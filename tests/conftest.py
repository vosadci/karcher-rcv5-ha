"""Shared fixtures for Kärcher integration tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from karcher.device import Device, DeviceProperties

from custom_components.karcher_home_robots.const import (
    CONF_COUNTRY,
    CONF_DEVICE_ID,
    CONF_DEVICE_NICKNAME,
    CONF_DEVICE_SN,
    CONF_EMAIL,
    CONF_PASSWORD,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests."""
    return enable_custom_integrations


@pytest.fixture
def mock_device() -> MagicMock:
    """A mock Kärcher Device."""
    device = MagicMock(spec=Device)
    device.device_id = "test_device_123"
    device.sn = "TEST123"
    device.nickname = "Test Vacuum"
    device.product_id = MagicMock()
    device.product_id.name = "RCV5"
    device.product_id.value = "1540149850806333440"
    return device


@pytest.fixture
def mock_props() -> MagicMock:
    """Mock DeviceProperties representing a docked, fully charged robot."""
    props = MagicMock(spec=DeviceProperties)
    props.work_mode = 0      # WORK_MODE_IDLE
    props.status = 4         # STATUS_DOCKED
    props.charge_state = 1   # charging
    props.quantity = 100     # battery %
    props.wind = 1           # Standard fan speed
    props.mode = 0           # Vacuum-only
    props.water = 1          # Low water level
    props.fault = 0
    props.cleaning_time = 0
    props.cleaning_area = 0
    props.current_map_id = 1
    return props


@pytest.fixture
def mock_api(mock_device, mock_props) -> MagicMock:
    """Mock KarcherApi."""
    api = MagicMock()
    api.authenticate = AsyncMock()
    api.get_devices = AsyncMock(return_value=[mock_device])
    api.fetch_properties = MagicMock(return_value=mock_props)
    api.get_rooms = AsyncMock(return_value=[
        {"id": 1, "name": "Living Room"},
        {"id": 2, "name": "Kitchen"},
    ])
    api.subscribe_device = MagicMock()
    api.set_push_callback = MagicMock()
    api.request_update = MagicMock()
    api.send_command = MagicMock()
    api.set_property = MagicMock()
    api.async_send_command = AsyncMock()
    api.async_set_property = AsyncMock()
    api.close = AsyncMock()
    return api


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A mock config entry for a single device."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Vacuum",
        unique_id="test_device_123",
        data={
            CONF_COUNTRY: "EU",
            CONF_EMAIL: "test@example.com",
            CONF_PASSWORD: "test_password",
            CONF_DEVICE_ID: "test_device_123",
            CONF_DEVICE_SN: "TEST123",
            CONF_DEVICE_NICKNAME: "Test Vacuum",
        },
    )


@pytest.fixture
async def setup_integration(hass, mock_config_entry, mock_api, mock_device):
    """Set up the integration with mocked API; return the coordinator."""
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.karcher_home_robots.KarcherApi", return_value=mock_api), \
         patch.object(mock_api, "get_devices", AsyncMock(return_value=[mock_device])):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    return hass.data[DOMAIN][mock_config_entry.entry_id]
