# SPDX-License-Identifier: MIT
"""Adapter — the ONLY module that imports karcher or accesses private symbols.

Responsibilities (ADR-0001, spec/04-architecture.md §3):
  1. Async boundary: karcher-home has a mixed sync/async API. Async methods
     (login, get_devices, get_map_data, close, create) are awaited directly.
     Sync/blocking methods (subscribe_device, unsubscribe_device, MQTT publish,
     fetch_properties round-trip) run in the executor via async_add_executor_job.
  2. Foreign-thread bridge: paho-mqtt delivers callbacks on its network
     thread. All re-entry into the event loop goes through
     loop.call_soon_threadsafe. Coordinator state is never mutated from
     the MQTT thread.
  3. Work-around containment: the net_stauts typo, the stale
     get_device_properties cache, the missing region= constructor
     parameter, and the _download resp.status_code typo are patched
     here; the coordinator sees clean data.
  4. Exception translation: karcher-home exceptions are mapped to
     ClientError subclasses before leaving this module (ADR-0003).

Allowlisted private symbols used in this module (spec/03 §3.1,
mirrored in ALLOWED_PRIVATE_API in tests/tools/check_imports.py):
  _mqtt                    — bind the paho message callback
  _mqtt.on_message         — set the adapter's threadsafe bridge
  _update_device_properties — bypass the stale get_device_properties cache
  subscribe_device         — undocumented but required subscription entry-point
  unsubscribe_device       — paired with subscribe_device
  _device_props            — internal cache dict; read to project DTO
  _wait_events             — internal event dict; used for fetch_properties
  net_stauts               — DeviceProperties typo field (work-around)

HA imports are TYPE_CHECKING-only at module level; no runtime
homeassistant.* import is permitted here (spec/04 §3, ADR-0002).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import types
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import aiohttp
from karcher.consts import ROBOT_PROPERTIES, TENANT_ID, Product
from karcher.device import Device as _KDevice
from karcher.exception import (
    KarcherHomeAccessDenied,
    KarcherHomeException,
    KarcherHomeInvalidAuth,
    KarcherHomeTokenExpired,
)
from karcher.karcher import KarcherHome
from karcher.mqtt import get_device_topic_property_get_reply
from karcher.utils import get_timestamp_ms

from ._types import DeviceProperties as _DeviceProperties
from .exceptions import (
    AuthError,
    BrokerDisconnect,
    ClientError,
    InvalidCredentials,
    NetworkError,
    RateLimited,
    TokenRejected,
    TransientError,
    ValidationError,
)
from .map_data import MapSnapshot as _MapSnapshot
from .map_parser import parse_map as _parse_map

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

import karcher as _karcher_pkg  # noqa: E402 — version probe; adapter is the only karcher importer

KARCHER_HOME_VERSION: str = vars(_karcher_pkg).get("__version__", "unknown")

# Timeout (seconds) for a blocking prop.get round-trip (request + reply).
_FETCH_TIMEOUT = 5.0

_SILENT_REAUTH_WINDOW = 300.0  # 5-minute window
_SILENT_REAUTH_MAX_ATTEMPTS = 3
_SILENT_REAUTH_BACKOFF = (5.0, 30.0, 120.0)  # seconds per attempt

# HTTP status codes used in _patch_download and _translate_exception.
_HTTP_OK = 200
_HTTP_RATE_LIMIT = 429


@dataclass(frozen=True)
class Device:
    """Opaque device handle returned by get_devices().

    Wraps the upstream karcher Device so the coordinator never sees the
    upstream type (ADR-0001).
    """

    device_id: str
    sn: str
    product_id: str
    nickname: str
    mac: str
    product_mode_code: str


@dataclass(frozen=True)
class Room:
    """Room handle returned by get_rooms()."""

    room_id: int
    name: str


# Maps the user-visible region choice to a seed country code accepted by
# KarcherHome.create(). The country just drives region discovery; we use a
# single canonical country per region so the mapping is unambiguous.
_REGION_TO_COUNTRY: dict[str, str] = {
    "eu": "GB",
    "us": "US",
    "cn": "CN",
}


class AdapterConfig:
    """Construction parameters for KarcherAdapter."""

    def __init__(self, region: str = "eu") -> None:
        self.region = region


class KarcherAdapter:
    """Thin async wrapper around karcher-home.

    Runs every blocking call in the default executor and bridges
    paho-mqtt foreign-thread callbacks into the event loop via
    loop.call_soon_threadsafe. Maps karcher-home exceptions into
    ClientError subclasses (ADR-0003).

    Accepts an optional karcher_factory callable so tests can inject a
    FakeKarcherClient without patching karcher.* internals
    (spec/04-architecture.md §10).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config: AdapterConfig,
        karcher_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._hass = hass
        self._config = config
        self._factory = karcher_factory
        self._client: Any = None
        self._email: str = ""
        self._password: str = ""
        # Per-device callbacks keyed by SN so multiple coordinators can share one adapter.
        self._push_callbacks: dict[str, Callable[[_DeviceProperties], None]] = {}
        self._path_callbacks: dict[str, Callable[[list[tuple[float, float, int]]], None]] = {}
        self._dispatcher_installed: bool = False
        # Listeners for service_invoke_reply topics: topic → (event, result_holder).
        # result_holder is a 1-element list so the sync thread can write the payload.
        self._reply_listeners: dict[str, tuple[threading.Event, list[Any]]] = {}
        self._reauth_attempts: int = 0
        self._reauth_window_start: float = 0.0
        # Shared across coordinators: only one login() fires at a time.
        self._reauth_lock: asyncio.Lock = asyncio.Lock()
        self._last_reauth_ts: float = 0.0  # loop.time() of last successful reauth

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Create the upstream client; separated from __init__ so the factory can be awaited."""
        if self._factory is not None:
            raw = self._factory()
        else:  # pragma: no cover — real KarcherHome.create() requires live network
            country = _REGION_TO_COUNTRY.get(self._config.region, "GB")
            try:
                raw = await KarcherHome.create(country=country)
            except (aiohttp.ClientError, OSError) as exc:
                raise NetworkError(str(exc)) from exc
            _patch_download(raw)
        self._client = raw

    async def close(self) -> None:
        if self._client is None:
            return
        try:
            await self._client.close()
        except Exception:  # swallow — we are tearing down
            _LOGGER.debug("Exception during adapter close", exc_info=True)
        finally:
            self._client = None

    def _require_client(self) -> Any:
        if self._client is None:
            raise RuntimeError("KarcherAdapter.async_setup() was not called")
        return self._client

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def get_endpoint_snapshot(self) -> dict[str, str | None]:
        """Return the resolved REST and MQTT endpoints; call after async_setup()."""
        client = self._require_client()
        return {
            "rest_base_url": client._base_url,  # private-api: _base_url
            "mqtt_url": client._mqtt_url,  # private-api: _mqtt_url
        }

    async def authenticate(self, email: str, password: str) -> None:
        """Authenticate against the 3iRobotix cloud; stores credentials for silent reauth."""
        self._email = email
        self._password = password
        await self._login()

    async def _login(self) -> None:
        client = self._require_client()
        try:
            await client.login(self._email, self._password)
        except KarcherHomeInvalidAuth as exc:
            raise InvalidCredentials(str(exc)) from exc
        except KarcherHomeTokenExpired as exc:
            raise TokenRejected(str(exc)) from exc
        except KarcherHomeAccessDenied as exc:
            raise AuthError(str(exc)) from exc
        except KarcherHomeException as exc:
            raise ClientError(str(exc)) from exc

    async def silent_reauth(self) -> None:
        """Attempt a silent token refresh with exponential backoff.

        Policy: 3 attempts per 5-minute window, delays 5s / 30s / 2min.
        Raises AuthError when the window is exhausted or credentials are wrong.

        When multiple coordinators share this adapter they may call silent_reauth
        concurrently on the same TokenRejected event. The lock ensures only one
        login() fires; latecomers check _last_reauth_ts and return early if another
        caller already refreshed the token while they waited.
        """
        entry_ts = asyncio.get_running_loop().time()
        async with self._reauth_lock:
            now = asyncio.get_running_loop().time()
            # If another caller already refreshed the token while we waited for
            # the lock, skip our own login — the token is already fresh.
            if self._last_reauth_ts > entry_ts:
                return

            if now - self._reauth_window_start > _SILENT_REAUTH_WINDOW:
                self._reauth_attempts = 0
                self._reauth_window_start = now

            if self._reauth_attempts >= _SILENT_REAUTH_MAX_ATTEMPTS:
                raise AuthError(
                    f"Silent reauth limit reached ({_SILENT_REAUTH_MAX_ATTEMPTS} attempts in "
                    f"{_SILENT_REAUTH_WINDOW:.0f}s window); user action required"
                )

            delay = _SILENT_REAUTH_BACKOFF[
                min(self._reauth_attempts, len(_SILENT_REAUTH_BACKOFF) - 1)
            ]
            self._reauth_attempts += 1
            _LOGGER.debug(
                "Silent reauth attempt %d/%d (backoff %.0fs)",
                self._reauth_attempts,
                _SILENT_REAUTH_MAX_ATTEMPTS,
                delay,
            )
            await asyncio.sleep(delay)
            try:
                await self._login()
            except AuthError:
                raise
            except ClientError as exc:
                raise TransientError(f"Silent reauth transient failure: {exc}") from exc
            # Success — reset window and record timestamp for dedup.
            self._reauth_attempts = 0
            self._reauth_window_start = 0.0
            self._last_reauth_ts = asyncio.get_running_loop().time()

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------

    async def get_devices(self) -> list[Device]:
        client = self._require_client()
        try:
            raw_devices = await client.get_devices()
        except KarcherHomeException as exc:
            raise _translate_exception(exc) from exc
        return [
            Device(
                device_id=str(d.device_id),
                sn=str(d.sn),
                product_id=getattr(d.product_id, "value", str(d.product_id)),
                nickname=str(d.nickname),
                mac=str(getattr(d, "mac", "")),
                product_mode_code=str(getattr(d, "product_mode_code", "")),
            )
            for d in raw_devices
        ]

    async def get_rooms(self, device: Device) -> list[Room]:
        """Return rooms from the map protobuf; empty list if no map is available."""
        client = self._require_client()
        kdev = _to_kdevice(device)
        try:
            raw_map = await client.get_map_data(kdev)
        except KarcherHomeException as exc:
            raise _translate_exception(exc) from exc
        except Exception as exc:
            # KarcherHomeException is caught above and re-raised; this branch
            # catches unexpected errors (e.g. protobuf decode failures) when
            # the robot has no map loaded yet.
            _LOGGER.debug("get_rooms failed (no map?): %s", exc)
            return []

        room_data = getattr(raw_map, "data", {}).get("room_data_info", [])
        rooms: list[Room] = []
        for r in room_data:
            try:
                rooms.append(Room(room_id=int(r["room_id"]), name=str(r["room_name"])))
            except KeyError, TypeError, ValueError:
                _LOGGER.debug("Skipping malformed room entry: %s", r)
        return rooms

    async def get_map_snapshot(
        self,
        device: Device,
        cur_path: list[tuple[float, float]] | None = None,
    ) -> _MapSnapshot | None:
        """Fetch and parse the current map; returns None when no map is available.

        Blocking CDN download — must be called in the executor from the coordinator.
        """
        client = self._require_client()
        kdev = _to_kdevice(device)
        try:
            raw_map = await client.get_map_data(kdev)
        except KarcherHomeException as exc:
            raise _translate_exception(exc) from exc
        except Exception as exc:
            _LOGGER.debug("get_map_snapshot failed (no map?): %s", exc)
            return None

        raw_data: dict[str, Any] = getattr(raw_map, "data", {}) or {}
        snap = _parse_map(raw_data, cur_path or [])
        if snap is not None:
            _LOGGER.debug(
                "get_map_snapshot parsed: grid=%dx%d data_len=%d",
                snap.grid.width,
                snap.grid.height,
                len(snap.grid.data),
            )
        return snap

    # ------------------------------------------------------------------
    # MQTT push subscription
    # ------------------------------------------------------------------

    async def subscribe(
        self,
        device: Device,
        on_push: Callable[[_DeviceProperties], None],
        on_path: Callable[[list[tuple[float, float, int]]], None] | None = None,
    ) -> None:
        """Subscribe to MQTT push updates; callbacks are always called from the event loop.

        Multiple coordinators may subscribe to different devices on the same adapter.
        Callbacks are stored per-SN and dispatched by a single on_message handler so
        successive subscribe() calls do not clobber each other's callbacks.
        """
        client = self._require_client()
        sn = device.sn
        self._push_callbacks[sn] = on_push
        if on_path is not None:
            self._path_callbacks[sn] = on_path

        loop = asyncio.get_running_loop()

        try:
            await self._hass.async_add_executor_job(
                client.subscribe_device,  # private-api: subscribe_device
                _to_kdevice(device),
            )
        except KarcherHomeException as exc:
            raise _translate_exception(exc) from exc

        # Install a single dispatching handler on the MQTT client.  On subsequent
        # subscribe() calls the handler is already in place (it reads from the
        # live _push_callbacks / _path_callbacks dicts), so we only need to set
        # it once — detected by whether it's already our dispatcher.
        # (private-api: _mqtt, _mqtt.on_message)
        mqtt = getattr(client, "_mqtt", None)  # private-api: _mqtt
        if mqtt is not None and not self._dispatcher_installed:
            self._install_mqtt_dispatcher(client, mqtt, loop)

        _LOGGER.debug("Subscribed to push updates for device %s", sn)

    def _install_mqtt_dispatcher(
        self, client: Any, mqtt: Any, loop: asyncio.AbstractEventLoop
    ) -> None:
        """Bind a single dispatching on_message to *mqtt*; idempotent after first call."""
        original = getattr(mqtt, "on_message", None)

        def _dispatcher(topic: str, payload: bytes) -> None:
            if (listener := self._reply_listeners.get(topic)) is not None:
                listener[1].append(payload)
                listener[0].set()
            matched_sn: str | None = None
            for registered_sn in list(self._push_callbacks):
                if f"/{registered_sn}/" in topic:
                    matched_sn = registered_sn
                    break
            if matched_sn is not None:
                if "thing/event/cur_path/post" in topic:
                    _dispatch_cur_path(matched_sn, topic, payload)
                elif "thing/event/property/post" in topic:
                    _dispatch_property_post(matched_sn, payload)
            # Always call the library's original handler so its internal
            # state machine (fetch_properties wait events etc.) keeps working.
            if original is not None:
                with contextlib.suppress(AttributeError):
                    original(topic, payload)

        def _dispatch_property_post(msg_sn: str, payload: bytes) -> None:
            try:
                data: dict[str, Any] = json.loads(payload)
                params: dict[str, Any] = data.get("params", {})
                if not params:
                    return
                # Work-around bug 1: _process_mqtt_message ignores
                # property/post; manually call _update_device_properties
                # so the in-memory cache is updated before snapshotting.
                # private-api: _update_device_properties
                client._update_device_properties(msg_sn, params)
            except (json.JSONDecodeError, AttributeError, TypeError) as exc:
                _LOGGER.debug("property/post parse error: %s", exc)
                return
            props = _project_properties(client, msg_sn)
            cb = self._push_callbacks.get(msg_sn)
            if props is not None and cb is not None:
                loop.call_soon_threadsafe(cb, props)
            # cur_path is embedded in property/post params, not in a separate
            # cur_path/post topic (MqttMessageParser.java:65, PROTOCOL.md §13.1).
            path_cb = self._path_callbacks.get(msg_sn)
            if path_cb is not None:
                raw_path = params.get("cur_path")
                if raw_path is not None:
                    points = _parse_cur_path(raw_path)
                    if points:
                        loop.call_soon_threadsafe(path_cb, points)

        def _dispatch_cur_path(msg_sn: str, _topic: str, payload: bytes) -> None:
            cb = self._path_callbacks.get(msg_sn)
            if cb is None:
                return
            try:
                data: dict[str, Any] = json.loads(payload)
                raw: list[Any] = data.get("params", {}).get("cur_path", [])
                points = _parse_cur_path(raw)
            except (json.JSONDecodeError, AttributeError, TypeError) as exc:
                _LOGGER.debug("cur_path/post parse error: %s", exc)
                return
            if points:
                loop.call_soon_threadsafe(cb, points)

        mqtt.on_message = _dispatcher  # private-api: _mqtt.on_message
        self._dispatcher_installed = True

    async def unsubscribe(self, device: Device) -> None:
        if self._client is None:
            return
        sn = device.sn
        self._push_callbacks.pop(sn, None)
        self._path_callbacks.pop(sn, None)
        try:
            await self._hass.async_add_executor_job(
                self._client.unsubscribe_device,  # private-api: unsubscribe_device
                _to_kdevice(device),
            )
        except Exception:  # swallow — unsubscribe is best-effort
            _LOGGER.debug("Exception during unsubscribe", exc_info=True)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def send_command(
        self,
        device: Device,
        service: str,
        params: Mapping[str, Any],
    ) -> None:
        client = self._require_client()
        topic = f"/mqtt/{device.product_id}/{device.sn}/thing/service_invoke/{service}"
        payload = json.dumps(
            {
                "method": f"service.{service}",
                "msgId": str(get_timestamp_ms()),
                "tenantId": TENANT_ID,
                "version": "3.0",
                "params": dict(params),
            }
        )
        await self._hass.async_add_executor_job(_mqtt_publish, client, topic, payload)

    async def set_preference(
        self,
        device: Device,
        map_id: int,
        room_preference: list[list[Any]],
    ) -> None:
        """Store room cleaning order and per-room settings on the robot.

        room_preference: ordered list of 12-element arrays (APK: CustomSortRoomActivity.java).
        Cleaning order equals array order.
        """
        client = self._require_client()
        topic = f"/mqtt/{device.product_id}/{device.sn}/thing/service_invoke/set_preference"
        payload = json.dumps(
            {
                "method": "service.set_preference",
                "msgId": str(get_timestamp_ms()),
                "tenantId": TENANT_ID,
                "version": "3.0",
                "params": {
                    "map_id": map_id,
                    "prefer_type": 1,
                    "room_preference": room_preference,
                },
            }
        )
        _LOGGER.debug("set_preference map_id=%s rooms=%d", map_id, len(room_preference))
        await self._hass.async_add_executor_job(_mqtt_publish, client, topic, payload)

    async def get_preference(
        self,
        device: Device,
        map_id: int,
    ) -> dict[str, Any]:
        """Fetch the stored room preference from the robot.

        Returns {"rooms": [...], "prefer_on": int} where rooms is the raw
        room_preference array (list of 12-element lists) in cleaning order.
        prefer_on is 1 if Custom mode is active, 0 otherwise.
        Returns {"rooms": [], "prefer_on": 0} on timeout.
        """
        client = self._require_client()
        reply_topic = (
            f"/mqtt/{device.product_id}/{device.sn}/thing/service_invoke_reply/get_preference"
        )
        result = await self._hass.async_add_executor_job(
            _get_preference_sync,
            client,
            device.product_id,
            device.sn,
            map_id,
            reply_topic,
            self._reply_listeners,
            _FETCH_TIMEOUT,
        )
        _LOGGER.debug(
            "get_preference map_id=%s rooms=%d prefer_on=%d",
            map_id,
            len(result["rooms"]),
            result["prefer_on"],
        )
        return result

    async def set_preference_type(self, device: Device, prefer_type: int) -> None:
        """Set Standard (0) or Custom (1) cleaning mode on the robot."""
        client = self._require_client()
        topic = f"/mqtt/{device.product_id}/{device.sn}/thing/service_invoke/set_preference_type"
        payload = json.dumps(
            {
                "method": "service.set_preference_type",
                "msgId": str(get_timestamp_ms()),
                "tenantId": TENANT_ID,
                "version": "3.0",
                "params": {"prefer_type": prefer_type},
            }
        )
        _LOGGER.debug("set_preference_type prefer_type=%d", prefer_type)
        await self._hass.async_add_executor_job(_mqtt_publish, client, topic, payload)

    async def set_property(
        self,
        device: Device,
        params: Mapping[str, Any],
    ) -> None:
        client = self._require_client()
        topic = f"/mqtt/{device.product_id}/{device.sn}/thing/service/property/set"
        payload = json.dumps(
            {
                "method": "prop.set",
                "msgId": str(get_timestamp_ms()),
                "tenantId": TENANT_ID,
                "version": "1.0",
                "params": dict(params),
            }
        )
        await self._hass.async_add_executor_job(_mqtt_publish, client, topic, payload)

    # ------------------------------------------------------------------
    # Property fetch (poll path)
    # ------------------------------------------------------------------

    async def fetch_properties(self, device: Device) -> _DeviceProperties:
        """Fetch device properties via prop.get, bypassing the stale get_device_properties cache."""
        client = self._require_client()
        sn = device.sn
        product_id = device.product_id

        try:
            await self._hass.async_add_executor_job(
                _fetch_properties_sync, client, sn, product_id, _FETCH_TIMEOUT
            )
        except KarcherHomeException as exc:
            raise _translate_exception(exc) from exc

        props = _project_properties(client, sn)
        if props is None:
            raise ValidationError(f"No properties available for {sn}")
        return props


# ---------------------------------------------------------------------------
# Module-level helpers (not part of the public API)
# ---------------------------------------------------------------------------


def _patch_download(client: Any) -> None:
    """Work-around upstream bug (d): KarcherHome._download uses resp.status_code
    (requests-style) instead of resp.status (aiohttp) in its error path.

    The bug only surfaces when a map download URL returns non-200, so the robot
    appears to have no rooms even when it does. We replace _download with a
    corrected version bound to the same instance.
    """

    async def _fixed_download(self: Any, url: str) -> bytes:
        headers = {"User-Agent": "Android_" + TENANT_ID}
        resp: aiohttp.ClientResponse = await self._http.get(url, headers=headers)
        if resp.status != _HTTP_OK:
            raise KarcherHomeException(-1, f"HTTP error: {resp.status}")
        data = await resp.content.read(-1)
        resp.close()
        return data

    client._download = types.MethodType(_fixed_download, client)


def _fetch_properties_sync(
    client: Any,
    sn: str,
    product_id: str,
    timeout: float,
) -> None:
    reply_topic = get_device_topic_property_get_reply(product_id, sn)

    # Register the wait event before publishing so we do not miss the reply.
    event = threading.Event()
    wait_events: dict[str, threading.Event] = getattr(
        client,
        "_wait_events",
        {},  # private-api: _wait_events
    )
    wait_events[reply_topic] = event

    mqtt = getattr(client, "_mqtt", None)  # private-api: _mqtt
    if mqtt is None:
        wait_events.pop(reply_topic, None)
        raise BrokerDisconnect("MQTT client not connected during fetch")

    publish_topic = f"/mqtt/{product_id}/{sn}/thing/service/property/get"
    payload = json.dumps(
        {
            "method": "prop.get",
            "msgId": str(get_timestamp_ms()),
            "tenantId": TENANT_ID,
            "version": "3.0",
            "params": {
                "property": [
                    *ROBOT_PROPERTIES,
                    "main_brush",
                    "side_brush",
                    "hypa",
                    "mop_life",
                    "tank_state",
                    "cloth_state",
                ],
            },
        }
    )
    try:
        mqtt.publish(publish_topic, payload)
        replied = event.wait(timeout)
    finally:
        wait_events.pop(reply_topic, None)

    if not replied:
        raise TransientError(f"prop.get reply not received within {timeout:.0f}s for {sn}")


def _get_preference_sync(
    client: Any,
    product_id: str,
    sn: str,
    map_id: int,
    reply_topic: str,
    reply_listeners: dict[str, tuple[threading.Event, list[Any]]],
    timeout: float,
) -> dict[str, Any]:
    """Publish get_preference and block until the reply arrives or times out.

    Called in the executor. Uses the adapter's _reply_listeners dict (passed by
    reference) so the dispatcher (which runs on the MQTT thread) can signal us.

    Returns {"rooms": [...], "prefer_on": int}.
    """
    _empty: dict[str, Any] = {"rooms": [], "prefer_on": 0}
    event = threading.Event()
    holder: list[Any] = []
    reply_listeners[reply_topic] = (event, holder)

    mqtt = getattr(client, "_mqtt", None)  # private-api: _mqtt
    if mqtt is None:
        reply_listeners.pop(reply_topic, None)
        raise BrokerDisconnect("MQTT client not connected during get_preference")

    publish_topic = f"/mqtt/{product_id}/{sn}/thing/service_invoke/get_preference"
    payload = json.dumps(
        {
            "method": "service.get_preference",
            "msgId": str(get_timestamp_ms()),
            "tenantId": TENANT_ID,
            "version": "3.0",
            "params": {"map_id": map_id},
        }
    )
    try:
        mqtt.publish(publish_topic, payload)
        replied = event.wait(timeout)
    finally:
        reply_listeners.pop(reply_topic, None)

    if not replied or not holder:
        _LOGGER.debug("get_preference: no reply within %.0fs for %s", timeout, sn)
        return _empty

    try:
        data: dict[str, Any] = json.loads(holder[0])
        inner: dict[str, Any] = data.get("data", {})
        raw: Any = inner.get("room", [])
        prefer_on = int(inner.get("prefer_on", 0))
        return {
            "rooms": raw if isinstance(raw, list) else [],
            "prefer_on": prefer_on,
        }
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
        _LOGGER.debug("get_preference reply parse error: %s", exc)
        return _empty


def _mqtt_publish(client: Any, topic: str, payload: str) -> None:
    mqtt = getattr(client, "_mqtt", None)  # private-api: _mqtt
    if mqtt is None:
        raise BrokerDisconnect("MQTT client not connected")
    try:
        mqtt.publish(topic, payload)
    except Exception as exc:
        raise BrokerDisconnect(str(exc)) from exc


def _to_kdevice(device: Device) -> _KDevice:
    return _KDevice(
        deviceId=device.device_id,
        sn=device.sn,
        productId=Product(device.product_id),
        nickname=device.nickname,
        mac=device.mac,
        isDefault=False,
        isSelected=False,
        isShare=False,
        onlineTime=0,
        photoUrl="",
        productModeCode=device.product_mode_code,
        bindTime=0,
        roomId="",
        status=1,
        versions="[]",
    )


def _project_properties(client: Any, sn: str) -> _DeviceProperties | None:
    device_props: dict[str, Any] = getattr(
        client,
        "_device_props",
        {},  # private-api: _device_props
    )
    raw: Any = device_props.get(sn)
    if raw is None:
        return None

    # Touch net_stauts via getattr to confirm the typo field exists without
    # triggering AttributeError on nested access in the library internals.
    # (private-api: net_stauts)
    getattr(raw, "net_stauts", None)  # private-api: net_stauts

    return _DeviceProperties(
        battery=_int_or_none(getattr(raw, "quantity", None)),
        cleaning_area=_int_or_none(getattr(raw, "cleaning_area", None)),
        cleaning_time=_int_or_none(getattr(raw, "cleaning_time", None)),
        work_mode=_int_or_none(getattr(raw, "work_mode", None)),
        status=_int_or_none(getattr(raw, "status", None)),
        charge_state=_int_or_none(getattr(raw, "charge_state", None)),
        fault=_int_or_none(getattr(raw, "fault", None)),
        wind=_int_or_none(getattr(raw, "wind", None)),
        water=_int_or_none(getattr(raw, "water", None)),
        mode=_int_or_none(getattr(raw, "mode", None)),
        tank_state=_int_or_none(getattr(raw, "tank_state", None)),
        cloth_state=_int_or_none(getattr(raw, "cloth_state", None)),
        current_map_id=str(raw.current_map_id) if raw.current_map_id is not None else None,
        main_brush=_int_or_none(getattr(raw, "main_brush", None)),
        side_brush=_int_or_none(getattr(raw, "side_brush", None)),
        hypa=_int_or_none(getattr(raw, "hypa", None)),
        mop_life=_int_or_none(getattr(raw, "mop_life", None)),
    )


_CUR_PATH_FIELDS_PER_POSE = 4  # x, y, phi, flag
# Wire format: [startPoseId, x0, y0, phi0, flag0, ..., xN, yN, phiN, flagN, endMarker]
# Minimum: startPoseId + 1 pose + endMarker = 6 elements (doc/PROTOCOL.md §13.1).
_CUR_PATH_MIN_LEN = 1 + _CUR_PATH_FIELDS_PER_POSE + 1


def _parse_cur_path(raw: Any) -> list[tuple[float, float, int]]:
    """Parse a cur_path float array into (x, y, flag) triples.

    Layout (doc/PROTOCOL.md §13.1, ControlMainActivity.java:2870):
        [startPoseId, x0, y0, phi0, flag0, ..., xN, yN, phiN, flagN, endMarker]
    The trailing endMarker is discarded. Validity: len >= 6 and (len-2) % 4 == 0.

    flag == 0 → transit/navigation move (PathMap.java:72, update==0 branch).
    flag != 0 → active cleaning pass.
    """
    if not isinstance(raw, list):
        return []
    n = len(raw)
    if n < _CUR_PATH_MIN_LEN or (n - 2) % _CUR_PATH_FIELDS_PER_POSE != 0:
        return []
    n_points = (n - 2) // _CUR_PATH_FIELDS_PER_POSE
    result: list[tuple[float, float, int]] = []
    for i in range(n_points):
        try:
            x = float(raw[i * 4 + 1])
            y = float(raw[i * 4 + 2])
            flag = int(raw[i * 4 + 4])
            result.append((x, y, flag))
        except TypeError, ValueError, IndexError:
            pass
    return result


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    with contextlib.suppress(TypeError, ValueError):
        return int(value)
    return None


def _translate_exception(exc: KarcherHomeException) -> ClientError:
    if isinstance(exc, KarcherHomeInvalidAuth):
        return InvalidCredentials(str(exc))
    if isinstance(exc, KarcherHomeTokenExpired):
        return TokenRejected(str(exc))
    if isinstance(exc, KarcherHomeAccessDenied):
        return AuthError(str(exc))
    if getattr(exc, "code", None) == _HTTP_RATE_LIMIT:
        return RateLimited(str(exc))
    return NetworkError(str(exc))


__all__ = [
    "AdapterConfig",
    "Device",
    "KarcherAdapter",
    "Room",
]
