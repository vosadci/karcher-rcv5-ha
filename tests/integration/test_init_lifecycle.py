# SPDX-License-Identifier: MIT
"""Integration tests for entry setup and unload lifecycle.

Tests use a FakeAdapter injected via patch so no real network or MQTT
connections are made.

Covers: FR-A-1, FR-A-5, FR-OF-1, NFR-SC-1..3
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

from custom_components.karcher_home_robots._types import DeviceProperties
from custom_components.karcher_home_robots.adapter import Device, Room
from custom_components.karcher_home_robots.const import DOMAIN
from custom_components.karcher_home_robots.coordinator import KarcherCoordinator
from custom_components.karcher_home_robots.exceptions import AuthError, TransientError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import PROPS_IDLE, TEST_DEVICE, TEST_ROOMS

# ---------------------------------------------------------------------------
# Entry data
# ---------------------------------------------------------------------------

_ENTRY_DATA = {
    "region": "eu",
    "email": "test@example.com",
    "password": "secret",
    "device_id": TEST_DEVICE.device_id,
    "sn": TEST_DEVICE.sn,
    "product_id": TEST_DEVICE.product_id,
    "nickname": TEST_DEVICE.nickname,
}


# ---------------------------------------------------------------------------
# FakeAdapter — injected into __init__.py via patch
# ---------------------------------------------------------------------------


class FakeAdapter:
    """Stand-in adapter used by integration tests.

    All methods are async and return canned values without touching the
    network or the real karcher-home library.
    """

    def __init__(
        self,
        props: DeviceProperties = PROPS_IDLE,
        devices: list[Device] | None = None,
        rooms: list[Room] | None = None,
        authenticate_raises: Exception | None = None,
        fetch_raises: Exception | None = None,
    ) -> None:
        self._props = props
        self._devices = devices if devices is not None else [TEST_DEVICE]
        self._rooms = rooms if rooms is not None else TEST_ROOMS
        self._authenticate_raises = authenticate_raises
        self._fetch_raises = fetch_raises
        self.closed = False
        self.subscribed = False
        self._push_callback: Callable[[DeviceProperties], None] | None = None
        self.commands_sent: list[tuple[str, dict[str, Any]]] = []
        self.properties_set: list[dict[str, Any]] = []

    async def async_setup(self) -> None:
        pass

    def get_endpoint_snapshot(self) -> dict[str, str | None]:
        return {"rest_base_url": "https://fake.example.com", "mqtt_url": None}

    async def authenticate(self, email: str, password: str) -> None:
        if self._authenticate_raises is not None:
            raise self._authenticate_raises

    async def get_devices(self) -> list[Device]:
        return self._devices

    async def get_rooms(self, device: Device) -> list[Room]:
        return self._rooms

    async def subscribe(
        self,
        device: Device,
        on_push: Callable[[DeviceProperties], None],
    ) -> None:
        self.subscribed = True
        self._push_callback = on_push

    async def unsubscribe(self, device: Device) -> None:
        self.subscribed = False

    async def fetch_properties(self, device: Device) -> DeviceProperties:
        if self._fetch_raises is not None:
            raise self._fetch_raises
        return self._props

    async def send_command(
        self,
        device: Device,
        service: str,
        params: dict[str, Any],
    ) -> None:
        self.commands_sent.append((service, dict(params)))

    async def set_property(self, device: Device, params: dict[str, Any]) -> None:
        self.properties_set.append(dict(params))

    async def close(self) -> None:
        self.closed = True

    def fire_push(self, props: DeviceProperties) -> None:
        """Simulate a push from the adapter (test helper)."""
        if self._push_callback is not None:
            self._push_callback(props)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_entry(**kwargs: Any) -> MockConfigEntry:
    data = {**_ENTRY_DATA, **kwargs}
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        unique_id=data["device_id"],
        version=2,
    )


def _patch_adapter(fake: FakeAdapter) -> Any:
    """Return a context manager that patches KarcherAdapter to return fake."""
    return patch(
        "custom_components.karcher_home_robots.KarcherAdapter",
        side_effect=lambda *a, **kw: fake,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_setup_entry_creates_coordinator(hass: HomeAssistant) -> None:
    """setup_entry stores a coordinator in entry.runtime_data.

    Covers: FR-A-1 (entry loadable), NFR-SC-1 (one coordinator per entry)
    """
    fake = FakeAdapter()
    entry = _make_entry()
    entry.add_to_hass(hass)

    with _patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data, KarcherCoordinator)


async def test_setup_loads_rooms(hass: HomeAssistant) -> None:
    """setup_entry populates coordinator.rooms from the adapter.

    Covers: FR-SL-1 (room list available after setup)
    """
    fake = FakeAdapter(rooms=TEST_ROOMS)
    entry = _make_entry()
    entry.add_to_hass(hass)

    with _patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator: KarcherCoordinator = entry.runtime_data
    assert len(coordinator.rooms) == 2
    assert coordinator.rooms[0].name == "Living Room"
    assert coordinator.rooms[1].name == "Bedroom"


async def test_setup_auth_failure_raises_config_entry_auth_failed(
    hass: HomeAssistant,
) -> None:
    """Auth failure during setup surfaces as ConfigEntryAuthFailed.

    Covers: FR-A-6 (auth failure surfaced), FR-OF-1
    """
    fake = FakeAdapter(authenticate_raises=AuthError("bad creds"))
    entry = _make_entry()
    entry.add_to_hass(hass)

    with _patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_unload_entry_shuts_down_coordinator(hass: HomeAssistant) -> None:
    """Unloading the entry calls coordinator.async_shutdown and adapter.close."""
    fake = FakeAdapter()
    entry = _make_entry()
    entry.add_to_hass(hass)

    with _patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        result = await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert fake.closed is True


async def test_two_entries_independent(hass: HomeAssistant) -> None:
    """Two config entries do not share state (NFR-SC-1..3)."""
    device_a = Device(
        device_id="dev-a",
        sn="SN-A",
        product_id="1540149850806333440",
        nickname="Robot A",
        mac="AA:BB:CC:DD:EE:FF",
        product_mode_code="CRL350",
    )
    device_b = Device(
        device_id="dev-b",
        sn="SN-B",
        product_id="1540149850806333440",
        nickname="Robot B",
        mac="AA:BB:CC:DD:EE:F0",
        product_mode_code="CRL350",
    )
    fake_a = FakeAdapter(devices=[device_a])
    fake_b = FakeAdapter(devices=[device_b])

    entry_a = MockConfigEntry(
        domain=DOMAIN,
        data={**_ENTRY_DATA, "device_id": device_a.device_id, "sn": device_a.sn},
        unique_id=device_a.device_id,
        version=2,
    )
    entry_b = MockConfigEntry(
        domain=DOMAIN,
        data={**_ENTRY_DATA, "device_id": device_b.device_id, "sn": device_b.sn},
        unique_id=device_b.device_id,
        version=2,
    )
    entry_a.add_to_hass(hass)
    entry_b.add_to_hass(hass)

    fakes = [fake_a, fake_b]
    call_idx: list[int] = [0]

    def _factory(*args: Any, **kwargs: Any) -> FakeAdapter:
        result = fakes[call_idx[0] % len(fakes)]
        call_idx[0] += 1
        return result

    with patch("custom_components.karcher_home_robots.KarcherAdapter", side_effect=_factory):
        # Setting up entry_a causes HA to schedule all entries in the domain;
        # block_till_done processes both.
        await hass.config_entries.async_setup(entry_a.entry_id)
        await hass.async_block_till_done()

    assert entry_a.state is ConfigEntryState.LOADED
    assert entry_b.state is ConfigEntryState.LOADED
    coord_a: KarcherCoordinator = entry_a.runtime_data
    coord_b: KarcherCoordinator = entry_b.runtime_data
    assert coord_a is not coord_b


async def test_device_not_on_account_fails_setup(hass: HomeAssistant) -> None:
    """If the stored device_id is not in the account device list, setup fails."""
    other_device = Device(
        device_id="other-device",
        sn="SN999",
        product_id="1540149850806333440",
        nickname="Other",
        mac="00:00:00:00:00:00",
        product_mode_code="CRL350",
    )
    fake = FakeAdapter(devices=[other_device])
    entry = _make_entry()  # device_id = TEST_DEVICE.device_id, not "other-device"
    entry.add_to_hass(hass)

    with _patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_fetch_transient_error_marks_unavailable(hass: HomeAssistant) -> None:
    """A TransientError from fetch_properties does not crash setup but marks unavailable.

    Covers: FR-OF-1 (cloud unreachable → entities unavailable)
    """
    fake = FakeAdapter(fetch_raises=TransientError("timeout"))
    entry = _make_entry()
    entry.add_to_hass(hass)

    with _patch_adapter(fake):
        # async_config_entry_first_refresh raises UpdateFailed on TransientError
        # which puts the entry in SETUP_RETRY rather than LOADED
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state in (ConfigEntryState.SETUP_RETRY, ConfigEntryState.SETUP_ERROR)
