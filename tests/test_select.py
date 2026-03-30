"""Tests for the room, cleaning mode, and water level select entities."""
from __future__ import annotations

import pytest

from custom_components.karcher_home_robots.const import (
    CLEANING_MODE_LIST,
    WATER_LEVEL_LIST,
)


# ── Room select ──────────────────────────────────────────────────────────────

async def test_room_options(hass, setup_integration):
    """Room select lists 'All rooms' plus every room from the coordinator."""
    state = hass.states.get("select.test_vacuum_room")
    assert state is not None
    options = state.attributes["options"]
    assert options == ["All rooms", "Living Room", "Kitchen"]


async def test_room_default_all(hass, setup_integration):
    """Default room selection is 'All rooms'."""
    state = hass.states.get("select.test_vacuum_room")
    assert state.state == "All rooms"


async def test_room_select_updates_coordinator(hass, setup_integration):
    """Selecting 'Kitchen' sets coordinator.selected_room_id = 2."""
    coordinator = setup_integration
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.test_vacuum_room", "option": "Kitchen"},
        blocking=True,
    )
    assert coordinator.selected_room_id == 2


async def test_room_select_all_clears_id(hass, setup_integration):
    """Selecting 'All rooms' sets coordinator.selected_room_id = None."""
    coordinator = setup_integration
    coordinator.selected_room_id = 1  # pre-select a room

    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.test_vacuum_room", "option": "All rooms"},
        blocking=True,
    )
    assert coordinator.selected_room_id is None


# ── Cleaning mode select ─────────────────────────────────────────────────────

async def test_cleaning_mode_options(hass, setup_integration):
    """Cleaning mode select exposes all three modes."""
    state = hass.states.get("select.test_vacuum_cleaning_mode")
    assert state is not None
    assert state.attributes["options"] == CLEANING_MODE_LIST


async def test_cleaning_mode_current(hass, setup_integration):
    """mode=0 maps to 'Vacuum'."""
    state = hass.states.get("select.test_vacuum_cleaning_mode")
    assert state.state == "Vacuum"


async def test_cleaning_mode_select_mop(hass, setup_integration, mock_api):
    """Selecting 'Mop' sends set_property({mode: 2})."""
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.test_vacuum_cleaning_mode", "option": "Mop"},
        blocking=True,
    )
    call_args = mock_api.async_set_property.call_args
    assert call_args[0][1] == {"mode": 2}


async def test_cleaning_mode_select_vacuum_mop(hass, setup_integration, mock_api):
    """Selecting 'Vacuum and Mop' sends set_property({mode: 1})."""
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.test_vacuum_cleaning_mode", "option": "Vacuum and Mop"},
        blocking=True,
    )
    call_args = mock_api.async_set_property.call_args
    assert call_args[0][1] == {"mode": 1}


# ── Water level select ───────────────────────────────────────────────────────

async def test_water_level_unavailable_in_vacuum_mode(hass, setup_integration, mock_props):
    """Water level is unavailable when cleaning mode is Vacuum-only (mode=0)."""
    coordinator = setup_integration
    mock_props.mode = 0
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    state = hass.states.get("select.test_vacuum_water_level")
    assert state.state == "unavailable"


async def test_water_level_available_in_vacuum_mop_mode(hass, setup_integration, mock_props):
    """Water level is available when cleaning mode is Vacuum and Mop (mode=1)."""
    coordinator = setup_integration
    mock_props.mode = 1
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    state = hass.states.get("select.test_vacuum_water_level")
    assert state.state != "unavailable"


async def test_water_level_available_in_mop_mode(hass, setup_integration, mock_props):
    """Water level is available when cleaning mode is Mop (mode=2)."""
    coordinator = setup_integration
    mock_props.mode = 2
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    state = hass.states.get("select.test_vacuum_water_level")
    assert state.state != "unavailable"


async def test_water_level_options(hass, setup_integration):
    """Water level select exposes Low / Medium / High (no 'Off')."""
    state = hass.states.get("select.test_vacuum_water_level")
    assert state is not None
    assert state.attributes["options"] == WATER_LEVEL_LIST


async def test_water_level_current(hass, setup_integration, mock_props):
    """water=2 maps to 'Medium' when mode is Vacuum and Mop."""
    coordinator = setup_integration
    mock_props.mode = 1   # Vacuum and Mop — water level available
    mock_props.water = 2
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    state = hass.states.get("select.test_vacuum_water_level")
    assert state.state == "Medium"


async def test_water_level_select_high(hass, setup_integration, mock_api, mock_props):
    """Selecting 'High' sends set_property({water: 3})."""
    coordinator = setup_integration
    mock_props.mode = 1   # Vacuum and Mop — water level available
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.test_vacuum_water_level", "option": "High"},
        blocking=True,
    )
    call_args = mock_api.async_set_property.call_args
    assert call_args[0][1] == {"water": 3}


async def test_water_level_select_low(hass, setup_integration, mock_api, mock_props):
    """Selecting 'Low' sends set_property({water: 1})."""
    coordinator = setup_integration
    mock_props.mode = 1   # Vacuum and Mop — water level available
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.test_vacuum_water_level", "option": "Low"},
        blocking=True,
    )
    call_args = mock_api.async_set_property.call_args
    assert call_args[0][1] == {"water": 1}
