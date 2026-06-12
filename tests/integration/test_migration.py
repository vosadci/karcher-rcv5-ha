# SPDX-License-Identifier: MIT
"""Integration tests for config-entry migration (async_migrate_entry).

The integration ships flow VERSION = 3. v2 was the first publicly accessible
entry version; v2 → v3 drops the redundant sn / product_id / nickname keys.
v1 never shipped and fails migration cleanly (MIGRATION_ERROR, not a crash).
"""

from __future__ import annotations

from custom_components.karcher_home_robots.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import ENTRY_DATA, TEST_DEVICE, FakeAdapter, patch_adapter


async def test_migrate_v2_entry_drops_redundant_keys(hass: HomeAssistant) -> None:
    """A v2 entry is migrated to v3 and loads; sn/product_id/nickname are dropped."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            **ENTRY_DATA,
            "sn": TEST_DEVICE.sn,
            "product_id": TEST_DEVICE.product_id,
            "nickname": TEST_DEVICE.nickname,
        },
        unique_id=TEST_DEVICE.device_id,
        version=2,
    )
    entry.add_to_hass(hass)

    with patch_adapter(FakeAdapter()):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == 3
    for key in ("sn", "product_id", "nickname"):
        assert key not in entry.data


async def test_migrate_v1_entry_fails_cleanly(hass: HomeAssistant) -> None:
    """A v1 entry fails migration with MIGRATION_ERROR instead of crashing setup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id=TEST_DEVICE.device_id,
        version=1,
    )
    entry.add_to_hass(hass)

    with patch_adapter(FakeAdapter()):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.MIGRATION_ERROR


async def test_v3_entry_not_modified(hass: HomeAssistant) -> None:
    """A current-version entry loads without data changes (no spurious migration)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id=TEST_DEVICE.device_id,
        version=3,
    )
    entry.add_to_hass(hass)
    data_before = dict(entry.data)

    with patch_adapter(FakeAdapter()):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    # Setup adds region_endpoint_snapshot; the original keys are untouched.
    for key, value in data_before.items():
        assert entry.data[key] == value
