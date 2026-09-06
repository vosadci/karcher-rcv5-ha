# SPDX-License-Identifier: MIT
"""Unit tests for the diagnostics redaction helper."""

from __future__ import annotations

from importlib import metadata
from unittest.mock import MagicMock

import pytest
from custom_components.karcher_home_robots import diagnostics
from custom_components.karcher_home_robots.diagnostics import (
    _REDACTED,
    _redact,
    async_get_config_entry_diagnostics,
)
from syrupy.assertion import SnapshotAssertion
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
        result = _redact({"region": "eu"})
        assert result["region"] == "eu"

    def test_redacts_device_id(self) -> None:
        result = _redact({"device_id": "abc"})
        assert result["device_id"] == _REDACTED

    def test_redacts_mac(self) -> None:
        result = _redact({"mac": "AA:BB:CC:DD:EE:FF"})
        assert result["mac"] == _REDACTED

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

    def test_redacts_secret(self) -> None:
        assert _redact({"secret": "s"})["secret"] == _REDACTED

    def test_redacts_api_key(self) -> None:
        assert _redact({"api_key": "k"})["api_key"] == _REDACTED

    def test_redacts_mqtt_url(self) -> None:
        assert _redact({"mqtt_url": "mqtts://broker"})["mqtt_url"] == _REDACTED

    def test_redacts_broker(self) -> None:
        assert _redact({"broker": "mqtt.example.com"})["broker"] == _REDACTED

    def test_redacts_client_id(self) -> None:
        assert _redact({"client_id": "abc"})["client_id"] == _REDACTED

    def test_sn_word_boundary_does_not_match_snapshot(self) -> None:
        result = _redact({"region_endpoint_snapshot": "eu"})
        assert result["region_endpoint_snapshot"] == "eu"

    def test_mac_word_boundary_does_not_match_unrelated(self) -> None:
        result = _redact({"smack": "value"})
        assert result["smack"] == "value"


async def test_diagnostics_bundle_structure(hass: MagicMock) -> None:
    """async_get_config_entry_diagnostics returns expected top-level keys."""
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
    # Asserted by value, not key presence: the field reported the literal
    # "unknown" on every install for as long as it existed, and a key-presence
    # check cannot tell the difference. metadata.version() here is an
    # independent path to the same answer adapter._library_version() computes.
    assert result["karcher_home_version"] == metadata.version("karcher-home")
    assert result["karcher_home_version"] != "unknown"


async def test_diagnostics_redacts_entry_data(hass: MagicMock) -> None:
    """Email, password, and sn are redacted in entry_data."""
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
    assert entry_data["device_id"] == _REDACTED
    assert entry_data["region"] == "eu"


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


async def test_diagnostics_bundle_snapshot(
    hass: MagicMock, snapshot: SnapshotAssertion, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full redacted bundle regression net.

    Complements the explicit redaction asserts above (which stay the
    authoritative security check): a snapshot of the whole bundle catches any
    newly added field — and surfaces it in the diff if it carries unredacted
    PII — without having to predict the key name in advance.

    The library version is pinned to a sentinel so the snapshot stays a
    statement about redaction shape; the real value is asserted in
    test_diagnostics_bundle_structure.
    """
    monkeypatch.setattr(diagnostics, "KARCHER_HOME_VERSION", "0.0.0-test")
    coordinator = MagicMock()
    coordinator.data = PROPS_IDLE
    coordinator.last_update_success = True
    coordinator.vacuum_state.value = "docked"
    coordinator.get_selected_room_id.return_value = 1
    coordinator.rooms = TEST_ROOMS

    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.data = {
        "region": "eu",
        "email": "user@example.com",
        "password": "topsecret",
        "device_id": TEST_DEVICE.device_id,
        "sn": TEST_DEVICE.sn,
    }

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result == snapshot
