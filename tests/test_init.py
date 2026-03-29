"""Tests for integration setup and unload."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from karcher.exception import KarcherHomeException, KarcherHomeInvalidAuth

from custom_components.karcher_home_robots.const import DOMAIN


async def test_setup_entry_success(hass, mock_config_entry, mock_api, mock_device):
    """Successful setup stores coordinator in hass.data and loads all platforms."""
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.karcher_home_robots.KarcherApi", return_value=mock_api), \
         patch.object(mock_api, "get_devices", AsyncMock(return_value=[mock_device])):
        result = await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert mock_config_entry.entry_id in hass.data[DOMAIN]

    # All entity platforms registered
    assert hass.states.get("vacuum.test_vacuum") is not None
    assert hass.states.get("sensor.test_vacuum_battery") is not None


async def test_setup_entry_auth_failed(hass, mock_config_entry, mock_api):
    """Invalid credentials puts entry in SETUP_ERROR state."""
    mock_api.authenticate.side_effect = KarcherHomeInvalidAuth
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.karcher_home_robots.KarcherApi", return_value=mock_api):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state == ConfigEntryState.SETUP_ERROR


async def test_setup_entry_not_ready(hass, mock_config_entry, mock_api):
    """Network error puts entry in SETUP_RETRY state."""
    mock_api.authenticate.side_effect = KarcherHomeException(0, "timeout")
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.karcher_home_robots.KarcherApi", return_value=mock_api):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state == ConfigEntryState.SETUP_RETRY


async def test_setup_entry_device_not_found(hass, mock_config_entry, mock_api):
    """Device ID absent from account puts entry in SETUP_RETRY state."""
    mock_api.get_devices.return_value = []  # account has no devices
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.karcher_home_robots.KarcherApi", return_value=mock_api):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state == ConfigEntryState.SETUP_RETRY


async def test_unload_entry(hass, setup_integration, mock_config_entry, mock_api):
    """Unloading the entry calls api.close() and removes coordinator from hass.data."""
    assert mock_config_entry.entry_id in hass.data[DOMAIN]

    result = await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert result is True
    assert mock_config_entry.entry_id not in hass.data.get(DOMAIN, {})
    mock_api.close.assert_called_once()


async def test_subscribe_before_first_refresh(hass, mock_config_entry, mock_api, mock_device):
    """subscribe_device is called before first_refresh to establish the MQTT
    connection, and set_push_callback is called after to wire the real callback."""
    call_order = []

    original_fetch = mock_api.fetch_properties
    def tracked_fetch(*args, **kwargs):
        call_order.append("fetch")
        return original_fetch(*args, **kwargs)
    mock_api.fetch_properties = tracked_fetch

    original_subscribe = mock_api.subscribe_device
    def tracked_subscribe(*args, **kwargs):
        call_order.append("subscribe")
        return original_subscribe(*args, **kwargs)
    mock_api.subscribe_device = tracked_subscribe

    original_set_cb = mock_api.set_push_callback
    def tracked_set_cb(*args, **kwargs):
        call_order.append("set_push_callback")
        return original_set_cb(*args, **kwargs)
    mock_api.set_push_callback = tracked_set_cb

    mock_config_entry.add_to_hass(hass)
    with patch("custom_components.karcher_home_robots.KarcherApi", return_value=mock_api), \
         patch.object(mock_api, "get_devices", AsyncMock(return_value=[mock_device])):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    subscribe_idx = next(i for i, v in enumerate(call_order) if v == "subscribe")
    fetch_idx = next(i for i, v in enumerate(call_order) if v == "fetch")
    set_cb_idx = next(i for i, v in enumerate(call_order) if v == "set_push_callback")
    assert subscribe_idx < fetch_idx, "subscribe_device must be called before first fetch"
    assert fetch_idx < set_cb_idx, "set_push_callback must be called after first fetch"
