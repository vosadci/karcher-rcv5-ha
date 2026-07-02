# SPDX-License-Identifier: MIT
"""Lovelace resource registration: versioned URL and cache-bust-on-update.

Regression guard: the resource used to be registered with a versionless URL.
Combined with HA's service worker, a browser kept serving a stale card after
every deploy — see doc/PROTOCOL.md-adjacent lore in memory. The fix tags the
URL with the card's VERSION and updates the stored resource item whenever
that version changes, so every release self-busts the cache.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from custom_components.karcher_home_robots import (
    _CARD_FILE,
    _STATIC_PATH,
    _read_card_version,
    _register_lovelace_resource,
)
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import (
    ResourceStorageCollection,
    ResourceYAMLCollection,
)
from homeassistant.core import HomeAssistant


class _FakeLovelaceData:
    def __init__(self, resources: object) -> None:
        self.resources = resources


def _fake_resource_collection(items: list[dict[str, str]]) -> MagicMock:
    col = MagicMock(spec=ResourceStorageCollection)
    col.async_items = MagicMock(return_value=items)
    col.async_create_item = AsyncMock()
    col.async_update_item = AsyncMock()
    return col


def test_read_card_version_matches_file() -> None:
    """The regex extracts the same VERSION the browser console banner shows."""
    text = _CARD_FILE.read_text(encoding="utf-8")
    version = _read_card_version()
    assert f'const VERSION = "{version}"' in text


async def test_register_creates_versioned_resource_when_absent(hass: HomeAssistant) -> None:
    """No existing resource: creates one with a ?v=<VERSION> URL."""
    version = _read_card_version()
    col = _fake_resource_collection([])
    hass.data[LOVELACE_DATA] = _FakeLovelaceData(col)

    await _register_lovelace_resource(hass)

    col.async_create_item.assert_awaited_once()
    (created_data,) = col.async_create_item.await_args.args
    assert created_data["url"] == f"{_STATIC_PATH}/karcher-vacuum-card.js?v={version}"
    col.async_update_item.assert_not_called()


async def test_register_updates_stale_versioned_resource(hass: HomeAssistant) -> None:
    """An existing resource with an old ?v= is updated in place, not duplicated."""
    version = _read_card_version()
    stale_item = {"id": "abc123", "url": f"{_STATIC_PATH}/karcher-vacuum-card.js?v=0.0.1"}
    col = _fake_resource_collection([stale_item])
    hass.data[LOVELACE_DATA] = _FakeLovelaceData(col)

    await _register_lovelace_resource(hass)

    col.async_update_item.assert_awaited_once_with(
        "abc123", {"url": f"{_STATIC_PATH}/karcher-vacuum-card.js?v={version}"}
    )
    col.async_create_item.assert_not_called()


async def test_register_is_noop_when_already_current(hass: HomeAssistant) -> None:
    """A resource already carrying the current version is left untouched."""
    version = _read_card_version()
    current_item = {
        "id": "abc123",
        "url": f"{_STATIC_PATH}/karcher-vacuum-card.js?v={version}",
    }
    col = _fake_resource_collection([current_item])
    hass.data[LOVELACE_DATA] = _FakeLovelaceData(col)

    await _register_lovelace_resource(hass)

    col.async_create_item.assert_not_called()
    col.async_update_item.assert_not_called()


async def test_register_ignores_unrelated_resources(hass: HomeAssistant) -> None:
    """Other integrations' resources are left alone; ours is still created."""
    version = _read_card_version()
    other_item = {"id": "other", "url": "/some-other-card/card.js"}
    col = _fake_resource_collection([other_item])
    hass.data[LOVELACE_DATA] = _FakeLovelaceData(col)

    await _register_lovelace_resource(hass)

    col.async_create_item.assert_awaited_once()
    (created_data,) = col.async_create_item.await_args.args
    assert created_data["url"] == f"{_STATIC_PATH}/karcher-vacuum-card.js?v={version}"


async def test_register_noop_without_lovelace_data(hass: HomeAssistant) -> None:
    """No LOVELACE_DATA (lovelace not loaded yet) is a silent no-op, not an error."""
    hass.data.pop(LOVELACE_DATA, None)
    await _register_lovelace_resource(hass)  # must not raise


async def test_register_noop_for_yaml_resource_mode(hass: HomeAssistant) -> None:
    """resource_mode: yaml uses ResourceYAMLCollection — skip rather than write to it."""
    yaml_col = MagicMock(spec=ResourceYAMLCollection)
    hass.data[LOVELACE_DATA] = _FakeLovelaceData(yaml_col)

    await _register_lovelace_resource(hass)  # must not raise or touch yaml_col

    yaml_col.assert_not_called()


def test_read_card_version_raises_on_missing_constant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A malformed/renamed card file fails loudly instead of registering a bad URL."""
    bad_file = tmp_path / "karcher-vacuum-card.js"
    bad_file.write_text("// no version here", encoding="utf-8")
    monkeypatch.setattr("custom_components.karcher_home_robots._CARD_FILE", bad_file)

    with pytest.raises(ValueError, match="VERSION constant not found"):
        _read_card_version()
