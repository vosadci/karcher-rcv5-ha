"""Tests for the KarcherVacuum entity."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.vacuum import VacuumActivity

from custom_components.karcher_home_robots.const import (
    CMD_GO_HOME,
    CMD_PAUSE,
    CMD_START,
    CMD_STOP,
    FAN_SPEED_LIST,
)


@pytest.fixture
async def vacuum_setup(setup_integration, hass):
    """Return the vacuum entity state after integration setup."""
    await hass.async_block_till_done()
    return hass.states.get("vacuum.test_vacuum")


async def test_vacuum_state_docked(vacuum_setup):
    """Default mock props (work_mode=0, status=4) → docked."""
    assert vacuum_setup is not None
    assert vacuum_setup.state == VacuumActivity.DOCKED


async def test_vacuum_state_cleaning(hass, setup_integration, mock_props):
    """work_mode in WORK_MODE_CLEANING → cleaning state."""
    from custom_components.karcher_home_robots.const import WORK_MODE_CLEANING
    coordinator = setup_integration
    cleaning_mode = next(iter(WORK_MODE_CLEANING))
    mock_props.work_mode = cleaning_mode
    mock_props.status = 0
    mock_props.charge_state = 0
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    state = hass.states.get("vacuum.test_vacuum")
    assert state.state == VacuumActivity.CLEANING


async def test_vacuum_fan_speed(vacuum_setup):
    """wind=1 → Standard fan speed label."""
    assert vacuum_setup.attributes.get("fan_speed") == "Standard"


async def test_vacuum_fan_speed_list(vacuum_setup):
    """All four fan speed options are exposed."""
    assert vacuum_setup.attributes.get("fan_speed_list") == FAN_SPEED_LIST


async def test_vacuum_rooms_in_roborock_format(vacuum_setup):
    """Rooms exposed as {"id": "name"} string-keyed dict (Roborock format for HAMH)."""
    rooms = vacuum_setup.attributes.get("rooms")
    assert rooms == {"1": "Living Room", "2": "Kitchen"}


async def test_async_start_no_room(hass, setup_integration, mock_api):
    """Start with no room selected sends room_ids=[]."""
    await hass.services.async_call(
        "vacuum", "start", {"entity_id": "vacuum.test_vacuum"}, blocking=True
    )
    mock_api.async_send_command.assert_called_once_with(
        mock_api.async_send_command.call_args[0][0],
        CMD_START["service"],
        {"room_ids": [], "ctrl_value": 1, "clean_type": 0},
    )


async def test_async_start_with_room(hass, setup_integration, mock_api):
    """Start with a selected room sends room_ids=[selected_id]."""
    coordinator = setup_integration
    coordinator.selected_room_id = 1

    await hass.services.async_call(
        "vacuum", "start", {"entity_id": "vacuum.test_vacuum"}, blocking=True
    )
    call_args = mock_api.async_send_command.call_args
    assert call_args[0][2]["room_ids"] == [1]


async def test_async_pause(hass, setup_integration, mock_api):
    """Pause sends set_room_clean with ctrl_value=2."""
    await hass.services.async_call(
        "vacuum", "pause", {"entity_id": "vacuum.test_vacuum"}, blocking=True
    )
    call_args = mock_api.async_send_command.call_args
    assert call_args[0][1] == CMD_PAUSE["service"]
    assert call_args[0][2]["ctrl_value"] == 2


async def test_async_stop(hass, setup_integration, mock_api):
    """Stop sends stop_recharge."""
    await hass.services.async_call(
        "vacuum", "stop", {"entity_id": "vacuum.test_vacuum"}, blocking=True
    )
    call_args = mock_api.async_send_command.call_args
    assert call_args[0][1] == CMD_STOP["service"]


async def test_async_return_to_base(hass, setup_integration, mock_api):
    """Return to base sends start_recharge."""
    await hass.services.async_call(
        "vacuum", "return_to_base", {"entity_id": "vacuum.test_vacuum"}, blocking=True
    )
    call_args = mock_api.async_send_command.call_args
    assert call_args[0][1] == CMD_GO_HOME["service"]


async def test_async_set_fan_speed_silent(hass, setup_integration, mock_api):
    """Setting Silent fan speed sends wind=0."""
    await hass.services.async_call(
        "vacuum", "set_fan_speed",
        {"entity_id": "vacuum.test_vacuum", "fan_speed": "Silent"},
        blocking=True,
    )
    mock_api.async_set_property.assert_called_once_with(
        mock_api.async_set_property.call_args[0][0], {"wind": 0}
    )


async def test_async_set_fan_speed_turbo(hass, setup_integration, mock_api):
    """Setting Turbo fan speed sends wind=3."""
    await hass.services.async_call(
        "vacuum", "set_fan_speed",
        {"entity_id": "vacuum.test_vacuum", "fan_speed": "Turbo"},
        blocking=True,
    )
    call_args = mock_api.async_set_property.call_args
    assert call_args[0][1] == {"wind": 3}


async def test_async_set_fan_speed_unknown(hass, setup_integration, mock_api):
    """Unknown fan speed logs a warning and sends no command."""
    await hass.services.async_call(
        "vacuum", "set_fan_speed",
        {"entity_id": "vacuum.test_vacuum", "fan_speed": "Warp Speed"},
        blocking=True,
    )
    mock_api.async_set_property.assert_not_called()


async def test_fan_speed_list_empty_in_mop_mode(hass, setup_integration, mock_props):
    """Fan speed list is empty when cleaning mode is Mop-only."""
    coordinator = setup_integration
    mock_props.mode = 2
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    state = hass.states.get("vacuum.test_vacuum")
    assert state.attributes.get("fan_speed_list") == []


async def test_fan_speed_none_in_mop_mode(hass, setup_integration, mock_props):
    """Fan speed is None when cleaning mode is Mop-only."""
    coordinator = setup_integration
    mock_props.mode = 2
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    state = hass.states.get("vacuum.test_vacuum")
    assert state.attributes.get("fan_speed") is None


async def test_fan_speed_set_ignored_in_mop_mode(hass, setup_integration, mock_api, mock_props):
    """Setting fan speed in Mop mode sends no command."""
    coordinator = setup_integration
    mock_props.mode = 2
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "vacuum", "set_fan_speed",
        {"entity_id": "vacuum.test_vacuum", "fan_speed": "Turbo"},
        blocking=True,
    )
    mock_api.async_set_property.assert_not_called()


async def test_send_command_app_segment_clean(hass, setup_integration, mock_api):
    """app_segment_clean command (from HAMH/Apple Home) triggers room cleaning."""
    await hass.services.async_call(
        "vacuum", "send_command",
        {"entity_id": "vacuum.test_vacuum", "command": "app_segment_clean", "params": [2]},
        blocking=True,
    )
    call_args = mock_api.async_send_command.call_args
    assert call_args[0][1] == CMD_START["service"]
    assert call_args[0][2]["room_ids"] == [2]
