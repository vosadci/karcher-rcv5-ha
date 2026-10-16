# SPDX-License-Identifier: MIT
"""Integration tests for consumable reset button dispatch."""

from __future__ import annotations

import pytest
from custom_components.karcher_home_robots.button import KarcherEmptyStationButton
from custom_components.karcher_home_robots.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import (
    ENTRY_DATA,
    PROPS_DOCKED,
    PROPS_IDLE,
    TEST_DEVICE,
    FakeAdapter,
    make_props,
    patch_adapter,
)


async def _setup(hass: HomeAssistant, fake: FakeAdapter) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id=TEST_DEVICE.device_id,
        version=3,
    )
    entry.add_to_hass(hass)
    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


@pytest.mark.parametrize(
    "entity_id,expected_type",
    [
        ("button.test_robot_reset_main_brush", 1),
        ("button.test_robot_reset_side_brush", 2),
        ("button.test_robot_reset_filter", 3),
        ("button.test_robot_reset_mopping_pad", 4),
    ],
)
async def test_reset_button_sends_reset_consumable(
    hass: HomeAssistant, entity_id: str, expected_type: int
) -> None:
    fake = FakeAdapter(props=PROPS_DOCKED)
    await _setup(hass, fake)

    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)

    assert fake.commands_sent == [("reset_consumable", {"consumable": expected_type})]


_DRIVE_OBJECT_IDS = {
    "drive_forward": "test_robot_drive_forward",
    "drive_left": "test_robot_turn_left",
    "drive_right": "test_robot_turn_right",
    "drive_backward": "test_robot_drive_backward",
}
_DRIVE_BUTTONS = tuple(f"button.{o}" for o in _DRIVE_OBJECT_IDS.values())


async def _setup_with_drive_enabled(hass: HomeAssistant, fake: FakeAdapter) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id=TEST_DEVICE.device_id,
        version=3,
    )
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    for key, object_id in _DRIVE_OBJECT_IDS.items():
        ent_reg.async_get_or_create(
            "button",
            DOMAIN,
            f"{TEST_DEVICE.device_id}_{key}",
            config_entry=entry,
            suggested_object_id=object_id,
        )
    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


@pytest.mark.parametrize(
    "entity_id,expected_direction",
    [
        # Values device-verified on an RCV5 (const.py): 1 fwd, 2 left, 3 right, 4 back.
        ("button.test_robot_drive_forward", 1),
        ("button.test_robot_turn_left", 2),
        ("button.test_robot_turn_right", 3),
        ("button.test_robot_drive_backward", 4),
    ],
)
async def test_drive_button_sends_set_direction(
    hass: HomeAssistant, entity_id: str, expected_direction: int
) -> None:
    """Each manual-drive button publishes one set_direction nudge."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup_with_drive_enabled(hass, fake)
    assert entry.state is ConfigEntryState.LOADED

    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)

    assert fake.commands_sent == [("set_direction", {"direction": expected_direction})]


async def test_drive_buttons_are_disabled_by_default(hass: HomeAssistant) -> None:
    await _setup(hass, FakeAdapter(props=PROPS_IDLE))

    ent_reg = er.async_get(hass)
    for entity_id in _DRIVE_BUTTONS:
        entry = ent_reg.async_get(entity_id)
        assert entry is not None
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_empty_station_button_sends_start_station_act(hass: HomeAssistant) -> None:
    """Pressing the empty-station button dispatches start_station_act with ctrl_value=1."""
    props = make_props(work_mode=0, status=4, charge_state=1, fault=0, charge_station_type=1)
    fake = FakeAdapter(props=props)
    await _setup(hass, fake)

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.test_robot_empty_station"},
        blocking=True,
    )

    assert fake.commands_sent == [("start_station_act", {"station_act": 3, "ctrl_value": 1})]


async def test_empty_station_button_unavailable_without_station(hass: HomeAssistant) -> None:
    """Button is unavailable when docked but charge_station_type == 0 (plain dock)."""
    props = make_props(work_mode=0, status=4, charge_state=1, fault=0, charge_station_type=0)
    fake = FakeAdapter(props=props)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherEmptyStationButton(coordinator)
    assert entity.available is False


async def test_empty_station_button_unavailable_when_not_docked(hass: HomeAssistant) -> None:
    """Button is unavailable when not docked, even with a station attached."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherEmptyStationButton(coordinator)
    assert entity.available is False


async def test_empty_station_button_unavailable_when_no_data(hass: HomeAssistant) -> None:
    """KarcherEmptyStationButton.available is False when coordinator data is None."""
    fake = FakeAdapter(props=PROPS_DOCKED)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherEmptyStationButton(coordinator)
    coordinator.async_set_updated_data(None)  # type: ignore[arg-type]
    assert entity.available is False
