"""Tests for sensor entities."""
from __future__ import annotations

import pytest
from homeassistant.components.sensor import SensorDeviceClass


async def test_battery_value(hass, setup_integration):
    """Battery level reflects DeviceProperties.quantity."""
    state = hass.states.get("sensor.test_vacuum_battery")
    assert state is not None
    assert state.state == "100"


async def test_battery_zero(hass, setup_integration, mock_props):
    """Battery at 0% is reported as '0', not 'unknown'."""
    coordinator = setup_integration
    mock_props.quantity = 0
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_vacuum_battery")
    assert state.state == "0"


async def test_battery_device_class(hass, setup_integration):
    """Sensor device class is BATTERY."""
    state = hass.states.get("sensor.test_vacuum_battery")
    assert state.attributes.get("device_class") == SensorDeviceClass.BATTERY


async def test_battery_unit(hass, setup_integration):
    """Unit of measurement is %."""
    state = hass.states.get("sensor.test_vacuum_battery")
    assert state.attributes.get("unit_of_measurement") == "%"


async def test_battery_unavailable_when_coordinator_fails(hass, setup_integration):
    """Sensor becomes unavailable when coordinator has no data."""
    coordinator = setup_integration
    # Simulate coordinator failure by clearing data
    coordinator.async_set_updated_data(None)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_vacuum_battery")
    assert state.state in ("unavailable", "unknown")


# --- Cleaning Area ---


async def test_cleaning_area_value(hass, setup_integration, mock_props):
    """Cleaning area reflects DeviceProperties.cleaning_area."""
    coordinator = setup_integration
    mock_props.cleaning_area = 12.5
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_vacuum_cleaning_area")
    assert state is not None
    assert state.state == "12.5"


async def test_cleaning_area_zero(hass, setup_integration, mock_props):
    """Cleaning area of 0 is reported as '0', not 'unknown'."""
    coordinator = setup_integration
    mock_props.cleaning_area = 0
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_vacuum_cleaning_area")
    assert state.state == "0"


async def test_cleaning_area_unit(hass, setup_integration):
    """Unit of measurement is m²."""
    state = hass.states.get("sensor.test_vacuum_cleaning_area")
    assert state.attributes.get("unit_of_measurement") == "m²"


# --- Cleaning Time ---


async def test_cleaning_time_value(hass, setup_integration, mock_props):
    """Cleaning time reflects DeviceProperties.cleaning_time."""
    coordinator = setup_integration
    mock_props.cleaning_time = 1800
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_vacuum_cleaning_time")
    assert state is not None
    assert state.state == "1800"


async def test_cleaning_time_zero(hass, setup_integration, mock_props):
    """Cleaning time of 0 is reported as '0', not 'unknown'."""
    coordinator = setup_integration
    mock_props.cleaning_time = 0
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_vacuum_cleaning_time")
    assert state.state == "0"


async def test_cleaning_time_device_class(hass, setup_integration):
    """Sensor device class is DURATION."""
    state = hass.states.get("sensor.test_vacuum_cleaning_time")
    assert state.attributes.get("device_class") == SensorDeviceClass.DURATION
