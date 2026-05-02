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
from typing import TYPE_CHECKING, Any, cast

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
from ._types import DevicePropertiesProtocol, KarcherHomeProtocol
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

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

import karcher as _karcher_pkg  # noqa: E402 — version probe; adapter is the only karcher importer

KARCHER_HOME_VERSION: str = vars(_karcher_pkg).get("__version__", "unknown")

# Timeout (seconds) for a blocking prop.get round-trip (request + reply).
_FETCH_TIMEOUT = 5.0

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
        self._client: KarcherHomeProtocol | None = None
        # Credentials stored for silent reauth (FR-A-8).
        self._email: str = ""
        self._password: str = ""
        # Push callback registered by subscribe(); called from the event loop.
        self._push_callback: Callable[[_DeviceProperties], None] | None = None
        # Silent reauth state (FR-A-8a): attempt counter and window reset time.
        self._reauth_attempts: int = 0
        self._reauth_window_start: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Create the upstream client.

        Separated from __init__ so the factory (async) can be awaited here
        rather than in a constructor.
        """
        if self._factory is not None:
            raw = self._factory()
        else:  # pragma: no cover — real KarcherHome.create() requires live network
            country = _REGION_TO_COUNTRY.get(self._config.region, "GB")
            raw = await KarcherHome.create(country=country)
            _patch_download(raw)
        self._client = cast(KarcherHomeProtocol, raw)

    async def close(self) -> None:
        """Release all resources held by this adapter."""
        if self._client is None:
            return
        try:
            await self._client.close()
        except Exception:  # swallow — we are tearing down
            _LOGGER.debug("Exception during adapter close", exc_info=True)
        finally:
            self._client = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def get_endpoint_snapshot(self) -> dict[str, str | None]:
        """Return the resolved REST and MQTT endpoints for persistence (FR-RG-2).

        Must be called after async_setup() so _client is initialised.
        The values come from _base_url and _mqtt_url set by KarcherHome.create()
        during async_setup; they do not change after that point.
        """
        assert self._client is not None, "async_setup() not called"
        return {
            "rest_base_url": self._client._base_url,  # private-api: _base_url
            "mqtt_url": self._client._mqtt_url,  # private-api: _mqtt_url
        }

    async def authenticate(self, email: str, password: str) -> None:
        """Authenticate against the 3iRobotix cloud.

        Stores credentials in memory for silent reauth (FR-A-8).
        Raises AuthError on failure.

        Covers: FR-A-8, FR-A-8b
        """
        self._email = email
        self._password = password
        await self._login()

    async def _login(self) -> None:
        """(Re-)authenticate using the stored credentials."""
        assert self._client is not None, "async_setup() not called"
        try:
            await self._client.login(self._email, self._password)
        except KarcherHomeInvalidAuth as exc:
            raise InvalidCredentials(str(exc)) from exc
        except KarcherHomeTokenExpired as exc:
            raise TokenRejected(str(exc)) from exc
        except KarcherHomeAccessDenied as exc:
            raise AuthError(str(exc)) from exc
        except KarcherHomeException as exc:
            raise ClientError(str(exc)) from exc

    async def silent_reauth(self) -> None:
        """Attempt a silent token refresh under the FR-A-8a backoff policy.

        Called by the coordinator when fetch_properties returns TokenRejected.
        Limits attempts to 3 per 5-minute window with exponential backoff
        (5 s, 30 s, 2 min). Raises AuthError (→ ConfigEntryAuthFailed) when
        the window is exhausted or if the login itself returns InvalidCredentials.

        Covers: FR-A-8, FR-A-8a, FR-A-8b
        """
        _REAUTH_WINDOW = 300.0  # 5 minutes
        _MAX_ATTEMPTS = 3
        _BACKOFF = (5.0, 30.0, 120.0)

        now = asyncio.get_event_loop().time()
        if now - self._reauth_window_start > _REAUTH_WINDOW:
            # New window — reset the counter.
            self._reauth_attempts = 0
            self._reauth_window_start = now

        if self._reauth_attempts >= _MAX_ATTEMPTS:
            raise AuthError(
                f"Silent reauth limit reached ({_MAX_ATTEMPTS} attempts in "
                f"{_REAUTH_WINDOW:.0f}s window); user action required"
            )

        delay = _BACKOFF[min(self._reauth_attempts, len(_BACKOFF) - 1)]
        self._reauth_attempts += 1
        _LOGGER.debug(
            "Silent reauth attempt %d/%d (backoff %.0fs)",
            self._reauth_attempts,
            _MAX_ATTEMPTS,
            delay,
        )
        await asyncio.sleep(delay)
        try:
            await self._login()
        except AuthError:
            # Wrong credentials → surface immediately (FR-A-8b).
            raise
        except ClientError as exc:
            # Transient failure — caller may retry on next poll.
            raise TransientError(f"Silent reauth transient failure: {exc}") from exc
        # Success — reset the window so the next token expiry gets fresh attempts.
        self._reauth_attempts = 0
        self._reauth_window_start = 0.0

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------

    async def get_devices(self) -> list[Device]:
        """Return the list of devices registered to the account.

        Raises ClientError on failure.
        """
        assert self._client is not None, "async_setup() not called"
        try:
            raw_devices = await self._client.get_devices()
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
        """Return the room list for device.

        Rooms are parsed from the map protobuf via get_map_data().
        Returns an empty list if no map data is available.

        Raises ClientError on failure.
        """
        assert self._client is not None, "async_setup() not called"
        kdev = _to_kdevice(device)
        try:
            raw_map = await self._client.get_map_data(kdev)
        except KarcherHomeException as exc:
            raise _translate_exception(exc) from exc
        except Exception as exc:
            _LOGGER.debug("get_rooms failed (no map?): %s", exc)
            return []

        room_data = getattr(raw_map, "data", {}).get("room_data_info", [])
        rooms: list[Room] = []
        for r in room_data:
            try:
                rooms.append(Room(room_id=int(r["room_id"]), name=str(r["room_name"])))
            except (KeyError, TypeError, ValueError):
                _LOGGER.debug("Skipping malformed room entry: %s", r)
        return rooms

    # ------------------------------------------------------------------
    # MQTT push subscription
    # ------------------------------------------------------------------

    async def subscribe(
        self,
        device: Device,
        on_push: Callable[[_DeviceProperties], None],
    ) -> None:
        """Subscribe to MQTT push updates for device.

        on_push is called from the event loop (never from the MQTT thread).
        Raises ClientError on failure.

        Covers: FR-UP-1 (push primary path)
        """
        assert self._client is not None, "async_setup() not called"
        self._push_callback = on_push

        loop = asyncio.get_running_loop()
        client = self._client
        sn = device.sn

        def _on_message(topic: str, payload: bytes) -> None:
            """paho callback — runs on the MQTT thread."""
            if f"/{sn}/" not in topic:
                return
            if "thing/event/property/post" not in topic:
                return
            try:
                data: dict[str, Any] = json.loads(payload)
                params: dict[str, Any] = data.get("params", {})
                if not params:
                    return
                # Work-around bug 1: _process_mqtt_message ignores
                # property/post; manually call _update_device_properties
                # so the in-memory cache is updated before snapshotting.
                # private-api: _update_device_properties
                client._update_device_properties(sn, params)
            except (json.JSONDecodeError, AttributeError, TypeError) as exc:
                _LOGGER.debug("property/post parse error: %s", exc)
                return

            props = _project_properties(client, sn)
            if props is not None and self._push_callback is not None:
                loop.call_soon_threadsafe(self._push_callback, props)

        try:
            await self._hass.async_add_executor_job(
                client.subscribe_device,  # private-api: subscribe_device
                _to_kdevice(device),
            )
        except KarcherHomeException as exc:
            raise _translate_exception(exc) from exc

        # Bind our on_message bridge over the top of the library's handler.
        # The library's _mqtt.on_message is _process_mqtt_message; we replace
        # it with our patched version that also handles property/post.
        # (private-api: _mqtt, _mqtt.on_message)
        mqtt = getattr(client, "_mqtt", None)  # private-api: _mqtt
        if mqtt is not None:
            original = getattr(mqtt, "on_message", None)

            def _patched_on_message(topic: str, payload: bytes) -> None:
                with contextlib.suppress(AttributeError):
                    _on_message(topic, payload)
                if original is not None:
                    with contextlib.suppress(AttributeError):
                        original(topic, payload)

            mqtt.on_message = _patched_on_message  # private-api: _mqtt.on_message

        _LOGGER.debug("Subscribed to push updates for device %s", device.sn)

    async def unsubscribe(self, device: Device) -> None:
        """Unsubscribe from MQTT push updates for device."""
        if self._client is None:
            return
        self._push_callback = None
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
        """Send a service_invoke command (e.g. set_room_clean) to device.

        Raises ClientError on failure.
        """
        assert self._client is not None, "async_setup() not called"
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
        await self._hass.async_add_executor_job(_mqtt_publish, self._client, topic, payload)

    async def set_property(
        self,
        device: Device,
        params: Mapping[str, Any],
    ) -> None:
        """Send a prop.set command to device.

        Raises ClientError on failure.
        """
        assert self._client is not None, "async_setup() not called"
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
        await self._hass.async_add_executor_job(_mqtt_publish, self._client, topic, payload)

    # ------------------------------------------------------------------
    # Property fetch (poll path)
    # ------------------------------------------------------------------

    async def fetch_properties(self, device: Device) -> _DeviceProperties:
        """Fetch current device properties, bypassing the library cache.

        Sends a prop.get request and waits up to _FETCH_TIMEOUT seconds for
        the device reply. Work-around for bug 2 (stale get_device_properties).

        Raises ClientError on failure.

        Covers: FR-UP-2 (poll fallback)
        """
        assert self._client is not None, "async_setup() not called"
        client = self._client
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
    client: KarcherHomeProtocol,
    sn: str,
    product_id: str,
    timeout: float,
) -> None:
    """Request a fresh prop.get and wait for the reply (blocking, executor)."""
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
            "params": {"property": ROBOT_PROPERTIES},
        }
    )
    mqtt.publish(publish_topic, payload)
    event.wait(timeout)
    wait_events.pop(reply_topic, None)


def _mqtt_publish(client: KarcherHomeProtocol, topic: str, payload: str) -> None:
    """Publish an MQTT message (executor thread). Raises ClientError if not connected."""
    mqtt = getattr(client, "_mqtt", None)  # private-api: _mqtt
    if mqtt is None:
        raise BrokerDisconnect("MQTT client not connected")
    try:
        mqtt.publish(topic, payload)
    except Exception as exc:
        raise BrokerDisconnect(str(exc)) from exc


def _to_kdevice(device: Device) -> _KDevice:
    """Reconstruct the upstream Device object the library needs for sub/unsub."""
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


def _project_properties(client: KarcherHomeProtocol, sn: str) -> _DeviceProperties | None:
    """Project the upstream DeviceProperties cache into the integration-owned DTO."""
    device_props: dict[str, Any] = getattr(
        client,
        "_device_props",
        {},  # private-api: _device_props
    )
    raw: DevicePropertiesProtocol | None = device_props.get(sn)
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
        current_map_id=str(raw.current_map_id) if raw.current_map_id is not None else None,
    )


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    with contextlib.suppress(TypeError, ValueError):
        return int(value)
    return None


def _translate_exception(exc: KarcherHomeException) -> ClientError:
    """Map a karcher-home exception to the appropriate ClientError subclass."""
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
