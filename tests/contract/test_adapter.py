# SPDX-License-Identifier: MIT
"""Contract tests for KarcherAdapter.

Tests the adapter's observable behaviour from the coordinator's perspective
using a FakeKarcherClient injected via the karcher_factory parameter.
No real MQTT or HTTP connections are made.

Covers: FR-A-8, FR-A-8b, FR-UP-1, FR-UP-2, ADR-0001, ADR-0003
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any
from unittest.mock import MagicMock

import pytest
from custom_components.karcher_home_robots._types import DeviceProperties
from custom_components.karcher_home_robots.adapter import (
    AdapterConfig,
    Device,
    KarcherAdapter,
    Room,
)
from custom_components.karcher_home_robots.exceptions import (
    AuthError,
    BrokerDisconnect,
    ClientError,
    InvalidCredentials,
    NetworkError,
    TokenRejected,
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


_RCV5_PRODUCT_ID = "1540149850806333440"  # Product.RCV5.value


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
        self.net_stauts: Any = None


class FakeKarcherClient:
    """Injectable fake that replaces the real KarcherHome client."""

    def __init__(self) -> None:
        self._mqtt: FakeMqtt = FakeMqtt()
        self._device_props: dict[str, FakeUpstreamProps] = {}
        self._wait_events: dict[str, threading.Event] = {}
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

DEVICE = Device(device_id="dev-1", sn="SN001", product_id=_RCV5_PRODUCT_ID, nickname="Robot", mac="AA:BB:CC:DD:EE:FF", product_mode_code="CRL350")


# ---------------------------------------------------------------------------
# async_setup
# ---------------------------------------------------------------------------


async def test_async_setup_stores_client(
    fake_hass: MagicMock, fake_client: FakeKarcherClient
) -> None:
    """Covers: ADR-0001 -- factory injects the client without real network."""
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
    """Covers: FR-A-8 -- adapter passes credentials to the upstream client."""
    await adapter.authenticate("user@example.com", "secret")
    assert fake_client.login_calls == [("user@example.com", "secret")]


async def test_authenticate_stores_credentials(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Covers: FR-A-8 -- credentials are retained for silent reauth."""
    await adapter.authenticate("user@example.com", "secret")
    assert adapter._email == "user@example.com"
    assert adapter._password == "secret"  # noqa: S105


async def test_authenticate_invalid_credentials_raises(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Covers: FR-A-8b -- KarcherHomeInvalidAuth maps to InvalidCredentials."""
    fake_client.login_exc = KarcherHomeInvalidAuth()
    with pytest.raises(InvalidCredentials):
        await adapter.authenticate("bad@example.com", "wrong")


async def test_authenticate_token_expired_raises(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Covers: FR-A-8b -- KarcherHomeTokenExpired maps to TokenRejected."""
    fake_client.login_exc = KarcherHomeTokenExpired()
    with pytest.raises(TokenRejected):
        await adapter.authenticate("user@example.com", "pass")


async def test_authenticate_access_denied_raises(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Covers: FR-A-8b -- KarcherHomeAccessDenied maps to AuthError."""
    fake_client.login_exc = KarcherHomeAccessDenied("Forbidden")
    with pytest.raises(AuthError):
        await adapter.authenticate("user@example.com", "pass")


async def test_authenticate_generic_exception_raises(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Covers: ADR-0003 -- any KarcherHomeException maps to ClientError."""
    fake_client.login_exc = KarcherHomeException(500, "internal")
    with pytest.raises(ClientError):
        await adapter.authenticate("user@example.com", "pass")


# ---------------------------------------------------------------------------
# get_devices
# ---------------------------------------------------------------------------


async def test_get_devices_returns_device_list(adapter: KarcherAdapter) -> None:
    """Covers: ADR-0001 -- upstream Device is projected to integration-owned DTO."""
    devices = await adapter.get_devices()
    assert len(devices) == 1
    dev = devices[0]
    assert dev.sn == "SN001"
    assert dev.device_id == "dev-1"
    assert dev.product_id == _RCV5_PRODUCT_ID
    assert dev.nickname == "Robot"


async def test_get_devices_exception_raises(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Covers: ADR-0003 -- upstream exception becomes NetworkError."""
    fake_client.get_devices_exc = KarcherHomeException(503, "unavailable")
    with pytest.raises(NetworkError):
        await adapter.get_devices()


# ---------------------------------------------------------------------------
# get_rooms
# ---------------------------------------------------------------------------


async def test_get_rooms_empty_when_no_map(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Covers: FR-SL-2 -- returns empty list when map data unavailable."""
    fake_client.map_data_exc = Exception("no map")
    rooms = await adapter.get_rooms(DEVICE)
    assert rooms == []


async def test_get_rooms_parses_room_data(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Covers: FR-SL-1 -- room IDs and names projected from map protobuf."""
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


# ---------------------------------------------------------------------------
# subscribe / push path
# ---------------------------------------------------------------------------


async def test_subscribe_calls_subscribe_device(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Covers: FR-UP-1 -- adapter calls the upstream subscribe_device."""
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


async def test_push_callback_invoked_on_property_post(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Covers: FR-UP-1 -- property/post payload is parsed and callback fired."""
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

    # Call from a background thread to simulate paho delivery.
    thread = threading.Thread(target=fire_callback)
    thread.start()
    thread.join()

    # Give call_soon_threadsafe a chance to run.
    await asyncio.sleep(0)

    assert len(received) == 1
    assert received[0].battery == 75
    assert received[0].work_mode == 1


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
    """Covers: work-around bug -- AttributeError from net_stauts does not crash the MQTT thread."""
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
    """Covers: ADR-0001 -- unsubscribe delegates to upstream."""
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
    """Covers: FR-V-1..FR-V-7 -- send_command publishes to service_invoke topic."""
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
    """Covers: FR-V-8 (fan speed), FR-SL-4 (cleaning mode) -- prop.set envelope."""
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


async def test_fetch_properties_returns_projected_dto(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Covers: FR-UP-2 -- fetch_properties returns integration-owned DTO."""
    await adapter.subscribe(DEVICE, lambda _: None)

    # Make the fake MQTT immediately resolve any registered wait events when
    # publish is called, simulating a fast prop.get reply.
    original_publish = fake_client._mqtt.publish

    def publish_and_resolve(topic: str, payload: str) -> None:
        original_publish(topic, payload)
        for event in list(fake_client._wait_events.values()):
            event.set()

    fake_client._mqtt.publish = publish_and_resolve

    props = await adapter.fetch_properties(DEVICE)
    assert isinstance(props, DeviceProperties)
    assert props.battery == 80  # FakeUpstreamProps default quantity=80


async def test_fetch_properties_no_mqtt_raises(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Covers: FR-UP-2 -- BrokerDisconnect raised when not subscribed."""
    fake_client._mqtt = None  # type: ignore[assignment]
    with pytest.raises(BrokerDisconnect):
        await adapter.fetch_properties(DEVICE)


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
