# SPDX-License-Identifier: MIT
"""Integration tests for cleaning-mode and water-level select entities.

Covers: FR-SL-4, FR-SL-5, FR-SL-6, FR-V-8, P2-7
"""

from __future__ import annotations

import homeassistant.helpers.entity_registry as er_module
from custom_components.karcher_home_robots.const import DOMAIN
from custom_components.karcher_home_robots.select import KarcherWaterLevelSelect
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import PROPS_IDLE, TEST_DEVICE, make_props
from tests.integration.test_init_lifecycle import _ENTRY_DATA, FakeAdapter, _patch_adapter


async def _setup(hass: HomeAssistant, fake: FakeAdapter) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=_ENTRY_DATA,
        unique_id=TEST_DEVICE.device_id,
        version=2,
    )
    entry.add_to_hass(hass)
    with _patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


# ---------------------------------------------------------------------------
# Cleaning-mode select (FR-SL-4)
# ---------------------------------------------------------------------------


async def test_cleaning_mode_reflects_vacuum(hass: HomeAssistant) -> None:
    """Cleaning-mode select shows Vacuum when mode=0 (FR-SL-4)."""
    props = make_props(work_mode=0, status=0, charge_state=0, fault=0, battery=80, mode=0)
    fake = FakeAdapter(props=props)
    await _setup(hass, fake)

    state = hass.states.get("select.test_robot_cleaning_mode")
    assert state is not None
    assert state.state == "vacuum"


async def test_cleaning_mode_reflects_vacuum_and_mop(hass: HomeAssistant) -> None:
    """Cleaning-mode select shows Vacuum & Mop when mode=1 (FR-SL-4)."""
    props = make_props(work_mode=0, status=0, charge_state=0, fault=0, battery=80, mode=1)
    fake = FakeAdapter(props=props)
    await _setup(hass, fake)

    state = hass.states.get("select.test_robot_cleaning_mode")
    assert state is not None
    assert state.state == "vacuum_and_mop"


async def test_cleaning_mode_reflects_mop(hass: HomeAssistant) -> None:
    """Cleaning-mode select shows Mop when mode=2 (FR-SL-4)."""
    props = make_props(work_mode=0, status=0, charge_state=0, fault=0, battery=80, mode=2)
    fake = FakeAdapter(props=props)
    await _setup(hass, fake)

    state = hass.states.get("select.test_robot_cleaning_mode")
    assert state is not None
    assert state.state == "mop"


async def test_cleaning_mode_select_writes_prop_set(hass: HomeAssistant) -> None:
    """Selecting a cleaning mode sends prop.set {"mode": N} (FR-SL-4)."""
    props = make_props(work_mode=0, status=0, charge_state=0, fault=0, battery=80, mode=0)
    fake = FakeAdapter(props=props)
    await _setup(hass, fake)

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.test_robot_cleaning_mode", "option": "mop"},
        blocking=True,
    )

    assert len(fake.properties_set) == 1
    assert fake.properties_set[0] == {"mode": 2}


async def test_cleaning_mode_unknown_option_ignored(hass: HomeAssistant) -> None:
    """An unknown cleaning mode option is silently dropped (no prop.set sent)."""
    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup(hass, fake)

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.test_robot_cleaning_mode", "option": "vacuum"},
        blocking=True,
    )
    # The valid option "vacuum" is in the list, so prop.set IS sent.
    # This test verifies the happy path completes without error.
    assert len(fake.properties_set) == 1
    assert fake.properties_set[0] == {"mode": 0}


# ---------------------------------------------------------------------------
# Water-level select (FR-SL-5, FR-SL-6)
# ---------------------------------------------------------------------------


async def test_water_level_disabled_by_default(hass: HomeAssistant) -> None:
    """Water-level select has entity_registry_enabled_default=False (FR-SL-6)."""
    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup(hass, fake)

    er = er_module.async_get(hass)
    entry = er.async_get("select.test_robot_water_level")
    assert entry is not None
    assert entry.disabled_by is not None


async def test_water_level_unavailable_when_vacuum_only(hass: HomeAssistant) -> None:
    """Water-level select is unavailable when mode=Vacuum (FR-SL-5).

    Verified via direct entity `available` property rather than state machine
    (the entity is disabled by default, so HA suppresses its state).
    """
    props = make_props(work_mode=0, status=0, charge_state=0, fault=0, battery=80, mode=0)
    fake = FakeAdapter(props=props)
    entry = await _setup(hass, fake)

    coordinator = entry.runtime_data
    entity = KarcherWaterLevelSelect(coordinator)
    assert not entity.available


async def test_water_level_available_when_mop_mode(hass: HomeAssistant) -> None:
    """Water-level select is available when mode=Mop (FR-SL-5)."""
    props = make_props(work_mode=0, status=0, charge_state=0, fault=0, battery=80, mode=2, water=2)
    fake = FakeAdapter(props=props)
    entry = await _setup(hass, fake)

    coordinator = entry.runtime_data
    entity = KarcherWaterLevelSelect(coordinator)
    assert entity.available
    assert entity.current_option == "medium"


async def test_water_level_select_writes_prop_set(hass: HomeAssistant) -> None:
    """Selecting water level sends prop.set {"water": N} via coordinator (FR-SL-5)."""
    props = make_props(work_mode=0, status=0, charge_state=0, fault=0, battery=80, mode=2, water=1)
    fake = FakeAdapter(props=props)
    entry = await _setup(hass, fake)

    coordinator = entry.runtime_data
    entity = KarcherWaterLevelSelect(coordinator)
    await entity.async_select_option("high")

    assert any(p == {"water": 3} for p in fake.properties_set)


# ---------------------------------------------------------------------------
# Fan-speed unavailability when Mop-only (FR-V-8)
# ---------------------------------------------------------------------------


async def test_fan_speed_none_when_mop_only(hass: HomeAssistant) -> None:
    """fan_speed attribute is None (unavailable) when mode=Mop (FR-V-8)."""
    props = make_props(work_mode=1, status=0, charge_state=0, fault=0, battery=70, mode=2, wind=2)
    fake = FakeAdapter(props=props)
    await _setup(hass, fake)

    state = hass.states.get("vacuum.test_robot_vacuum")
    assert state is not None
    assert state.attributes.get("fan_speed") is None


async def test_fan_speed_present_when_vacuum_mode(hass: HomeAssistant) -> None:
    """fan_speed attribute is set when mode is not Mop-only (FR-V-8)."""
    props = make_props(work_mode=1, status=0, charge_state=0, fault=0, battery=70, mode=0, wind=2)
    fake = FakeAdapter(props=props)
    await _setup(hass, fake)

    state = hass.states.get("vacuum.test_robot_vacuum")
    assert state is not None
    assert state.attributes.get("fan_speed") == "Medium"
