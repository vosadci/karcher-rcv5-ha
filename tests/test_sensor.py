"""Tests for the battery sensor entity."""
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
