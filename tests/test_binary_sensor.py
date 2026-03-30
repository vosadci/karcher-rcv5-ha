"""Tests for the error binary sensor entity."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass


async def test_error_off_when_no_fault(hass, setup_integration):
    """Error sensor is off when fault is 0."""
    state = hass.states.get("binary_sensor.test_vacuum_error")
    assert state is not None
    assert state.state == "off"


async def test_error_on_when_fault_and_idle(hass, setup_integration, mock_props):
    """Error sensor turns on when fault is non-zero and robot is idle (not docked)."""
    coordinator = setup_integration
    mock_props.fault = 5
    mock_props.work_mode = 0   # idle
    mock_props.status = 1      # not docked (STATUS_DOCKED = 4)
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.test_vacuum_error")
    assert state.state == "on"


async def test_error_off_when_fault_but_docked(hass, setup_integration, mock_props):
    """Fault suppressed when robot is docked — transient warning, not a real error."""
    coordinator = setup_integration
    mock_props.fault = 5
    mock_props.work_mode = 0   # idle
    mock_props.status = 4      # STATUS_DOCKED
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.test_vacuum_error")
    assert state.state == "off"


async def test_error_off_when_fault_during_cleaning(hass, setup_integration, mock_props):
    """Fault suppressed during active cleaning — non-zero fault is normal mid-run."""
    coordinator = setup_integration
    mock_props.fault = 5
    mock_props.work_mode = 1   # cleaning (not in WORK_MODE_IDLE)
    mock_props.status = 5
    coordinator.async_set_updated_data(mock_props)
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.test_vacuum_error")
    assert state.state == "off"


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
