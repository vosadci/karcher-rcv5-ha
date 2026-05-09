# SPDX-License-Identifier: MIT
"""Integration tests for entry setup and unload lifecycle.

Tests use a FakeAdapter injected via patch so no real network or MQTT
connections are made.

"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from custom_components.karcher_home_robots.adapter import Device
from custom_components.karcher_home_robots.const import DOMAIN
from custom_components.karcher_home_robots.coordinator import KarcherCoordinator
from custom_components.karcher_home_robots.exceptions import (
    AuthError,
    PermanentError,
    TransientError,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import (
    ENTRY_DATA,
    FakeAdapter,
    TEST_DEVICE,
    TEST_ROOMS,
    make_entry,
    patch_adapter,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_setup_entry_creates_coordinator(hass: HomeAssistant) -> None:
    """setup_entry stores a coordinator in entry.runtime_data."""
    fake = FakeAdapter()
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data, KarcherCoordinator)


async def test_setup_loads_rooms(hass: HomeAssistant) -> None:
    """setup_entry populates coordinator.rooms from the adapter."""
    fake = FakeAdapter(rooms=TEST_ROOMS)
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator: KarcherCoordinator = entry.runtime_data
    assert len(coordinator.rooms) == 2
    assert coordinator.rooms[0].name == "Living Room"
    assert coordinator.rooms[1].name == "Bedroom"


async def test_setup_auth_failure_raises_config_entry_auth_failed(
    hass: HomeAssistant,
) -> None:
    """Auth failure during setup surfaces as ConfigEntryAuthFailed."""
    fake = FakeAdapter(authenticate_raises=AuthError("bad creds"))
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_unload_entry_shuts_down_coordinator(hass: HomeAssistant) -> None:
    """Unloading the entry calls coordinator.async_shutdown and adapter.close."""
    fake = FakeAdapter()
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch_adapter(fake):
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
        data={**ENTRY_DATA, "device_id": device_a.device_id},
        unique_id=device_a.device_id,
        version=3,
    )
    entry_b = MockConfigEntry(
        domain=DOMAIN,
        data={**ENTRY_DATA, "device_id": device_b.device_id},
        unique_id=device_b.device_id,
        version=3,
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
    entry = make_entry()  # device_id = TEST_DEVICE.device_id, not "other-device"
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_fetch_transient_error_marks_unavailable(hass: HomeAssistant) -> None:
    """A TransientError from fetch_properties does not crash setup but marks unavailable."""
    fake = FakeAdapter(fetch_raises=TransientError("timeout"))
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        # async_config_entry_first_refresh raises UpdateFailed on TransientError
        # which puts the entry in SETUP_RETRY rather than LOADED
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state in (ConfigEntryState.SETUP_RETRY, ConfigEntryState.SETUP_ERROR)


async def test_setup_permanent_error_raises_config_entry_error(hass: HomeAssistant) -> None:
    """PermanentError during authenticate surfaces as ConfigEntryError (→ SETUP_ERROR)."""
    fake = FakeAdapter(authenticate_raises=PermanentError("device banned"))
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_transient_error_during_auth_raises_config_entry_not_ready(
    hass: HomeAssistant,
) -> None:
    """TransientError during authenticate surfaces as ConfigEntryNotReady (→ SETUP_RETRY)."""
    fake = FakeAdapter(authenticate_raises=TransientError("timeout"))
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state in (ConfigEntryState.SETUP_RETRY, ConfigEntryState.SETUP_ERROR)


async def test_setup_writes_endpoint_snapshot_to_entry(hass: HomeAssistant) -> None:
    """async_setup_entry persists the endpoint snapshot in entry.data."""
    fake = FakeAdapter()
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert "region_endpoint_snapshot" in entry.data
    assert entry.data["region_endpoint_snapshot"]["rest_base_url"] == "https://fake.example.com"


async def test_setup_skips_snapshot_update_when_already_current(hass: HomeAssistant) -> None:
    """No entry update when the stored snapshot already matches the fresh one."""
    snapshot = {"rest_base_url": "https://fake.example.com", "mqtt_url": None}
    fake = FakeAdapter()
    entry = make_entry(region_endpoint_snapshot=snapshot)
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    # Snapshot was pre-populated with the same value the adapter returns,
    # so async_update_entry should not have changed it.
    assert entry.data["region_endpoint_snapshot"] == snapshot
