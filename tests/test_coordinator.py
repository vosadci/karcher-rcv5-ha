"""Tests for KarcherCoordinator and derive_vacuum_state."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from karcher.exception import KarcherHomeAccessDenied, KarcherHomeTokenExpired
from karcher.identifiers import VacuumState

from custom_components.karcher.coordinator import KarcherCoordinator, derive_vacuum_state
from custom_components.karcher.const import (
    STATUS_DOCKED,
    WORK_MODE_CLEANING,
    WORK_MODE_GO_HOME,
    WORK_MODE_IDLE,
    WORK_MODE_PAUSE,
)


@pytest.fixture
async def coordinator(hass, mock_api, mock_device, mock_props):
    coord = KarcherCoordinator(hass, mock_api, mock_device)
    coord.async_set_updated_data(mock_props)
    return coord


async def test_update_data_returns_properties(hass, mock_api, mock_device, mock_props):
    """Polling calls fetch_properties and returns the result."""
    coord = KarcherCoordinator(hass, mock_api, mock_device)
    with patch.object(hass, "async_add_executor_job", new=AsyncMock(return_value=mock_props)) as mock_exec:
        result = await coord._async_update_data()
    mock_exec.assert_called_once_with(mock_api.fetch_properties, mock_device)
    assert result is mock_props


async def test_update_data_token_expired(hass, mock_api, mock_device):
    """Token expiry raises ConfigEntryAuthFailed."""
    coord = KarcherCoordinator(hass, mock_api, mock_device)
    with patch.object(hass, "async_add_executor_job", new=AsyncMock(side_effect=KarcherHomeTokenExpired)):
        with pytest.raises(ConfigEntryAuthFailed):
            await coord._async_update_data()


async def test_update_data_access_denied(hass, mock_api, mock_device):
    """Access denied raises ConfigEntryAuthFailed."""
    coord = KarcherCoordinator(hass, mock_api, mock_device)
    with patch.object(hass, "async_add_executor_job", new=AsyncMock(side_effect=KarcherHomeAccessDenied("denied"))):
        with pytest.raises(ConfigEntryAuthFailed):
            await coord._async_update_data()


async def test_update_data_generic_error(hass, mock_api, mock_device):
    """Generic exception wraps into UpdateFailed."""
    coord = KarcherCoordinator(hass, mock_api, mock_device)
    with patch.object(hass, "async_add_executor_job", new=AsyncMock(side_effect=RuntimeError("boom"))):
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()


async def test_mqtt_push_updates_data(coordinator, mock_props):
    """handle_mqtt_push updates coordinator.data."""
    new_props = MagicMock()
    new_props.quantity = 50
    coordinator.handle_mqtt_push(new_props)
    assert coordinator.data is new_props


# ── derive_vacuum_state ──────────────────────────────────────────────────────

def make_props(work_mode, status=0, charge_state=0, fault=0):
    p = MagicMock()
    p.work_mode = work_mode
    p.status = status
    p.charge_state = charge_state
    p.fault = fault
    return p


def test_derive_state_cleaning():
    wm = next(iter(WORK_MODE_CLEANING))
    assert derive_vacuum_state(make_props(wm)) == VacuumState.Cleaning


def test_derive_state_paused():
    wm = next(iter(WORK_MODE_PAUSE))
    assert derive_vacuum_state(make_props(wm)) == VacuumState.Paused


def test_derive_state_returning():
    wm = next(iter(WORK_MODE_GO_HOME))
    assert derive_vacuum_state(make_props(wm, status=0, charge_state=0)) == VacuumState.Returning


def test_derive_state_docked_via_status():
    wm = next(iter(WORK_MODE_IDLE))
    assert derive_vacuum_state(make_props(wm, status=STATUS_DOCKED)) == VacuumState.Docked


def test_derive_state_docked_via_charge_state():
    wm = next(iter(WORK_MODE_IDLE))
    assert derive_vacuum_state(make_props(wm, charge_state=1)) == VacuumState.Docked


def test_derive_state_error():
    wm = next(iter(WORK_MODE_IDLE))
    assert derive_vacuum_state(make_props(wm, fault=1)) == VacuumState.Error


def test_derive_state_go_home_then_docked():
    wm = next(iter(WORK_MODE_GO_HOME))
    assert derive_vacuum_state(make_props(wm, status=STATUS_DOCKED)) == VacuumState.Docked
