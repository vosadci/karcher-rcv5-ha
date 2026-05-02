# SPDX-License-Identifier: MIT
"""Unit tests for the diagnostics redaction helper.

Covers: FR-D-2
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.karcher_home_robots.diagnostics import (
    _REDACTED,
    _redact,
    async_get_config_entry_diagnostics,
)
from tests.conftest import PROPS_IDLE, TEST_DEVICE, TEST_ROOMS


class TestRedact:
    """Tests for _redact()."""

    def test_redacts_password(self) -> None:
        result = _redact({"password": "s3cr3t"})
        assert result["password"] == _REDACTED

    def test_redacts_email(self) -> None:
        result = _redact({"email": "user@example.com"})
        assert result["email"] == _REDACTED

    def test_redacts_token(self) -> None:
        result = _redact({"token": "abc123"})
        assert result["token"] == _REDACTED

    def test_redacts_nonce(self) -> None:
        result = _redact({"nonce": "xyz"})
        assert result["nonce"] == _REDACTED

    def test_redacts_sn_key(self) -> None:
        result = _redact({"sn": "SN001"})
        assert result["sn"] == _REDACTED

    def test_preserves_non_sensitive_keys(self) -> None:
        result = _redact({"region": "eu", "device_id": "abc"})
        assert result["region"] == "eu"
        assert result["device_id"] == "abc"

    def test_redacts_nested_dict(self) -> None:
        result = _redact({"outer": {"password": "secret", "key": "value"}})
        assert result["outer"]["password"] == _REDACTED
        assert result["outer"]["key"] == "value"

    def test_redacts_in_list(self) -> None:
        result = _redact([{"password": "s3cr3t"}, {"region": "eu"}])
        assert result[0]["password"] == _REDACTED
        assert result[1]["region"] == "eu"

    def test_preserves_non_dict_non_list(self) -> None:
        assert _redact(42) == 42
        assert _redact("hello") == "hello"
        assert _redact(None) is None

    def test_case_insensitive_match(self) -> None:
        result = _redact({"PASSWORD": "s", "Token": "t"})
        assert result["PASSWORD"] == _REDACTED
        assert result["Token"] == _REDACTED


async def test_diagnostics_bundle_structure(hass: MagicMock) -> None:
    """async_get_config_entry_diagnostics returns expected top-level keys.

    Covers: FR-D-1
    """
    coordinator = MagicMock()
    coordinator.data = PROPS_IDLE
    coordinator.last_update_success = True
    coordinator.vacuum_state.value = "docked"
    coordinator.get_selected_room_id.return_value = None
    coordinator.rooms = TEST_ROOMS

    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.data = {
        "region": "eu",
        "email": "user@example.com",
        "password": "secret",
        "device_id": TEST_DEVICE.device_id,
        "sn": TEST_DEVICE.sn,
    }

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert "entry_data" in result
    assert "coordinator" in result
    assert "device_properties" in result
    assert "rooms" in result
    assert "karcher_home_version" in result


async def test_diagnostics_redacts_entry_data(hass: MagicMock) -> None:
    """Email, password, and sn are redacted in entry_data.

    Covers: FR-D-2
    """
    coordinator = MagicMock()
    coordinator.data = PROPS_IDLE
    coordinator.last_update_success = True
    coordinator.vacuum_state.value = "docked"
    coordinator.get_selected_room_id.return_value = None
    coordinator.rooms = []

    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.data = {
        "region": "eu",
        "email": "user@example.com",
        "password": "topsecret",
        "device_id": "abc",
        "sn": "SN001",
    }

    result = await async_get_config_entry_diagnostics(hass, entry)

    entry_data = result["entry_data"]
    assert entry_data["email"] == _REDACTED
    assert entry_data["password"] == _REDACTED
    assert entry_data["sn"] == _REDACTED
    assert entry_data["region"] == "eu"
    assert entry_data["device_id"] == "abc"


async def test_diagnostics_none_props(hass: MagicMock) -> None:
    """device_properties is None when coordinator.data is None."""
    coordinator = MagicMock()
    coordinator.data = None
    coordinator.last_update_success = False
    coordinator.vacuum_state.value = "unknown"
    coordinator.get_selected_room_id.return_value = None
    coordinator.rooms = []

    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.data = {"region": "eu", "device_id": "abc"}

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["device_properties"] is None


async def test_diagnostics_rooms_in_bundle(hass: MagicMock) -> None:
    """Rooms are serialised into the diagnostics bundle."""
    coordinator = MagicMock()
    coordinator.data = PROPS_IDLE
    coordinator.last_update_success = True
    coordinator.vacuum_state.value = "docked"
    coordinator.get_selected_room_id.return_value = 2
    coordinator.rooms = TEST_ROOMS

    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.data = {"region": "eu"}

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert len(result["rooms"]) == 2
    assert result["rooms"][0] == {"room_id": 1, "name": "Living Room"}
    assert result["coordinator"]["selected_room_id"] == 2
