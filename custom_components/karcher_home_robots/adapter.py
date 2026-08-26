# SPDX-License-Identifier: MIT
"""Adapter — the ONLY module that imports karcher or accesses private symbols.

Responsibilities (ARCHITECTURE.md):
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
  4. Exception translation: karcher-home exceptions — and the unchecked
     ValueError get_devices() raises for a robot model outside its Product
     enum — are mapped to ClientError subclasses before leaving this module
     (ARCHITECTURE.md, error taxonomy).

Allowlisted private symbols used in this module (ARCHITECTURE.md,
mirrored in ALLOWED_PRIVATE_API in tests/tools/check_imports.py):
  _mqtt                    — bind the paho message callback
  _mqtt.on_message         — set the adapter's threadsafe bridge
  _update_device_properties — bypass the stale get_device_properties cache
  subscribe_device         — undocumented but required subscription entry-point
  unsubscribe_device       — paired with subscribe_device
  _device_props            — internal cache dict; read to project DTO
  net_stauts               — DeviceProperties typo field (work-around)

HA imports are TYPE_CHECKING-only at module level; no runtime
homeassistant.* import is permitted here (ARCHITECTURE.md).
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import logging
import threading
import time
import types
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import aiohttp
import karcher.consts as _karcher_consts
import karcher.device as _karcher_device
from karcher.consts import ROBOT_PROPERTIES, TENANT_ID, Language
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
    UnsupportedDeviceError,
    ValidationError,
)
from .map_data import MapSnapshot as _MapSnapshot
from .map_parser import parse_map as _parse_map

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

import karcher as _karcher_pkg  # noqa: E402 — version probe; adapter is the only karcher importer


class _PatchedProduct(StrEnum):
    RCV3 = "1528986273083777024"
    RCV5 = "1540149850806333440"
    RCF5 = "1599715149861306368"
    RVM4 = "1946123509838999552"


_karcher_consts.Product = _PatchedProduct
_karcher_device.Product = _PatchedProduct
Product = _PatchedProduct

KARCHER_HOME_VERSION: str = vars(_karcher_pkg).get("__version__", "unknown")

# Timeout (seconds) for a blocking prop.get round-trip (request + reply).
_FETCH_TIMEOUT = 5.0
# The station fields are a best-effort extra request on a model that may not
# know them; keep its wait short so a silent robot costs the poll little.
_STATION_TIMEOUT = 2.0

# Consumables the library's own ROBOT_PROPERTIES list omits. Filtered against it
# so a library that later adopts one of them cannot produce a duplicate key.
_CONSUMABLE_PROPERTIES = ("main_brush", "side_brush", "hypa", "mop_life")
_CORE_PROPERTIES: tuple[str, ...] = (
    *ROBOT_PROPERTIES,
    *(prop for prop in _CONSUMABLE_PROPERTIES if prop not in ROBOT_PROPERTIES),
)

_SILENT_REAUTH_WINDOW = 300.0  # 5-minute window
_SILENT_REAUTH_MAX_ATTEMPTS = 3
_SILENT_REAUTH_BACKOFF = (5.0, 30.0, 120.0)  # seconds per attempt

# HTTP status codes used in _patch_download and _translate_exception.
_HTTP_OK = 200
_HTTPS_PORT = 443
_HTTP_RATE_LIMIT = 429

# get_rooms() and get_map_snapshot() both call client.get_map_data() and are
# routinely called back-to-back (async_setup, map-change refresh) for the same
# logical refresh. Cache the raw payload briefly so that pair collapses to one
# cloud round-trip instead of two identical ones.
_MAP_DATA_CACHE_TTL = 5.0


def _device_topic(product_id: str, sn: str, suffix: str) -> str:
    """Build a device MQTT topic: /mqtt/{product_id}/{sn}/thing/{suffix}."""
    return f"/mqtt/{product_id}/{sn}/thing/{suffix}"


# Display names for the product IDs karcher.consts.Product knows about. Kärcher
# writes these with a space ("RCV 5"); the enum member names do not.
#
# "RCF5" is keyed on the pinned library's actual enum member name, but the
# vendor app's own source (com/irobotix/common/device/IotBase.java in the
# decompiled APK, product ID 1599715149861306368) calls this model "RCF3" —
# python-karcher's member name is a mislabel. Overridden here so our own
# display is correct regardless of whether/when that gets fixed upstream;
# the enum member itself stays RCF5 until then, since renaming a published
# enum member is a breaking change for python-karcher's other consumers.
#
# RVF7 isn't a member of the pinned PyPI karcher-home's Product enum — it's
# only ever resolved if a user has manually installed a patched build (e.g.
# gucio1200/python-karcher) that adds it. The entry is cosmetic-only: harmless
# for everyone else, and gives that member a properly spaced label instead of
# the raw enum name if it's ever present at runtime.
_MODEL_NAMES: dict[str, str] = {
    "RCV3": "RCV 3",
    "RCV5": "RCV 5",
    "RCF5": "RCF 3",
    "RVM4": "RVM 4",
    "RVF7": "RVF 7",
}


def _model_name(product_id: str) -> str:
    """Human-readable model for the HA device registry.

    Falls back to the raw product ID for a model the pinned library doesn't
    know, so the device still registers honestly rather than under the wrong
    model (entity.py used to hardcode "RCV5" for every device).
    """
    try:
        member = Product(product_id)
    except ValueError:
        return product_id
    # str(): karcher-home ships no stubs, so member.name is Any under --strict.
    name = str(member.name)
    return _MODEL_NAMES.get(name, name)


def _envelope(method: str, params: Mapping[str, Any], *, version: str = "3.0") -> str:
    """Serialise the standard thing-service request envelope to a JSON string."""
    return json.dumps(
        {
            "method": method,
            "msgId": str(get_timestamp_ms()),
            "tenantId": TENANT_ID,
            "version": version,
            "params": dict(params),
        }
    )


@dataclass(frozen=True)
class Device:
    """Opaque device handle returned by get_devices().

    Wraps the upstream karcher Device so the coordinator never sees the
    upstream type (ARCHITECTURE.md).
    """

    device_id: str
    sn: str
    product_id: str
    nickname: str
    mac: str
    product_mode_code: str
    # Display model ("RCV 5", "RCF 5", ...), derived from product_id by
    # _model_name() so entity.py can fill DeviceInfo without importing karcher.
    model: str = ""


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
    ClientError subclasses (ARCHITECTURE.md, error taxonomy).

    Accepts an optional karcher_factory callable so tests can inject a
    FakeKarcherClient without patching karcher.* internals
    (ARCHITECTURE.md).
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
        _PathCb = Callable[[list[tuple[float, float, float, int]]], None]
        self._path_callbacks: dict[str, _PathCb] = {}
        # The dispatcher currently bound to the client's MQTT on_message, or
        # None. Tracked by identity (not a flag): if the library rebuilds its
        # MQTT client or rebinds on_message, the stale reference no longer
        # matches and the dispatcher is reinstalled.
        self._installed_dispatcher: Callable[[str, bytes], None] | None = None
        # Devices currently subscribed, keyed by SN — used to replay
        # subscriptions after a re-login rebuilds client-side MQTT state.
        self._subscribed_devices: dict[str, Device] = {}
        # Listeners for service_invoke_reply topics: topic → (event, result_holder).
        # result_holder is a 1-element list so the sync thread can write the payload.
        self._reply_listeners: dict[str, tuple[threading.Event, list[Any]]] = {}
        # charge_station_type is not a field on karcher-home's DeviceProperties
        # dataclass (v0.5.1), so its own .update() silently drops it — see
        # _harvest_station_fields. Cached here from raw JSON instead, keyed by
        # sn, and merged (never replaced wholesale) like the library's own cache.
        self._station_props: dict[str, dict[str, int]] = {}
        self._reauth_attempts: int = 0
        self._reauth_window_start: float = 0.0
        # Shared across coordinators: only one login() fires at a time.
        self._reauth_lock: asyncio.Lock = asyncio.Lock()
        self._last_reauth_ts: float = 0.0  # loop.time() of last successful reauth
        # Short-TTL cache of the raw get_map_data() reply, keyed by SN, so
        # get_rooms() + get_map_snapshot() called back-to-back share one fetch.
        self._map_data_cache: dict[str, tuple[float, Any]] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self, endpoint_snapshot: dict[str, str | None] | None = None) -> None:
        """Create the upstream client; separated from __init__ so the factory can be awaited.

        When *endpoint_snapshot* carries both a resolved REST and MQTT URL, the
        client is seeded from it and region discovery (KarcherHome.create()) is
        skipped — this lets HA restart reconnect while the discovery endpoint is
        down but the broker is up. An absent or incomplete snapshot runs live
        discovery as before.
        """
        rest_url: str | None = None
        mqtt_url: str | None = None
        if endpoint_snapshot is not None:
            rest_url = endpoint_snapshot.get("rest_base_url")
            mqtt_url = endpoint_snapshot.get("mqtt_url")
        seed = rest_url is not None and mqtt_url is not None

        if self._factory is not None:
            raw = self._factory()
        else:  # pragma: no cover — real client construction requires live network
            raw = await self._create_upstream(seed)

        if rest_url is not None and mqtt_url is not None:
            self._apply_endpoint_seed(raw, rest_url, mqtt_url)
        self._client = raw

    async def _create_upstream(self, seed: bool) -> Any:  # pragma: no cover — requires live network
        """Construct the real upstream client: bare (seeded) or via region discovery."""
        if seed:
            raw = KarcherHome()
        else:
            country = _REGION_TO_COUNTRY.get(self._config.region, "GB")
            try:
                raw = await KarcherHome.create(country=country)
            except (aiohttp.ClientError, OSError) as exc:
                raise NetworkError(str(exc)) from exc
        _patch_download(raw)
        return raw

    def _apply_endpoint_seed(self, raw: Any, rest_url: str, mqtt_url: str) -> None:
        """Seed a bare client with stored endpoints, reproducing create() minus discovery."""
        raw._base_url = (
            rest_url  # private-api: _base_url — seed stored REST endpoint, skip discovery
        )
        raw._mqtt_url = (
            mqtt_url  # private-api: _mqtt_url — seed stored broker endpoint, skip discovery
        )
        # Parity with create(country=…): _country drives the map-fetch countryCode,
        # _language the request lang header. Both default differently in the bare
        # constructor, so set them the way create() would.
        raw._country = _REGION_TO_COUNTRY.get(  # private-api: _country — parity with create()
            self._config.region, "GB"
        )
        raw._language = Language.EN  # private-api: _language — parity with create() default

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

    async def ensure_credentials(self, email: str, password: str) -> None:
        """Re-login if *password* differs from the credentials this adapter holds.

        The shared adapter authenticates once with whatever credentials created
        it. A sibling config entry carrying a refreshed password (after reauth)
        must push it here, or silent_reauth keeps retrying the stale password and
        the reauth never takes effect. No-op when the credentials are unchanged.

        On failure the previous credentials are restored so coordinators still
        sharing the adapter are not left pointing at a password that never
        authenticated.
        """
        if email == self._email and password == self._password:
            return
        prev_email, prev_password = self._email, self._password
        self._email = email
        self._password = password
        try:
            await self._login()
        except Exception:
            self._email = prev_email
            self._password = prev_password
            raise
        # Re-login may rebuild client-side MQTT state; replay subscriptions and
        # re-bind the dispatcher so push survives (mirrors silent_reauth).
        await self._restore_push_pipeline()

    async def _login(self) -> None:
        client = self._require_client()
        try:
            await client.login(self._email, self._password)
        except KarcherHomeException as exc:
            # _translate_exception maps auth failures to AuthError subclasses
            # and everything else to TransientError subclasses — a bare
            # ClientError here escaped every caller's except clauses and
            # failed setup with a stack trace instead of ConfigEntryNotReady.
            raise _translate_exception(exc) from exc

    async def silent_reauth(self) -> None:
        """Attempt a silent token refresh with exponential backoff.

        Policy: 3 attempts per 5-minute window, delays 5s / 30s / 2min.
        Raises AuthError when the window is exhausted or credentials are wrong.

        When multiple coordinators share this adapter they may call silent_reauth
        concurrently on the same TokenRejected event. The lock serialises the
        bookkeeping and the login itself, but the backoff sleep runs OUTSIDE the
        lock so other coordinators on the account are not blocked for up to two
        minutes. Latecomers check _last_reauth_ts (on lock entry and again after
        the sleep) and return early when another caller already refreshed.
        """
        entry_ts = asyncio.get_running_loop().time()
        delay = await self._reserve_reauth_attempt(entry_ts)
        if delay is None:
            return  # another caller already refreshed the token
        # Back off without holding the lock.
        await asyncio.sleep(delay)
        await self._perform_reauth_login(entry_ts)

    async def _reserve_reauth_attempt(self, entry_ts: float) -> float | None:
        """Claim a reauth attempt under the lock; return its backoff, or None to skip."""
        async with self._reauth_lock:
            now = asyncio.get_running_loop().time()
            # If another caller already refreshed the token while we waited for
            # the lock, skip our own login — the token is already fresh.
            if self._last_reauth_ts > entry_ts:
                return None

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
            return delay

    async def _perform_reauth_login(self, entry_ts: float) -> None:
        """Log in under the lock and replay the push pipeline, unless superseded."""
        async with self._reauth_lock:
            if self._last_reauth_ts > entry_ts:
                return  # another caller refreshed while we slept
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
            # Re-login may rebuild client-side MQTT state, discarding the bound
            # dispatcher and broker-side subscriptions. Replay both so push
            # survives the reauth; the coordinator's post-reauth fetch retry
            # covers data freshness.
            await self._restore_push_pipeline()

    async def _restore_push_pipeline(self) -> None:
        """Replay device subscriptions and re-bind the MQTT dispatcher.

        Best-effort: a failed replay for one device is logged at DEBUG and does
        not block the others — the next poll surfaces persistent problems.
        """
        client = self._require_client()
        loop = asyncio.get_running_loop()
        for device in list(self._subscribed_devices.values()):
            try:
                await self._hass.async_add_executor_job(
                    client.subscribe_device,  # private-api: subscribe_device
                    _to_kdevice(device),
                )
            except KarcherHomeException as exc:
                _LOGGER.debug("Subscription replay failed for %s: %s", device.sn, exc)
        self._ensure_dispatcher(client, loop)

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------

    async def get_devices(self) -> list[Device]:
        client = self._require_client()
        try:
            raw_devices = await client.get_devices()
        except KarcherHomeException as exc:
            raise _translate_exception(exc) from exc
        except ValueError as exc:
            # karcher.device.Device.__init__ (upstream) resolves Product(product_id)
            # eagerly for every device in get_devices()'s own list comprehension, so
            # a single robot model outside karcher.consts.Product raises ValueError
            # before ANY device on the account — including already-supported ones —
            # is returned. Device.__init__ also parses `status` and `versions` per
            # device, which can raise ValueError/JSONDecodeError (a ValueError
            # subclass) for unrelated malformed-payload reasons — the message below
            # is a likely cause, not a certainty, since the library gives us no way
            # to tell which field failed. Treated as permanent (not retried): the
            # dominant real-world cause is an unrecognised model, which retrying
            # cannot fix, and it needs the device removed from the account or the
            # pinned library updated to know it.
            raise UnsupportedDeviceError(
                "The Kärcher cloud account has a device this integration's pinned "
                "library could not parse — most likely an unrecognised robot model. "
                "Device discovery failed for every robot on the account, not just "
                "that one."
            ) from exc
        devices: list[Device] = []
        for d in raw_devices:
            product_id = getattr(d.product_id, "value", str(d.product_id))
            devices.append(
                Device(
                    device_id=str(d.device_id),
                    sn=str(d.sn),
                    product_id=product_id,
                    nickname=str(d.nickname),
                    mac=str(getattr(d, "mac", "")),
                    product_mode_code=str(getattr(d, "product_mode_code", "")),
                    model=_model_name(product_id),
                )
            )
        return devices

    async def _fetch_map_data(self, device: Device) -> Any:
        """Fetch the raw map payload, sharing a short-TTL cache across callers.

        get_rooms() and get_map_snapshot() both need this payload and are
        routinely called back-to-back for the same logical refresh; a cache
        hit here saves a duplicate cloud round-trip.
        """
        now = asyncio.get_running_loop().time()
        cached = self._map_data_cache.get(device.sn)
        if cached is not None and now - cached[0] < _MAP_DATA_CACHE_TTL:
            return cached[1]

        client = self._require_client()
        kdev = _to_kdevice(device)
        try:
            raw_map = await client.get_map_data(kdev)
        except KarcherHomeException as exc:
            raise _translate_exception(exc) from exc
        self._map_data_cache[device.sn] = (now, raw_map)
        return raw_map

    async def get_rooms(self, device: Device) -> list[Room]:
        """Return rooms from the map protobuf; empty list if no map is available."""
        try:
            raw_map = await self._fetch_map_data(device)
        except ClientError:
            raise
        except Exception as exc:
            # Unexpected errors (e.g. protobuf decode failures) when the
            # robot has no map loaded yet.
            _LOGGER.debug("get_rooms failed (no map?): %s", exc)
            return []

        room_data = getattr(raw_map, "data", {}).get("room_data_info", [])
        rooms: list[Room] = []
        for r in room_data:
            try:
                rooms.append(Room(room_id=int(r["room_id"]), name=str(r["room_name"])))
            except (KeyError, TypeError, ValueError) as exc:
                _LOGGER.debug("Skipping malformed room entry %s: %s", r, exc)
        return rooms

    async def get_map_snapshot(self, device: Device) -> _MapSnapshot | None:
        """Fetch and parse the current map; returns None when no map is available.

        The CDN download is async aiohttp end-to-end; only the pure parse runs here.
        """
        try:
            raw_map = await self._fetch_map_data(device)
        except ClientError:
            raise
        except Exception as exc:
            _LOGGER.debug("get_map_snapshot failed (no map?): %s", exc)
            return None

        raw_data: dict[str, Any] = getattr(raw_map, "data", {}) or {}
        snap = _parse_map(raw_data)
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
        on_path: Callable[[list[tuple[float, float, float, int]]], None] | None = None,
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
        self._subscribed_devices[sn] = device

        loop = asyncio.get_running_loop()

        try:
            await self._hass.async_add_executor_job(
                client.subscribe_device,  # private-api: subscribe_device
                _to_kdevice(device),
            )
        except KarcherHomeException as exc:
            raise _translate_exception(exc) from exc

        # Install a single dispatching handler on the MQTT client.  On subsequent
        # subscribe() calls the handler is usually already in place (it reads from
        # the live _push_callbacks / _path_callbacks dicts) — detected by identity,
        # so a rebuilt MQTT client or a rebound on_message gets the dispatcher
        # reinstalled rather than silently losing push.
        self._ensure_dispatcher(client, loop)

        _LOGGER.debug("Subscribed to push updates for device %s", sn)

    def _ensure_dispatcher(self, client: Any, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the dispatcher to the client's current MQTT object if not already bound."""
        mqtt = getattr(client, "_mqtt", None)  # private-api: _mqtt
        if mqtt is None:
            return
        current = getattr(mqtt, "on_message", None)  # private-api: _mqtt.on_message
        if self._installed_dispatcher is not None and current is self._installed_dispatcher:
            return
        self._install_mqtt_dispatcher(client, mqtt, loop)

    def _install_mqtt_dispatcher(
        self, client: Any, mqtt: Any, loop: asyncio.AbstractEventLoop
    ) -> None:
        """Bind a single dispatching on_message to *mqtt*.

        Callers go through _ensure_dispatcher, which skips the call when the
        current on_message is already this adapter's dispatcher.
        """
        original = getattr(mqtt, "on_message", None)

        def _dispatcher(topic: str, payload: bytes) -> None:
            # Runs on the paho thread. Nothing here may raise: an escaping
            # exception kills the network loop, and — before the reply listener
            # is signalled in the finally below — strands every waiter on this
            # topic, which surfaces as a bogus "reply not received" timeout.
            try:
                matched_sn: str | None = None
                for registered_sn in list(self._push_callbacks):
                    if f"/{registered_sn}/" in topic:
                        matched_sn = registered_sn
                        break
                if matched_sn is not None:
                    try:
                        if "thing/event/cur_path/post" in topic:
                            self._dispatch_cur_path(client, loop, matched_sn, payload)
                        elif "thing/event/property/post" in topic:
                            self._dispatch_property_post(client, loop, matched_sn, payload)
                        elif "thing/service/property/get_reply" in topic:
                            self._harvest_station_reply(matched_sn, payload)
                    except Exception:
                        _LOGGER.debug("Dispatch failed for %s", topic, exc_info=True)
                # Always call the library's original handler so its internal
                # state machine (device-property cache, wait events) keeps
                # working. It indexes reply payloads by bare key, so an
                # unexpected reply shape raises KeyError here — log and carry on.
                if original is not None:
                    try:
                        original(topic, payload)
                    except Exception:
                        _LOGGER.debug("Library handler failed for %s", topic, exc_info=True)
            finally:
                # Signalled last so a waiter wakes only after the library has
                # applied the reply to its property cache.
                if (listener := self._reply_listeners.get(topic)) is not None:
                    listener[1].append(payload)
                    listener[0].set()

        mqtt.on_message = _dispatcher  # private-api: _mqtt.on_message
        self._installed_dispatcher = _dispatcher

    def _dispatch_property_post(
        self,
        client: Any,
        loop: asyncio.AbstractEventLoop,
        msg_sn: str,
        payload: bytes,
    ) -> None:
        try:
            data: dict[str, Any] = json.loads(payload)
            params: Any = data.get("params", {})
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            _LOGGER.debug("property/post parse error: %s", exc)
            return
        if not params or not isinstance(params, Mapping):
            return
        _harvest_station_fields(self._station_props.setdefault(msg_sn, {}), params)
        # Work-around bug 1: _process_mqtt_message ignores property/post; manually
        # call _update_device_properties so the in-memory cache is updated before
        # snapshotting.  private-api: _update_device_properties
        # Work-around bug 2: library accesses net_status but the DeviceProperties
        # field is misspelled net_stauts (PROTOCOL.md §7). The cache is updated
        # before the AttributeError fires, so _project_properties can still read
        # the new values — suppress and continue.
        with contextlib.suppress(AttributeError):
            # private-api: _update_device_properties
            client._update_device_properties(msg_sn, params)
        props = _project_properties(client, msg_sn, self._station_props.get(msg_sn))
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

    def _harvest_station_reply(self, msg_sn: str, payload: bytes) -> None:
        """Pull charge_station_type/dust_action out of a prop.get reply's raw JSON.

        Runs on the paho thread inside the dispatcher — must never raise. Needed
        because karcher-home's DeviceProperties.update() (device.py) filters
        incoming keys against its own dataclass fields and charge_station_type
        is not one of them, so it never reaches client._device_props otherwise.
        """
        try:
            data: dict[str, Any] = json.loads(payload)
            reply_data: Any = data.get("data", {})
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            _LOGGER.debug("property/get_reply parse error: %s", exc)
            return
        if not reply_data or not isinstance(reply_data, Mapping):
            return
        _harvest_station_fields(self._station_props.setdefault(msg_sn, {}), reply_data)

    def _dispatch_cur_path(
        self,
        client: Any,
        loop: asyncio.AbstractEventLoop,
        msg_sn: str,
        payload: bytes,
    ) -> None:
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

    async def unsubscribe(self, device: Device) -> None:
        if self._client is None:
            return
        sn = device.sn
        self._push_callbacks.pop(sn, None)
        self._path_callbacks.pop(sn, None)
        self._subscribed_devices.pop(sn, None)
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
        topic = _device_topic(device.product_id, device.sn, f"service_invoke/{service}")
        payload = _envelope(f"service.{service}", dict(params))
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
        topic = _device_topic(device.product_id, device.sn, "service_invoke/set_preference")
        payload = _envelope(
            "service.set_preference",
            {"map_id": map_id, "prefer_type": 1, "room_preference": room_preference},
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
        Raises TransientError on timeout so the coordinator keeps its cache
        instead of overwriting it with an empty result.
        """
        client = self._require_client()
        # Same dispatcher dependency as the poll path — see _prop_get.
        self._ensure_dispatcher(client, asyncio.get_running_loop())
        reply_topic = _device_topic(
            device.product_id, device.sn, "service_invoke_reply/get_preference"
        )
        result = await self._hass.async_add_executor_job(
            partial(
                _get_preference_sync,
                client,
                product_id=device.product_id,
                sn=device.sn,
                map_id=map_id,
                reply_topic=reply_topic,
                reply_listeners=self._reply_listeners,
                timeout=_FETCH_TIMEOUT,
            )
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
        topic = _device_topic(device.product_id, device.sn, "service_invoke/set_preference_type")
        payload = _envelope("service.set_preference_type", {"prefer_type": prefer_type})
        _LOGGER.debug("set_preference_type prefer_type=%d", prefer_type)
        await self._hass.async_add_executor_job(_mqtt_publish, client, topic, payload)

    async def set_property(
        self,
        device: Device,
        params: Mapping[str, Any],
    ) -> None:
        client = self._require_client()
        topic = _device_topic(device.product_id, device.sn, "service/property/set")
        payload = _envelope("prop.set", dict(params), version="1.0")
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
            await self._prop_get(client, sn, product_id, _CORE_PROPERTIES, _FETCH_TIMEOUT)
        except KarcherHomeException as exc:
            raise _translate_exception(exc) from exc

        # Station fields go in their own request: they are absent from models
        # without a Suction Station, and firmware that rejects a prop.get over
        # one unknown key would otherwise take the whole poll down with it.
        # Best-effort — the robot's own properties are what the poll is for.
        try:
            await self._prop_get(client, sn, product_id, _STATION_FIELDS, _STATION_TIMEOUT)
        except (ClientError, KarcherHomeException) as exc:
            _LOGGER.debug("Station prop.get failed (model may not support it): %s", exc)

        props = _project_properties(client, sn, self._station_props.get(sn))
        if props is None:
            _LOGGER.debug("No properties available for %s", sn)
            raise ValidationError("No properties available")
        return props

    async def _prop_get(
        self,
        client: Any,
        sn: str,
        product_id: str,
        properties: tuple[str, ...],
        timeout_s: float,
    ) -> None:
        """Publish one prop.get and await its reply in the executor.

        The reply is signalled by this adapter's dispatcher, so a client whose
        MQTT object was rebuilt (dropping the binding) would otherwise time out
        on every poll until the next subscribe. _ensure_dispatcher is
        identity-checked — a no-op when the binding is still in place.
        """
        self._ensure_dispatcher(client, asyncio.get_running_loop())
        await self._hass.async_add_executor_job(
            partial(
                _prop_get_sync,
                client,
                sn=sn,
                product_id=product_id,
                properties=properties,
                reply_listeners=self._reply_listeners,
                timeout=timeout_s,
            )
        )


# ---------------------------------------------------------------------------
# Module-level helpers (not part of the public API)
# ---------------------------------------------------------------------------


async def _guard_download_url(url: str) -> None:
    """Reject a cloud-supplied map download URL that points at a non-public host.

    The map downloadUrl is built from cloud JSON (cdnDomain/dir); a compromised
    cloud could return an internal URL and turn this HA-side fetch into an SSRF
    probe of the local network. Enforce https and reject any host that resolves
    to a private/loopback/link-local/reserved address.

    Defense-in-depth only: the URL arrives over the cert-pinned REST channel, so
    a cloud able to forge it is already trusted for that leg, and this check does
    not stop DNS rebinding (the attacker also controls the malicious host's DNS).
    Airtight prevention would require pinning the resolved IP through to connect,
    which is more than this surface warrants.
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise NetworkError(f"refusing non-https map download URL (scheme {parts.scheme!r})")
    host = parts.hostname
    if not host:
        raise NetworkError("refusing map download URL with no host")

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, parts.port or _HTTPS_PORT)
    except OSError as exc:
        raise NetworkError(f"map download URL host did not resolve: {exc}") from exc

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise NetworkError("refusing map download URL that resolves to a non-public address")


def _patch_download(client: Any) -> None:
    """Work-around upstream bug (d): KarcherHome._download uses resp.status_code
    (requests-style) instead of resp.status (aiohttp) in its error path.

    The bug only surfaces when a map download URL returns non-200, so the robot
    appears to have no rooms even when it does. We replace _download with a
    corrected version bound to the same instance.
    """

    async def _fixed_download(self: Any, url: str) -> bytes:
        await _guard_download_url(url)
        headers = {"User-Agent": "Android_" + TENANT_ID}
        resp: aiohttp.ClientResponse = await self._http.get(url, headers=headers)
        if resp.status != _HTTP_OK:
            raise KarcherHomeException(-1, f"HTTP error: {resp.status}")
        data = await resp.content.read(-1)
        resp.close()
        return data

    client._download = types.MethodType(_fixed_download, client)


def _property_get_payload(properties: tuple[str, ...]) -> str:
    return _envelope("prop.get", {"property": list(properties)})


def _prop_get_sync(
    client: Any,
    *,
    sn: str,
    product_id: str,
    properties: tuple[str, ...],
    reply_listeners: dict[str, tuple[threading.Event, list[Any]]],
    timeout: float,
) -> None:
    """Publish prop.get for *properties* and block until the reply arrives.

    Called in the executor. The wait runs on the adapter's own _reply_listeners
    (signalled by the dispatcher) rather than the library's _wait_events, which
    karcher-home leaves unset when the robot answers with a non-zero ``code`` —
    an error reply was indistinguishable from no reply at all.
    """
    reply_topic = get_device_topic_property_get_reply(product_id, sn)

    # Register the listener before publishing so we do not miss the reply.
    event = threading.Event()
    holder: list[Any] = []
    reply_listeners[reply_topic] = (event, holder)

    mqtt = getattr(client, "_mqtt", None)  # private-api: _mqtt
    if mqtt is None:
        reply_listeners.pop(reply_topic, None)
        raise BrokerDisconnect("MQTT client not connected during fetch")

    publish_topic = _device_topic(product_id, sn, "service/property/get")
    try:
        mqtt.publish(publish_topic, _property_get_payload(properties))
        reply = _await_prop_get_reply(event, holder, timeout)
    finally:
        reply_listeners.pop(reply_topic, None)

    if reply is None:
        # SN intentionally omitted: this message reaches WARNING/INFO via the
        # coordinator outage logger, and SN must not appear above DEBUG.
        _LOGGER.debug("prop.get reply not received within %.0fs for %s", timeout, sn)
        raise TransientError(f"prop.get reply not received within {timeout:.0f}s")

    code = _reply_code(reply)
    if code:
        _LOGGER.debug("prop.get rejected with code %s for %s (%s)", code, sn, properties)
        raise TransientError(f"prop.get rejected by the robot with code {code}")


def _await_prop_get_reply(event: threading.Event, holder: list[Any], timeout: float) -> Any:
    """Wait up to *timeout* for a get_reply payload, newest first.

    Replies do carry a msgId, but no capture proves it echoes the request's
    (capture_station_props.py redacts the field), so matching on it risks
    discarding every genuine reply. The listener is registered immediately
    before the publish instead, which bounds what can land in *holder*.
    """
    deadline = time.monotonic() + timeout
    if not event.wait(max(deadline - time.monotonic(), 0.0)) or not holder:
        return None
    return holder[-1]


def _reply_code(payload: Any) -> int:
    """Return the reply's ``code``; 0 when absent or unparseable (assume success)."""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError) as exc:
        _LOGGER.debug("property/get_reply code parse error: %s", exc)
        return 0
    if not isinstance(data, Mapping):
        return 0
    return _int_or_none(data.get("code")) or 0


def _get_preference_sync(
    client: Any,
    *,
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

    publish_topic = _device_topic(product_id, sn, "service_invoke/get_preference")
    try:
        mqtt.publish(publish_topic, _get_preference_payload(map_id))
        replied = event.wait(timeout)
    finally:
        reply_listeners.pop(reply_topic, None)

    if not replied or not holder:
        # A timeout must NOT masquerade as a genuine empty reply: returning
        # {"rooms": [], ...} here would make the coordinator wipe real cached
        # preferences and flip prefer_mode to "standard" on one MQTT hiccup.
        # Raise so the coordinator keeps its cache (its fetch wraps this in a
        # best-effort try/except that leaves prefer_mode/room_preferences intact).
        _LOGGER.debug("get_preference: no reply within %.0fs for %s", timeout, sn)
        raise TransientError(f"get_preference reply not received within {timeout:.0f}s")

    return _parse_preference_reply(holder[0], _empty)


def _get_preference_payload(map_id: int) -> str:
    return _envelope("service.get_preference", {"map_id": map_id})


def _parse_preference_reply(raw_reply: Any, empty: dict[str, Any]) -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads(raw_reply)
        inner: dict[str, Any] = data.get("data", {})
        raw: Any = inner.get("room", [])
        prefer_on = int(inner.get("prefer_on", 0))
        return {
            "rooms": raw if isinstance(raw, list) else [],
            "prefer_on": prefer_on,
        }
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
        _LOGGER.debug("get_preference reply parse error: %s", exc)
        return empty


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


def _project_properties(
    client: Any, sn: str, station: Mapping[str, int] | None = None
) -> _DeviceProperties | None:
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

    # getattr throughout: this runs on the paho thread via
    # _dispatch_property_post, so an upstream dataclass change must degrade to
    # None rather than raise in the MQTT thread.
    map_id = getattr(raw, "current_map_id", None)
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
        custom_type=_int_or_none(getattr(raw, "custom_type", None)),
        current_map_id=str(map_id) if map_id is not None else None,
        main_brush=_int_or_none(getattr(raw, "main_brush", None)),
        side_brush=_int_or_none(getattr(raw, "side_brush", None)),
        hypa=_int_or_none(getattr(raw, "hypa", None)),
        mop_life=_int_or_none(getattr(raw, "mop_life", None)),
        # Not karcher-home dataclass fields (charge_station_type) or not
        # requested by the library's own polling (dust_action) — sourced from
        # the adapter's own raw-JSON side cache instead. See _harvest_station_fields.
        charge_station_type=None if station is None else station.get("charge_station_type"),
        dust_action=None if station is None else station.get("dust_action"),
    )


_CUR_PATH_FIELDS_PER_POSE = 4  # x, y, phi, flag
# Wire format: [startPoseId, x0, y0, phi0, flag0, ..., xN, yN, phiN, flagN, endMarker]
# Minimum: startPoseId + 1 pose + endMarker = 6 elements (doc/PROTOCOL.md §13.1).
_CUR_PATH_MIN_LEN = 1 + _CUR_PATH_FIELDS_PER_POSE + 1


def _parse_cur_path(raw: Any) -> list[tuple[float, float, float, int]]:
    """Parse a cur_path float array into (x, y, phi, flag) 4-tuples.

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
    result: list[tuple[float, float, float, int]] = []
    for i in range(n_points):
        with contextlib.suppress(TypeError, ValueError, IndexError):
            x = float(raw[i * 4 + 1])
            y = float(raw[i * 4 + 2])
            phi = float(raw[i * 4 + 3])
            flag = int(raw[i * 4 + 4])
            result.append((x, y, phi, flag))
    return result


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    with contextlib.suppress(TypeError, ValueError):
        return int(value)
    return None


_STATION_FIELDS = ("charge_station_type", "dust_action")


def _harvest_station_fields(dest: dict[str, int], data: Mapping[str, Any]) -> None:
    """Merge charge_station_type/dust_action from a raw payload into *dest*.

    Merges in place rather than replacing — the same last-known-value semantics
    as karcher-home's own DeviceProperties.update(), so a delta push carrying
    only one of the two fields never clobbers the other.
    """
    for key in _STATION_FIELDS:
        value = _int_or_none(data.get(key))
        if value is not None:
            dest[key] = value


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
