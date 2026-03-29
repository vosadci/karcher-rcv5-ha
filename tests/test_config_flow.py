"""Tests for the Kärcher config flow."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from karcher.exception import KarcherHomeException, KarcherHomeInvalidAuth

from custom_components.karcher_home_robots.const import DOMAIN


@pytest.fixture
def mock_karcher_api(mock_device):
    """Patch KarcherApi in the config flow module."""
    api_instance = MagicMock()
    api_instance.authenticate = AsyncMock()
    api_instance.get_devices = AsyncMock(return_value=[mock_device])
    api_instance.close = AsyncMock()
    with patch("custom_components.karcher_home_robots.config_flow.KarcherApi", return_value=api_instance) as mock_cls:
        mock_cls.instance = api_instance
        yield api_instance


async def test_user_step_shows_region_form(hass):
    """First step renders the region selector form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert "country" in result["data_schema"].schema


async def test_credentials_step_shows_form(hass, mock_karcher_api):
    """After picking region, credentials form is shown."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"country": "EU"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "credentials"


async def test_credentials_invalid_auth(hass, mock_karcher_api):
    """Invalid credentials show the invalid_auth error."""
    mock_karcher_api.authenticate.side_effect = KarcherHomeInvalidAuth

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], {"country": "EU"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "bad@example.com", "password": "wrong"}
    )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_auth"


async def test_credentials_cannot_connect(hass, mock_karcher_api):
    """Network error shows the cannot_connect error."""
    mock_karcher_api.authenticate.side_effect = KarcherHomeException(0, "timeout")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], {"country": "EU"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "test@example.com", "password": "pass"}
    )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "cannot_connect"


async def test_single_device_creates_entry(hass, mock_karcher_api, mock_device):
    """Single device skips device picker and creates config entry directly."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], {"country": "EU"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "test@example.com", "password": "pass"}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == mock_device.nickname
    assert result["data"]["device_id"] == mock_device.device_id
    assert result["data"]["country"] == "EU"


async def test_multiple_devices_shows_picker(hass, mock_karcher_api, mock_device):
    """Multiple devices causes device picker step to appear."""
    device2 = MagicMock()
    device2.device_id = "device_456"
    device2.sn = "SN456"
    device2.nickname = "Second Vacuum"
    mock_karcher_api.get_devices.return_value = [mock_device, device2]

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], {"country": "EU"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "test@example.com", "password": "pass"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "device"


async def test_device_selection_creates_entry(hass, mock_karcher_api, mock_device):
    """Selecting a device from the picker creates the config entry."""
    device2 = MagicMock()
    device2.device_id = "device_456"
    device2.sn = "SN456"
    device2.nickname = "Second Vacuum"
    mock_karcher_api.get_devices.return_value = [mock_device, device2]

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], {"country": "EU"})
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "test@example.com", "password": "pass"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_id": "device_456"}
    )
    assert result["type"] == "create_entry"
    assert result["data"]["device_id"] == "device_456"


async def test_duplicate_prevented(hass, mock_karcher_api, mock_device):
    """Adding the same device twice aborts with already_configured."""
    # First setup
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], {"country": "EU"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "test@example.com", "password": "pass"}
    )
    assert result["type"] == "create_entry"

    # Second attempt — same device
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], {"country": "EU"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "test@example.com", "password": "pass"}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


async def test_reauth_updates_credentials(hass, mock_karcher_api, mock_config_entry):
    """Reauth flow replaces email and password in the config entry."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": mock_config_entry.entry_id},
        data=mock_config_entry.data,
    )
    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"

    with patch("custom_components.karcher_home_robots.config_flow.KarcherApi", return_value=mock_karcher_api):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"email": "new@example.com", "password": "new_password"},
        )

    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["email"] == "new@example.com"
    assert mock_config_entry.data["password"] == "new_password"


async def test_reauth_invalid_credentials(hass, mock_karcher_api, mock_config_entry):
    """Reauth with invalid credentials shows error and keeps original entry data."""
    mock_config_entry.add_to_hass(hass)
    mock_karcher_api.authenticate.side_effect = KarcherHomeInvalidAuth

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": mock_config_entry.entry_id},
        data=mock_config_entry.data,
    )
    with patch("custom_components.karcher_home_robots.config_flow.KarcherApi", return_value=mock_karcher_api):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"email": "bad@example.com", "password": "wrong"},
        )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_auth"
    # Original credentials unchanged
    assert mock_config_entry.data["email"] == "test@example.com"
