# SPDX-License-Identifier: MIT
"""Per-room entities (select/switch/number) are added when rooms arrive late.

Regression guard: per-room entities were created once at platform setup from
coordinator.rooms; rooms recovered later via _retry_room_fetch or a map-change
refresh never got entities until a reload.
"""

from __future__ import annotations

from custom_components.karcher_home_robots.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import ENTRY_DATA, TEST_DEVICE, TEST_ROOMS, FakeAdapter, patch_adapter


def _unique_ids(hass: HomeAssistant, entry: MockConfigEntry) -> set[str]:
    ent_reg = er.async_get(hass)
    return {e.unique_id for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)}


async def test_per_room_entities_added_when_rooms_arrive_late(hass: HomeAssistant) -> None:
    """Rooms appearing after setup produce select/switch/number entities."""
    fake = FakeAdapter(rooms=[])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id=TEST_DEVICE.device_id,
        version=3,
    )
    entry.add_to_hass(hass)
    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    dev = TEST_DEVICE.device_id
    uids = _unique_ids(hass, entry)
    assert f"{dev}_room_1_mode" not in uids
    assert f"{dev}_room_1_custom" not in uids
    assert f"{dev}_room_1_order" not in uids

    # Rooms arrive later (retried fetch or map change) and listeners fire.
    coordinator = entry.runtime_data
    coordinator.rooms = list(TEST_ROOMS)
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    uids = _unique_ids(hass, entry)
    for room_id in (1, 2):
        assert f"{dev}_room_{room_id}_mode" in uids
        assert f"{dev}_room_{room_id}_power" in uids
        assert f"{dev}_room_{room_id}_repeat" in uids
        assert f"{dev}_room_{room_id}_custom" in uids
        assert f"{dev}_room_{room_id}_order" in uids


async def test_per_room_entities_present_when_rooms_known_at_setup(hass: HomeAssistant) -> None:
    """Rooms known at setup still produce their entities immediately."""
    fake = FakeAdapter(rooms=TEST_ROOMS)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id=TEST_DEVICE.device_id,
        version=3,
    )
    entry.add_to_hass(hass)
    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    uids = _unique_ids(hass, entry)
    dev = TEST_DEVICE.device_id
    assert f"{dev}_room_1_mode" in uids
    assert f"{dev}_room_2_custom" in uids
    assert f"{dev}_room_2_order" in uids


async def test_per_room_entity_name_follows_rename(hass: HomeAssistant) -> None:
    """Renaming a room on the robot updates the per-room entity's friendly name."""
    from custom_components.karcher_home_robots.adapter import Room

    fake = FakeAdapter(rooms=TEST_ROOMS)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id=TEST_DEVICE.device_id,
        version=3,
    )
    entry.add_to_hass(hass)
    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id(
        "select", DOMAIN, f"{TEST_DEVICE.device_id}_room_1_mode"
    )
    assert entity_id is not None
    assert "Living Room mode" in hass.states.get(entity_id).attributes["friendly_name"]

    # Robot reports room 1 renamed; the entity name must track it.
    coordinator = entry.runtime_data
    coordinator.rooms = [Room(room_id=1, name="Kitchen"), Room(room_id=2, name="Bedroom")]
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    assert "Kitchen mode" in hass.states.get(entity_id).attributes["friendly_name"]


async def test_room_entities_not_duplicated_on_repeated_updates(hass: HomeAssistant) -> None:
    """Repeated coordinator updates do not attempt to re-add existing rooms."""
    fake = FakeAdapter(rooms=TEST_ROOMS)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id=TEST_DEVICE.device_id,
        version=3,
    )
    entry.add_to_hass(hass)
    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    before = _unique_ids(hass, entry)
    coordinator = entry.runtime_data
    coordinator.async_update_listeners()
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    assert _unique_ids(hass, entry) == before
