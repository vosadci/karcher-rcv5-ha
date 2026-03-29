"""Tests for the error binary sensor entity."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass


async def test_error_off_when_no_fault(hass, setup_integration):
    """Error sensor is off when fault is 0."""
    state = hass.states.get("binary_sensor.test_vacuum_error")
    assert state is not None
    assert state.state == "off"


async def test_error_on_when_fault(hass, setup_integration, mock_props):
    """Error sensor turns on when fault is non-zero."""
    coordinator = setup_integration
    mock_props.fault = 5
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.test_vacuum_error")
    assert state.state == "on"


async def test_error_device_class(hass, setup_integration):
    """Device class is PROBLEM."""
    state = hass.states.get("binary_sensor.test_vacuum_error")
    assert state.attributes.get("device_class") == BinarySensorDeviceClass.PROBLEM


async def test_error_unavailable_when_coordinator_fails(hass, setup_integration):
    """Error sensor becomes unavailable when coordinator has no data."""
    coordinator = setup_integration
    coordinator.async_set_updated_data(None)
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.test_vacuum_error")
    assert state.state in ("unavailable", "unknown")
