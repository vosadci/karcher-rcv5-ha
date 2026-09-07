# SPDX-License-Identifier: MIT
"""Contract tests for KarcherAdapter.

Tests the adapter's observable behaviour from the coordinator's perspective
using a FakeKarcherClient injected via the karcher_factory parameter.
No real MQTT or HTTP connections are made.

"""

from __future__ import annotations

import asyncio
import base64
import json
import socket
import threading
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from custom_components.karcher_home_robots import adapter as adapter_module
from custom_components.karcher_home_robots._types import DeviceProperties
from custom_components.karcher_home_robots.adapter import (
    AdapterConfig,
    Device,
    KarcherAdapter,
    Room,
    _guard_download_url,
    _patch_download,
    _translate_exception,
)
from custom_components.karcher_home_robots.exceptions import (
    AuthError,
    BrokerDisconnect,
    ClientError,
    InvalidCredentials,
    NetworkError,
    TokenRejected,
    TransientError,
    UnsupportedDeviceError,
)
from karcher.exception import (
    KarcherHomeAccessDenied,
    KarcherHomeException,
    KarcherHomeInvalidAuth,
    KarcherHomeTokenExpired,
)

# ---------------------------------------------------------------------------
# Fake upstream client
# ---------------------------------------------------------------------------


class FakeMqtt:
    """Minimal paho-like MQTT stub."""

    def __init__(self) -> None:
        self.on_message: Any = None
        self.published: list[tuple[str, str]] = []

    def publish(self, topic: str, payload: str) -> None:
        self.published.append((topic, payload))

    def disconnect(self) -> None:
        pass


_RCV3_PRODUCT_ID = "1528986273083777024"  # Product.RCV3.value
_RCV5_PRODUCT_ID = "1540149850806333440"  # Product.RCV5.value
# Named after the pinned library's enum member (Product.RCF5), which mislabels
# this model — Kärcher's own catalog calls it RCF3 (doc/PROTOCOL.md §16.7).
_RCF5_PRODUCT_ID = "1599715149861306368"  # Product.RCF5.value
_RVM4_PRODUCT_ID = "1946123509838999552"  # Product.RVM4.value (patched in adapter)


class FakeUpstreamDevice:
    """Minimal upstream Device stub returned by get_devices()."""

    def __init__(self, **kwargs: Any) -> None:
        self.device_id = kwargs.get("device_id", "dev-1")
        self.sn = kwargs.get("sn", "SN001")
        # product_id must be a str-enum-like object with a .value attribute.
        self.product_id = _FakeProduct(kwargs.get("product_id", _RCV5_PRODUCT_ID))
        self.nickname = kwargs.get("nickname", "Robot")
        self.mac = kwargs.get("mac", "AA:BB:CC:DD:EE:FF")
        self.product_mode_code = kwargs.get("product_mode_code", "CRL350")


class _FakeProduct(str):
    """Minimal Product enum stub — has a .value property like karcher.consts.Product."""

    @property
    def value(self) -> str:
        return str(self)


class FakeUpstreamProps:
    """Minimal upstream DeviceProperties stub."""

    def __init__(self, **kwargs: Any) -> None:
        self.quantity = kwargs.get("quantity", 80)
        self.work_mode = kwargs.get("work_mode", 0)
        self.status = kwargs.get("status", 0)
        self.charge_state = kwargs.get("charge_state", 0)
        self.fault = kwargs.get("fault", 0)
        self.wind = kwargs.get("wind", 1)
        self.water = kwargs.get("water", 0)
        self.mode = kwargs.get("mode", 0)
        self.cleaning_area = kwargs.get("cleaning_area", 0)
        self.cleaning_time = kwargs.get("cleaning_time", 0)
        self.current_map_id = kwargs.get("current_map_id", "1")
        self.custom_type = kwargs.get("custom_type", 0)
        self.net_stauts: Any = None


class FakeKarcherClient:
    """Injectable fake that replaces the real KarcherHome client."""

    def __init__(self) -> None:
        self._mqtt: FakeMqtt = FakeMqtt()
        self._device_props: dict[str, FakeUpstreamProps] = {}
        self.login_calls: list[tuple[str, str]] = []
        self.get_devices_calls: int = 0
        self.subscribe_calls: list[Any] = []
        self.unsubscribe_calls: list[Any] = []
        self.get_map_data_calls: int = 0
        # Control what methods return/raise.
        self.login_exc: Exception | None = None
        self.get_devices_result: list[FakeUpstreamDevice] = [FakeUpstreamDevice()]
        self.get_devices_exc: Exception | None = None
        self.subscribe_exc: Exception | None = None
        self.map_data_result: Any = None
        self.map_data_exc: Exception | None = None

    async def login(self, email: str, password: str) -> None:
        self.login_calls.append((email, password))
        if self.login_exc:
            raise self.login_exc

    async def get_devices(self) -> list[FakeUpstreamDevice]:
        self.get_devices_calls += 1
        if self.get_devices_exc:
            raise self.get_devices_exc
        return self.get_devices_result

    def subscribe_device(self, dev: Any) -> None:
        self.subscribe_calls.append(dev)
        if self.subscribe_exc:
            raise self.subscribe_exc
        self._device_props[dev.sn] = FakeUpstreamProps()

    def unsubscribe_device(self, dev: Any) -> None:
        self.unsubscribe_calls.append(dev)
        self._device_props.pop(dev.sn, None)

    def _update_device_properties(self, sn: str, data: dict[str, Any]) -> None:
        if sn in self._device_props:
            for k, v in data.items():
                if hasattr(self._device_props[sn], k):
                    setattr(self._device_props[sn], k, v)

    async def get_map_data(self, dev: Any, map: int = 1) -> Any:
        self.get_map_data_calls += 1
        if self.map_data_exc:
            raise self.map_data_exc
        return self.map_data_result

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_client() -> FakeKarcherClient:
    return FakeKarcherClient()


@pytest.fixture
def fake_hass() -> MagicMock:
    """Minimal hass mock that runs executor jobs synchronously."""
    hass = MagicMock()

    async def async_add_executor_job(func: Any, *args: Any) -> Any:
        return func(*args)

    hass.async_add_executor_job = async_add_executor_job
    return hass


@pytest.fixture
async def adapter(fake_hass: MagicMock, fake_client: FakeKarcherClient) -> KarcherAdapter:
    """Adapter pre-configured with a FakeKarcherClient."""
    a = KarcherAdapter(
        hass=fake_hass,
        config=AdapterConfig(),
        karcher_factory=lambda: fake_client,
    )
    await a.async_setup()
    return a


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEVICE = Device(
    device_id="dev-1",
    sn="SN001",
    product_id=_RCV5_PRODUCT_ID,
    nickname="Robot",
    mac="AA:BB:CC:DD:EE:FF",
    product_mode_code="CRL350",
)


# ---------------------------------------------------------------------------
# async_setup
# ---------------------------------------------------------------------------


async def test_async_setup_stores_client(
    fake_hass: MagicMock, fake_client: FakeKarcherClient
) -> None:
    """factory injects the client without real network."""
    a = KarcherAdapter(hass=fake_hass, config=AdapterConfig(), karcher_factory=lambda: fake_client)
    assert a._client is None
    await a.async_setup()
    assert a._client is not None


# ---------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------


async def test_authenticate_calls_login(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """adapter passes credentials to the upstream client."""
    await adapter.authenticate("user@example.com", "secret")
    assert fake_client.login_calls == [("user@example.com", "secret")]


async def test_authenticate_stores_credentials(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """credentials are retained for silent reauth."""
    await adapter.authenticate("user@example.com", "secret")
    assert adapter._email == "user@example.com"
    assert adapter._password == "secret"  # noqa: S105


async def test_authenticate_invalid_credentials_raises(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """KarcherHomeInvalidAuth maps to InvalidCredentials."""
    fake_client.login_exc = KarcherHomeInvalidAuth()
    with pytest.raises(InvalidCredentials):
        await adapter.authenticate("bad@example.com", "wrong")


async def test_authenticate_token_expired_raises(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """KarcherHomeTokenExpired maps to TokenRejected."""
    fake_client.login_exc = KarcherHomeTokenExpired()
    with pytest.raises(TokenRejected):
        await adapter.authenticate("user@example.com", "pass")


async def test_authenticate_access_denied_raises(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """KarcherHomeAccessDenied maps to AuthError."""
    fake_client.login_exc = KarcherHomeAccessDenied("Forbidden")
    with pytest.raises(AuthError):
        await adapter.authenticate("user@example.com", "pass")


async def test_authenticate_generic_exception_raises(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """any KarcherHomeException maps to ClientError."""
    fake_client.login_exc = KarcherHomeException(500, "internal")
    with pytest.raises(ClientError):
        await adapter.authenticate("user@example.com", "pass")


# ---------------------------------------------------------------------------
# ensure_credentials
# ---------------------------------------------------------------------------


async def test_ensure_credentials_noop_when_unchanged(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Same credentials → no extra login."""
    await adapter.authenticate("user@example.com", "secret")
    await adapter.ensure_credentials("user@example.com", "secret")
    assert fake_client.login_calls == [("user@example.com", "secret")]


async def test_ensure_credentials_relogs_in_on_changed_password(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """A changed password triggers a re-login and replays the push pipeline."""
    await adapter.authenticate("user@example.com", "old")
    await adapter.subscribe(DEVICE, lambda _: None)
    n_subscribes = len(fake_client.subscribe_calls)

    fake_client._mqtt = FakeMqtt()  # re-login rebuilds MQTT state
    await adapter.ensure_credentials("user@example.com", "new")

    assert fake_client.login_calls[-1] == ("user@example.com", "new")
    assert adapter._password == "new"  # noqa: S105
    assert len(fake_client.subscribe_calls) == n_subscribes + 1
    assert fake_client._mqtt.on_message is not None


async def test_ensure_credentials_restores_previous_on_failure(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """A failed re-login rolls back to the previous credentials and re-raises."""
    await adapter.authenticate("user@example.com", "old")
    fake_client.login_exc = KarcherHomeInvalidAuth()

    with pytest.raises(InvalidCredentials):
        await adapter.ensure_credentials("user@example.com", "bad")

    assert adapter._email == "user@example.com"
    assert adapter._password == "old"  # noqa: S105


# ---------------------------------------------------------------------------
# get_devices
# ---------------------------------------------------------------------------


async def test_get_devices_returns_device_list(adapter: KarcherAdapter) -> None:
    """upstream Device is projected to integration-owned DTO."""
    devices = await adapter.get_devices()
    assert len(devices) == 1
    dev = devices[0]
    assert dev.sn == "SN001"
    assert dev.device_id == "dev-1"
    assert dev.product_id == _RCV5_PRODUCT_ID
    assert dev.nickname == "Robot"
    assert dev.model == "RCV 5"


@pytest.mark.parametrize(
    ("product_id", "expected_model"),
    [
        (_RCV3_PRODUCT_ID, "RCV 3"),
        (_RCV5_PRODUCT_ID, "RCV 5"),
        (_RCF5_PRODUCT_ID, "RCF 3"),  # Product.RCF5's product_id — vendor calls it RCF3
        # Kärcher's live catalog names this ID "RVM 4 Comfort"; there is no
        # separately catalogued base RVM 4 (doc/PROTOCOL.md §16.5-16.6).
        (_RVM4_PRODUCT_ID, "RVM 4 Comfort"),
    ],
)
async def test_get_devices_derives_model_per_product(
    adapter: KarcherAdapter,
    fake_client: FakeKarcherClient,
    product_id: str,
    expected_model: str,
) -> None:
    """Device.model is derived from product_id, not hardcoded to RCV5."""
    fake_client.get_devices_result = [FakeUpstreamDevice(product_id=product_id)]
    devices = await adapter.get_devices()
    assert devices[0].model == expected_model


async def test_get_devices_unrecognised_product_falls_back_to_raw_id(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """A product_id outside karcher.consts.Product still yields a device, labelled
    with its raw ID rather than mislabelled as RCV5. In practice this path is
    normally pre-empted by test_get_devices_unsupported_model_raises below, since
    the real library raises before returning such a device at all — this guards
    _model_name() directly in case a future library version is more lenient."""
    fake_client.get_devices_result = [FakeUpstreamDevice(product_id="9999999999999999999")]
    devices = await adapter.get_devices()
    assert devices[0].model == "9999999999999999999"


async def test_get_devices_exception_raises(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """upstream exception becomes NetworkError."""
    fake_client.get_devices_exc = KarcherHomeException(503, "unavailable")
    with pytest.raises(NetworkError):
        await adapter.get_devices()


async def test_get_devices_unsupported_model_raises_permanent_error(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """karcher-home's own get_devices() resolves Product(product_id) eagerly for
    every device in one list comprehension (karcher/karcher.py), so a robot model
    outside the enum raises a raw ValueError there — before any device on the
    account, including already-supported ones, is returned. Confirm this surfaces
    as a clear, non-retryable ClientError instead of an unhandled ValueError."""
    fake_client.get_devices_exc = ValueError("'9999999999999999999' is not a valid Product")
    with pytest.raises(UnsupportedDeviceError):
        await adapter.get_devices()


# ---------------------------------------------------------------------------
# get_rooms
# ---------------------------------------------------------------------------


async def test_get_rooms_empty_when_no_map(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """returns empty list when map data unavailable."""
    fake_client.map_data_exc = Exception("no map")
    rooms = await adapter.get_rooms(DEVICE)
    assert rooms == []


async def test_get_rooms_parses_room_data(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """room IDs and names projected from map protobuf."""
    map_mock = MagicMock()
    map_mock.data = {
        "room_data_info": [
            {"room_id": 1, "room_name": "Kitchen"},
            {"room_id": 2, "room_name": "Living Room"},
        ]
    }
    fake_client.map_data_result = map_mock
    rooms = await adapter.get_rooms(DEVICE)
    assert rooms == [Room(room_id=1, name="Kitchen"), Room(room_id=2, name="Living Room")]


async def test_get_rooms_skips_malformed_entries(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Malformed room entries are skipped; valid ones are projected."""
    map_mock = MagicMock()
    map_mock.data = {
        "room_data_info": [
            {"room_id": 1, "room_name": "Kitchen"},
            {"bad_key": "oops"},
        ]
    }
    fake_client.map_data_result = map_mock
    rooms = await adapter.get_rooms(DEVICE)
    assert len(rooms) == 1
    assert rooms[0].name == "Kitchen"


async def test_get_rooms_then_get_map_snapshot_shares_one_fetch(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """A get_rooms + get_map_snapshot pair (async_setup, map-change refresh)
    hits client.get_map_data() once, not twice."""
    grid_bytes = b"\x00" * (120 * 120)
    map_mock = MagicMock()
    map_mock.data = {
        "map_head": {"resolution": 0.05, "size_x": 120, "size_y": 120},
        "map_data": base64.b64encode(grid_bytes).decode(),
        "room_data_info": [{"room_id": 1, "room_name": "Kitchen"}],
    }
    fake_client.map_data_result = map_mock

    rooms = await adapter.get_rooms(DEVICE)
    snapshot = await adapter.get_map_snapshot(DEVICE)

    assert rooms == [Room(room_id=1, name="Kitchen")]
    assert snapshot is not None
    assert fake_client.get_map_data_calls == 1


async def test_get_rooms_refetches_after_cache_ttl_expires(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """The map-data cache is short-lived; a later call re-fetches instead of
    serving stale data forever."""
    map_mock = MagicMock()
    map_mock.data = {"room_data_info": [{"room_id": 1, "room_name": "Kitchen"}]}
    fake_client.map_data_result = map_mock

    await adapter.get_rooms(DEVICE)
    assert fake_client.get_map_data_calls == 1

    cache = adapter._map_data_cache
    ts, cached_map = cache[DEVICE.sn]
    cache[DEVICE.sn] = (ts - 60.0, cached_map)

    await adapter.get_rooms(DEVICE)
    assert fake_client.get_map_data_calls == 2


# ---------------------------------------------------------------------------
# subscribe / push path
# ---------------------------------------------------------------------------


async def test_subscribe_calls_subscribe_device(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """adapter calls the upstream subscribe_device."""
    await adapter.subscribe(DEVICE, lambda _: None)
    assert len(fake_client.subscribe_calls) == 1


async def test_subscribe_patches_on_message(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """The adapter replaces _mqtt.on_message with its threadsafe bridge."""
    original = fake_client._mqtt.on_message
    await adapter.subscribe(DEVICE, lambda _: None)
    assert fake_client._mqtt.on_message is not original
    assert fake_client._mqtt.on_message is not None


async def test_dispatcher_reinstalled_after_mqtt_rebuild(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """A rebuilt MQTT client gets the dispatcher re-bound on the next subscribe.

    Regression guard: the install check used a boolean flag, so a new _mqtt
    object (whose on_message is not the adapter's dispatcher) silently lost
    all push traffic for the rest of the session.
    """
    await adapter.subscribe(DEVICE, lambda _: None)
    assert fake_client._mqtt.on_message is not None

    # Simulate the library rebuilding its MQTT client (e.g. on re-login).
    fake_client._mqtt = FakeMqtt()
    assert fake_client._mqtt.on_message is None

    other = Device(
        device_id="dev-2",
        sn="SN002",
        product_id=_RCV5_PRODUCT_ID,
        nickname="Robot 2",
        mac="AA:BB:CC:DD:EE:F0",
        product_mode_code="CRL350",
    )
    await adapter.subscribe(other, lambda _: None)
    assert fake_client._mqtt.on_message is not None


async def test_silent_reauth_replays_subscriptions_and_dispatcher(
    adapter: KarcherAdapter,
    fake_client: FakeKarcherClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a successful re-login, subscriptions are replayed and the dispatcher re-bound."""
    monkeypatch.setattr(
        "custom_components.karcher_home_robots.adapter._SILENT_REAUTH_BACKOFF",
        (0.0, 0.0, 0.0),
    )
    await adapter.authenticate("user@example.com", "pw")
    await adapter.subscribe(DEVICE, lambda _: None)
    n_subscribes = len(fake_client.subscribe_calls)

    # Re-login rebuilds the MQTT client; dispatcher and subscriptions are gone.
    fake_client._mqtt = FakeMqtt()

    await adapter.silent_reauth()

    assert len(fake_client.subscribe_calls) == n_subscribes + 1
    assert fake_client.subscribe_calls[-1].sn == DEVICE.sn
    assert fake_client._mqtt.on_message is not None


async def test_silent_reauth_logs_and_continues_on_subscribe_replay_failure(
    adapter: KarcherAdapter,
    fake_client: FakeKarcherClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A KarcherHomeException during subscription replay is logged at DEBUG and does not abort."""
    monkeypatch.setattr(
        "custom_components.karcher_home_robots.adapter._SILENT_REAUTH_BACKOFF",
        (0.0, 0.0, 0.0),
    )
    await adapter.authenticate("user@example.com", "pw")
    await adapter.subscribe(DEVICE, lambda _: None)

    fake_client._mqtt = FakeMqtt()
    fake_client.subscribe_exc = KarcherHomeException(503, "replay failure")

    # Must not raise; the error is swallowed.
    await adapter.silent_reauth()

    # The dispatcher is still re-installed despite the subscription failure.
    assert fake_client._mqtt.on_message is not None


async def test_ensure_dispatcher_noop_when_already_installed(
    adapter: KarcherAdapter,
    fake_client: FakeKarcherClient,
) -> None:
    """_ensure_dispatcher returns early when on_message is already the adapter's dispatcher."""
    await adapter.subscribe(DEVICE, lambda _: None)
    first_on_message = fake_client._mqtt.on_message

    other = Device(
        device_id="dev-2",
        sn="SN002",
        product_id=_RCV5_PRODUCT_ID,
        nickname="Robot 2",
        mac="AA:BB:CC:DD:EE:F0",
        product_mode_code="CRL350",
    )
    # Second subscribe: dispatcher already installed, should not re-bind.
    await adapter.subscribe(other, lambda _: None)

    assert fake_client._mqtt.on_message is first_on_message


async def test_push_callback_invoked_on_property_post(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """property/post payload is parsed and callback fired."""
    received: list[DeviceProperties] = []
    await adapter.subscribe(DEVICE, received.append)

    payload = json.dumps(
        {
            "params": {
                "work_mode": 1,
                "quantity": 75,
                "status": 0,
                "charge_state": 0,
                "fault": 0,
                "wind": 1,
                "water": 0,
                "cleaning_area": 0,
                "cleaning_time": 0,
                "current_map_id": "1",
            }
        }
    ).encode()

    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/property/post"

    def fire_callback() -> None:
        fake_client._mqtt.on_message(topic, payload)

    thread = threading.Thread(target=fire_callback)
    thread.start()
    thread.join()

    # Give call_soon_threadsafe a chance to run.
    await asyncio.sleep(0)

    assert len(received) == 1
    assert received[0].battery == 75
    assert received[0].work_mode == 1


async def test_push_projects_custom_type(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """custom_type (Standard/Customise flag) is projected from the property push."""
    received: list[DeviceProperties] = []
    await adapter.subscribe(DEVICE, received.append)

    payload = json.dumps({"params": {"custom_type": 2}}).encode()
    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/property/post"
    fake_client._mqtt.on_message(topic, payload)
    await asyncio.sleep(0)

    assert len(received) == 1
    assert received[0].custom_type == 2


async def test_push_harvests_station_fields(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """dust_action is harvested from raw JSON even though FakeUpstreamProps has no such field.

    Mirrors the real karcher-home DeviceProperties dataclass, which does not
    define dust_action as a requested/known field on this path either — the
    side cache (_harvest_station_fields), not the library's own .update(),
    is what must make this survive.
    """
    received: list[DeviceProperties] = []
    await adapter.subscribe(DEVICE, received.append)

    payload = json.dumps({"params": {"dust_action": 2}}).encode()
    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/property/post"
    fake_client._mqtt.on_message(topic, payload)
    await asyncio.sleep(0)

    assert len(received) == 1
    assert received[0].dust_action == 2


async def test_station_fields_merge_across_pushes(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """A push carrying only dust_action must not clobber a previously-seen charge_station_type."""
    received: list[DeviceProperties] = []
    await adapter.subscribe(DEVICE, received.append)
    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/property/post"

    fake_client._mqtt.on_message(topic, json.dumps({"params": {"charge_station_type": 1}}).encode())
    await asyncio.sleep(0)
    fake_client._mqtt.on_message(topic, json.dumps({"params": {"dust_action": 2}}).encode())
    await asyncio.sleep(0)

    assert received[-1].charge_station_type == 1
    assert received[-1].dust_action == 2


async def test_get_reply_station_harvest_swallows_malformed_json(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Malformed get_reply payload must not crash the MQTT thread."""
    await adapter.subscribe(DEVICE, lambda _: None)
    reply_topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/service/property/get_reply"

    # Must not raise.
    fake_client._mqtt.on_message(reply_topic, b"not json")


async def test_get_reply_station_harvest_swallows_non_dict_json(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """A valid JSON scalar (e.g. a bare number) must not crash the MQTT thread.

    json.loads succeeds but the result has no .get(), which raises
    AttributeError rather than json.JSONDecodeError or TypeError.
    """
    await adapter.subscribe(DEVICE, lambda _: None)
    reply_topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/service/property/get_reply"

    # Must not raise.
    fake_client._mqtt.on_message(reply_topic, b"5")


async def test_get_reply_station_harvest_ignores_empty_data(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """A get_reply with no 'data' key leaves the station side cache untouched."""
    await adapter.subscribe(DEVICE, lambda _: None)
    reply_topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/service/property/get_reply"

    fake_client._mqtt.on_message(reply_topic, json.dumps({"code": 0}).encode())

    assert adapter._station_props.get("SN001") is None


async def test_push_ignores_unrelated_topics(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Messages for a different device SN are not delivered to the callback."""
    received: list[DeviceProperties] = []
    await adapter.subscribe(DEVICE, received.append)

    payload = json.dumps({"params": {"work_mode": 1, "quantity": 50}}).encode()
    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/OTHER_SN/thing/event/property/post"

    fake_client._mqtt.on_message(topic, payload)
    await asyncio.sleep(0)
    assert received == []


async def test_push_swallows_attribute_error_from_net_stauts(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """AttributeError from net_stauts does not crash the MQTT thread."""
    received: list[DeviceProperties] = []

    original_update = fake_client._update_device_properties

    def raise_attr_error(sn: str, data: dict[str, Any]) -> None:
        raise AttributeError("net_stauts typo simulation")

    fake_client._update_device_properties = raise_attr_error

    await adapter.subscribe(DEVICE, received.append)

    payload = json.dumps({"params": {"work_mode": 1}}).encode()
    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/property/post"

    # Must not raise.
    fake_client._mqtt.on_message(topic, payload)
    await asyncio.sleep(0)

    fake_client._update_device_properties = original_update


# ---------------------------------------------------------------------------
# unsubscribe
# ---------------------------------------------------------------------------


async def test_unsubscribe_calls_unsubscribe_device(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """unsubscribe delegates to upstream."""
    await adapter.subscribe(DEVICE, lambda _: None)
    await adapter.unsubscribe(DEVICE)
    assert len(fake_client.unsubscribe_calls) == 1


async def test_unsubscribe_clears_callback(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """After unsubscribe, no further push callbacks are invoked."""
    received: list[DeviceProperties] = []
    await adapter.subscribe(DEVICE, received.append)
    await adapter.unsubscribe(DEVICE)

    payload = json.dumps({"params": {"work_mode": 1}}).encode()
    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/property/post"
    fake_client._mqtt.on_message(topic, payload)
    await asyncio.sleep(0)
    assert received == []


# ---------------------------------------------------------------------------
# send_command
# ---------------------------------------------------------------------------


async def test_send_command_publishes_correct_topic(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """send_command publishes to service_invoke topic."""
    await adapter.subscribe(DEVICE, lambda _: None)
    await adapter.send_command(DEVICE, "set_room_clean", {"room_ids": [], "ctrl_value": 1})

    assert len(fake_client._mqtt.published) == 1
    topic, raw_payload = fake_client._mqtt.published[0]
    assert topic == f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/service_invoke/set_room_clean"
    payload = json.loads(raw_payload)
    assert payload["method"] == "service.set_room_clean"
    assert payload["params"]["ctrl_value"] == 1


async def test_send_command_without_mqtt_raises(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """BrokerDisconnect raised when MQTT client is absent."""
    fake_client._mqtt = None  # type: ignore[assignment]
    with pytest.raises(BrokerDisconnect):
        await adapter.send_command(DEVICE, "set_room_clean", {})


# ---------------------------------------------------------------------------
# set_property
# ---------------------------------------------------------------------------


async def test_set_property_publishes_prop_set(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """prop.set envelope."""
    await adapter.subscribe(DEVICE, lambda _: None)
    await adapter.set_property(DEVICE, {"wind": 2})

    assert len(fake_client._mqtt.published) == 1
    topic, raw_payload = fake_client._mqtt.published[0]
    assert topic == f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/service/property/set"
    payload = json.loads(raw_payload)
    assert payload["method"] == "prop.set"
    assert payload["version"] == "1.0"
    assert payload["params"]["wind"] == 2


# ---------------------------------------------------------------------------
# fetch_properties
# ---------------------------------------------------------------------------


_REPLY_TOPIC = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/service/property/get_reply"


def _reply_on_publish(
    fake_client: FakeKarcherClient,
    *,
    data: dict[str, Any] | None = None,
    code: int = 0,
    reply_to_station: bool = True,
) -> None:
    """Make the fake robot answer every prop.get on the get_reply topic.

    *reply_to_station* off models a robot that ignores the station-field
    request but answers the core one.
    """
    original_publish = fake_client._mqtt.publish

    def publish_and_reply(topic: str, payload: str) -> None:
        original_publish(topic, payload)
        requested = json.loads(payload)["params"]["property"]
        if not reply_to_station and "charge_station_type" in requested:
            return
        reply = json.dumps({"code": code, "data": data or {}}).encode()
        fake_client._mqtt.on_message(_REPLY_TOPIC, reply)

    fake_client._mqtt.publish = publish_and_reply


def _requested_properties(fake_client: FakeKarcherClient) -> list[list[str]]:
    """Property lists from every prop.get the adapter published, in order."""
    return [
        json.loads(payload)["params"]["property"]
        for topic, payload in fake_client._mqtt.published
        if topic.endswith("thing/service/property/get")
    ]


async def test_fetch_properties_returns_projected_dto(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """fetch_properties returns integration-owned DTO."""
    await adapter.subscribe(DEVICE, lambda _: None)
    _reply_on_publish(fake_client)

    props = await adapter.fetch_properties(DEVICE)
    assert isinstance(props, DeviceProperties)
    assert props.battery == 80  # FakeUpstreamProps default quantity=80


async def test_fetch_properties_requests_station_fields_separately(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Station fields ride in their own prop.get, and the core list has no duplicates."""
    await adapter.subscribe(DEVICE, lambda _: None)
    _reply_on_publish(fake_client)

    await adapter.fetch_properties(DEVICE)

    core, station = _requested_properties(fake_client)
    assert station == ["charge_station_type", "dust_action"]
    assert "charge_station_type" not in core
    assert len(core) == len(set(core))


async def test_fetch_properties_survives_silent_station_request(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """A robot that ignores the station fields still polls fine (issue #124)."""
    await adapter.subscribe(DEVICE, lambda _: None)
    _reply_on_publish(fake_client, reply_to_station=False)

    with patch.object(adapter_module, "_STATION_TIMEOUT", 0.05):
        props = await adapter.fetch_properties(DEVICE)

    assert props.battery == 80
    assert props.charge_station_type is None


async def test_fetch_properties_raises_on_rejected_reply(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """A non-zero reply code surfaces the code instead of a bogus timeout.

    karcher-home's own handler drops such a reply without setting its wait
    event, so before this the robot's refusal looked like silence (issue #124).
    """
    await adapter.subscribe(DEVICE, lambda _: None)
    _reply_on_publish(fake_client, code=1201)

    with pytest.raises(TransientError, match="1201"):
        await adapter.fetch_properties(DEVICE)


async def test_fetch_properties_reads_the_newest_reply(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """With two replies in flight the latest one decides, not the first."""
    await adapter.subscribe(DEVICE, lambda _: None)
    original_publish = fake_client._mqtt.publish

    def publish_and_reply(topic: str, payload: str) -> None:
        original_publish(topic, payload)
        older = json.dumps({"msgId": "1", "code": 1201, "data": {}}).encode()
        fake_client._mqtt.on_message(_REPLY_TOPIC, older)
        newer = json.dumps({"msgId": "2", "code": 0, "data": {}}).encode()
        fake_client._mqtt.on_message(_REPLY_TOPIC, newer)

    fake_client._mqtt.publish = publish_and_reply

    props = await adapter.fetch_properties(DEVICE)
    assert props.battery == 80


async def test_fetch_properties_survives_malformed_reply_shape(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """A get_reply whose `data` is not an object must not strand the waiter.

    The station harvest used to raise AttributeError here, killing the
    dispatcher before the reply was ever handed on (issue #124).
    """
    await adapter.subscribe(DEVICE, lambda _: None)
    original_publish = fake_client._mqtt.publish

    def publish_and_reply(topic: str, payload: str) -> None:
        original_publish(topic, payload)
        reply = json.dumps({"code": 0, "data": [{"charge_station_type": 1}]}).encode()
        fake_client._mqtt.on_message(_REPLY_TOPIC, reply)

    fake_client._mqtt.publish = publish_and_reply

    props = await adapter.fetch_properties(DEVICE)
    assert props.battery == 80


async def test_fetch_properties_harvests_station_fields_from_get_reply(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """charge_station_type/dust_action are harvested from the raw get_reply JSON.

    charge_station_type is not a field on karcher-home's DeviceProperties
    dataclass at all (v0.5.1) — FakeUpstreamProps mirrors that by omitting it
    too — so this proves the adapter's own side cache, not the library's
    .update(), is what makes station-attached work.
    """
    await adapter.subscribe(DEVICE, lambda _: None)
    _reply_on_publish(fake_client, data={"charge_station_type": 1, "dust_action": 2})

    props = await adapter.fetch_properties(DEVICE)
    assert props.charge_station_type == 1
    assert props.dust_action == 2


async def test_fetch_properties_no_mqtt_raises(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """BrokerDisconnect raised when not subscribed."""
    fake_client._mqtt = None  # type: ignore[assignment]
    with pytest.raises(BrokerDisconnect):
        await adapter.fetch_properties(DEVICE)


async def test_fetch_properties_times_out_without_reply(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """A silent robot still raises TransientError, so the coordinator keeps its cache."""
    await adapter.subscribe(DEVICE, lambda _: None)

    with (
        patch.object(adapter_module, "_FETCH_TIMEOUT", 0.05),
        pytest.raises(TransientError, match="not received"),
    ):
        await adapter.fetch_properties(DEVICE)


async def test_poll_rebinds_a_lost_dispatcher(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """A rebuilt MQTT client must not leave the poll waiting on a reply forever.

    The reply is signalled by the adapter's dispatcher, so a client that lost
    the binding has to get it back before the request goes out.
    """
    await adapter.subscribe(DEVICE, lambda _: None)
    fake_client._mqtt = FakeMqtt()  # rebuilt client: dispatcher binding gone
    _reply_on_publish(fake_client)

    props = await adapter.fetch_properties(DEVICE)
    assert props.battery == 80


@pytest.mark.parametrize("reply", [b"not json at all", b"[1, 2, 3]"])
async def test_fetch_properties_accepts_unparseable_reply(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient, reply: bytes
) -> None:
    """A reply we cannot read is treated as success, not as a rejection."""
    await adapter.subscribe(DEVICE, lambda _: None)
    original_publish = fake_client._mqtt.publish

    def publish_and_reply(topic: str, payload: str) -> None:
        original_publish(topic, payload)
        fake_client._mqtt.on_message(_REPLY_TOPIC, reply)

    fake_client._mqtt.publish = publish_and_reply

    props = await adapter.fetch_properties(DEVICE)
    assert props.battery == 80


async def test_poll_survives_a_failing_push_handler(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """A push that blows up mid-dispatch must not strand a poll waiting on a reply."""

    def _boom(sn: str, data: dict[str, Any]) -> None:
        raise TypeError("library update exploded")

    fake_client._update_device_properties = _boom  # type: ignore[method-assign]
    await adapter.subscribe(DEVICE, lambda _: None)

    push_topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/property/post"
    fake_client._mqtt.on_message(push_topic, json.dumps({"params": {"quantity": 42}}).encode())

    _reply_on_publish(fake_client)
    props = await adapter.fetch_properties(DEVICE)
    assert props.battery == 80


async def test_poll_survives_a_failing_library_handler(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """karcher-home raises KeyError on an unexpected reply shape; the poll goes on."""

    def _boom(topic: str, payload: bytes) -> None:
        raise KeyError("code")

    fake_client._mqtt.on_message = _boom
    await adapter.subscribe(DEVICE, lambda _: None)
    _reply_on_publish(fake_client)

    props = await adapter.fetch_properties(DEVICE)
    assert props.battery == 80


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


async def test_close_clears_client(adapter: KarcherAdapter, fake_client: FakeKarcherClient) -> None:
    """close() sets _client to None; subsequent operations should not be called."""
    assert adapter._client is not None
    await adapter.close()
    assert adapter._client is None


async def test_close_idempotent(adapter: KarcherAdapter) -> None:
    """Calling close() twice does not raise."""
    await adapter.close()
    await adapter.close()


async def test_close_swallows_exception(
    fake_hass: MagicMock, fake_client: FakeKarcherClient
) -> None:
    """close() swallows exceptions from client.close() and still clears _client."""

    async def exploding_close() -> None:
        raise RuntimeError("broker gone")

    fake_client.close = exploding_close  # type: ignore[method-assign]
    a = KarcherAdapter(hass=fake_hass, config=AdapterConfig(), karcher_factory=lambda: fake_client)
    await a.async_setup()
    await a.close()
    assert a._client is None


# ---------------------------------------------------------------------------
# get_endpoint_snapshot
# ---------------------------------------------------------------------------


async def test_get_endpoint_snapshot_returns_urls(
    fake_hass: MagicMock, fake_client: FakeKarcherClient
) -> None:
    """get_endpoint_snapshot projects _base_url and _mqtt_url from the client."""
    fake_client._base_url = "https://eu.api.example.com"
    fake_client._mqtt_url = "mqtts://eu.mqtt.example.com:8883"
    a = KarcherAdapter(hass=fake_hass, config=AdapterConfig(), karcher_factory=lambda: fake_client)
    await a.async_setup()
    snap = a.get_endpoint_snapshot()
    assert snap["rest_base_url"] == "https://eu.api.example.com"
    assert snap["mqtt_url"] == "mqtts://eu.mqtt.example.com:8883"


async def test_async_setup_seeds_endpoints_from_snapshot(
    fake_hass: MagicMock, fake_client: FakeKarcherClient
) -> None:
    """A complete snapshot seeds the client's endpoints instead of discovering them."""
    a = KarcherAdapter(
        hass=fake_hass, config=AdapterConfig(region="eu"), karcher_factory=lambda: fake_client
    )
    snapshot: dict[str, str | None] = {
        "rest_base_url": "https://stored.api.example.com",
        "mqtt_url": "mqtts://stored.mqtt.example.com:8883",
    }
    await a.async_setup(endpoint_snapshot=snapshot)
    # Seeded endpoints match the snapshot exactly (no discovery overwrote them).
    assert fake_client._base_url == "https://stored.api.example.com"
    assert fake_client._mqtt_url == "mqtts://stored.mqtt.example.com:8883"
    assert a.get_endpoint_snapshot() == snapshot
    # create() parity attributes are seeded for the resolved region.
    assert fake_client._country == "GB"


async def test_async_setup_incomplete_snapshot_does_not_seed(
    fake_hass: MagicMock, fake_client: FakeKarcherClient
) -> None:
    """A snapshot missing mqtt_url is treated as absent — endpoints are not seeded."""
    fake_client._base_url = "https://discovered.example.com"
    fake_client._mqtt_url = "mqtts://discovered.example.com:8883"
    a = KarcherAdapter(
        hass=fake_hass, config=AdapterConfig(region="eu"), karcher_factory=lambda: fake_client
    )
    await a.async_setup(
        endpoint_snapshot={"rest_base_url": "https://stored.example.com", "mqtt_url": None}
    )
    # Untouched: the factory-provided (discovered) endpoints remain.
    assert fake_client._base_url == "https://discovered.example.com"
    assert fake_client._mqtt_url == "mqtts://discovered.example.com:8883"


# ---------------------------------------------------------------------------
# _on_message — empty params branch
# ---------------------------------------------------------------------------


async def test_push_ignores_empty_params(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """property/post with empty params dict does not invoke the callback."""
    received: list[Any] = []
    await adapter.subscribe(DEVICE, received.append)

    payload = json.dumps({"params": {}}).encode()
    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/property/post"
    fake_client._mqtt.on_message(topic, payload)
    await asyncio.sleep(0)
    assert received == []


async def test_push_skips_callback_when_props_not_in_cache(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Callback is not invoked when _project_properties returns None (SN absent from cache)."""
    received: list[Any] = []
    await adapter.subscribe(DEVICE, received.append)

    # Remove the device from the internal props cache so _project_properties returns None.
    fake_client._device_props.pop(DEVICE.sn, None)

    payload = json.dumps({"params": {"work_mode": 1}}).encode()
    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/property/post"
    fake_client._mqtt.on_message(topic, payload)
    await asyncio.sleep(0)
    assert received == []


# ---------------------------------------------------------------------------
# _patch_download / _fixed_download
# ---------------------------------------------------------------------------


@patch("custom_components.karcher_home_robots.adapter._guard_download_url", new=AsyncMock())
async def test_patch_download_success(fake_hass: MagicMock) -> None:
    """_fixed_download returns bytes on HTTP 200."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.content.read = AsyncMock(return_value=b"map-data")
    mock_resp.close = MagicMock()

    mock_http = MagicMock()
    mock_http.get = AsyncMock(return_value=mock_resp)

    mock_client = MagicMock()
    mock_client._http = mock_http

    _patch_download(mock_client)
    result = await mock_client._download("https://example.com/map")
    assert result == b"map-data"


@patch("custom_components.karcher_home_robots.adapter._guard_download_url", new=AsyncMock())
async def test_patch_download_non_200_raises(fake_hass: MagicMock) -> None:
    """_fixed_download raises KarcherHomeException on non-200 status."""
    mock_resp = MagicMock()
    mock_resp.status = 403
    mock_resp.content.read = AsyncMock(return_value=b"")
    mock_resp.close = MagicMock()

    mock_http = MagicMock()
    mock_http.get = AsyncMock(return_value=mock_resp)

    mock_client = MagicMock()
    mock_client._http = mock_http

    _patch_download(mock_client)
    with pytest.raises(KarcherHomeException):
        await mock_client._download("https://example.com/map")


# ---------------------------------------------------------------------------
# _guard_download_url — SSRF guard on the cloud-supplied map download URL
# ---------------------------------------------------------------------------


def _addrinfo(ip: str) -> list:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


async def test_guard_download_url_rejects_non_https() -> None:
    """A non-https scheme is refused before any resolution."""
    with pytest.raises(NetworkError):
        await _guard_download_url("http://cdn.example.com/map")


async def test_guard_download_url_rejects_missing_host() -> None:
    with pytest.raises(NetworkError):
        await _guard_download_url("https:///map")


async def test_guard_download_url_allows_public_address() -> None:
    """A public-resolving host passes the guard."""
    loop = asyncio.get_running_loop()
    with patch.object(loop, "getaddrinfo", AsyncMock(return_value=_addrinfo("93.184.216.34"))):
        await _guard_download_url("https://cdn.example.com/map")


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.0.0.5", "192.168.1.10", "169.254.1.1", "172.16.0.1"],
)
async def test_guard_download_url_rejects_internal_address(ip: str) -> None:
    """A host resolving to a private/loopback/link-local address is refused (SSRF guard)."""
    loop = asyncio.get_running_loop()
    with (
        patch.object(loop, "getaddrinfo", AsyncMock(return_value=_addrinfo(ip))),
        pytest.raises(NetworkError),
    ):
        await _guard_download_url("https://cdn.example.com/map")


async def test_guard_download_url_rejects_unresolvable_host() -> None:
    loop = asyncio.get_running_loop()
    with (
        patch.object(loop, "getaddrinfo", AsyncMock(side_effect=OSError("nope"))),
        pytest.raises(NetworkError),
    ):
        await _guard_download_url("https://cdn.example.com/map")


async def test_guard_download_url_skips_unparseable_address() -> None:
    """A malformed resolved address (e.g. a scoped IPv6 literal) is skipped, not fatal;
    a later valid public address in the same getaddrinfo result still passes the guard."""
    loop = asyncio.get_running_loop()
    infos = _addrinfo("not-an-ip") + _addrinfo("93.184.216.34")
    with patch.object(loop, "getaddrinfo", AsyncMock(return_value=infos)):
        await _guard_download_url("https://cdn.example.com/map")


# ---------------------------------------------------------------------------
# _translate_exception — KarcherHomeAccessDenied branch
# ---------------------------------------------------------------------------


def test_translate_exception_access_denied() -> None:
    """KarcherHomeAccessDenied maps to AuthError."""
    result = _translate_exception(KarcherHomeAccessDenied("denied"))
    assert isinstance(result, AuthError)


# ---------------------------------------------------------------------------
# get_preference
# ---------------------------------------------------------------------------


def _make_preference_reply(rooms: list[Any], prefer_on: int) -> str:
    return json.dumps({"data": {"room": rooms, "prefer_on": prefer_on}})


async def test_get_preference_returns_rooms_and_prefer_on(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """get_preference returns dict with rooms list and prefer_on flag."""
    await adapter.subscribe(DEVICE, lambda _: None)

    rooms = [[1, "Living Room", 0, 0, 1, 2, 0, 0, 1, 0, 0, 0]]
    reply_payload = _make_preference_reply(rooms, prefer_on=1)

    original_publish = fake_client._mqtt.publish

    def publish_and_reply(topic: str, payload: str) -> None:
        original_publish(topic, payload)
        # Simulate robot reply by injecting into _reply_listeners.
        reply_topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/service_invoke_reply/get_preference"
        entry = adapter._reply_listeners.get(reply_topic)
        if entry:
            event, holder = entry
            holder.append(reply_payload)
            event.set()

    fake_client._mqtt.publish = publish_and_reply

    result = await adapter.get_preference(DEVICE, map_id=1)
    assert result["prefer_on"] == 1
    assert result["rooms"] == rooms


async def test_get_preference_prefer_on_zero(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """prefer_on=0 is parsed correctly (standard mode)."""
    await adapter.subscribe(DEVICE, lambda _: None)

    reply_payload = _make_preference_reply([], prefer_on=0)
    original_publish = fake_client._mqtt.publish

    def publish_and_reply(topic: str, payload: str) -> None:
        original_publish(topic, payload)
        reply_topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/service_invoke_reply/get_preference"
        entry = adapter._reply_listeners.get(reply_topic)
        if entry:
            event, holder = entry
            holder.append(reply_payload)
            event.set()

    fake_client._mqtt.publish = publish_and_reply

    result = await adapter.get_preference(DEVICE, map_id=1)
    assert result["prefer_on"] == 0
    assert result["rooms"] == []


async def test_get_preference_timeout_raises_transient(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Timeout raises TransientError so the coordinator keeps its cached prefs."""
    await adapter.subscribe(DEVICE, lambda _: None)
    # Don't signal the reply event — let it time out immediately.
    from custom_components.karcher_home_robots.adapter import _get_preference_sync
    from custom_components.karcher_home_robots.exceptions import TransientError

    with pytest.raises(TransientError):
        _get_preference_sync(
            fake_client,
            product_id=_RCV5_PRODUCT_ID,
            sn="SN001",
            map_id=1,
            reply_topic="no/such/topic",
            reply_listeners={},
            timeout=0.01,
        )


# ---------------------------------------------------------------------------
# set_preference_type
# ---------------------------------------------------------------------------


async def test_set_preference_type_publishes_correct_payload(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """set_preference_type publishes prefer_type to the correct topic."""
    await adapter.subscribe(DEVICE, lambda _: None)
    await adapter.set_preference_type(DEVICE, prefer_type=1)

    assert len(fake_client._mqtt.published) == 1
    topic, raw_payload = fake_client._mqtt.published[0]
    assert topic == (f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/service_invoke/set_preference_type")
    payload = json.loads(raw_payload)
    assert payload["method"] == "service.set_preference_type"
    assert payload["params"]["prefer_type"] == 1


async def test_set_preference_type_standard(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """prefer_type=0 (standard) is sent correctly."""
    await adapter.subscribe(DEVICE, lambda _: None)
    await adapter.set_preference_type(DEVICE, prefer_type=0)

    _, raw_payload = fake_client._mqtt.published[0]
    payload = json.loads(raw_payload)
    assert payload["params"]["prefer_type"] == 0
