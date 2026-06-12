# SPDX-License-Identifier: MIT
"""Integration tests for room select and map-ID change handling.

FR-RG-2, P3-2, P3-3, P3-6, P3-8
"""

from __future__ import annotations

import logging

import pytest
from custom_components.karcher_home_robots.adapter import Room
from custom_components.karcher_home_robots.const import DOMAIN
from custom_components.karcher_home_robots.select import ALL_ROOMS_LABEL, KarcherRoomSelect
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import (
    ENTRY_DATA,
    PROPS_IDLE,
    TEST_DEVICE,
    TEST_ROOMS,
    FakeAdapter,
    make_props,
    patch_adapter,
)


async def _setup(hass: HomeAssistant, fake: FakeAdapter) -> MockConfigEntry:
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
    return entry


# ---------------------------------------------------------------------------
# Room select options (FR-SL-1)
# ---------------------------------------------------------------------------


async def test_room_select_options_include_all_rooms(hass: HomeAssistant) -> None:
    """Room select always has sentinel plus each room name (FR-SL-1)."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)

    coordinator = entry.runtime_data
    entity = KarcherRoomSelect(coordinator)
    assert ALL_ROOMS_LABEL in entity.options
    assert "Living Room" in entity.options
    assert "Bedroom" in entity.options
    assert entity.options[0] == ALL_ROOMS_LABEL


async def test_room_select_unavailable_when_no_rooms(hass: HomeAssistant) -> None:
    """Room select is unavailable when coordinator.rooms is empty (FR-SL-2)."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=[])
    entry = await _setup(hass, fake)

    coordinator = entry.runtime_data
    entity = KarcherRoomSelect(coordinator)
    assert not entity.available


async def test_room_select_available_when_rooms_loaded(hass: HomeAssistant) -> None:
    """Room select is available when rooms are known (FR-SL-2)."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)

    coordinator = entry.runtime_data
    entity = KarcherRoomSelect(coordinator)
    assert entity.available


# ---------------------------------------------------------------------------
# Room selection stored on coordinator (FR-SL-3)
# ---------------------------------------------------------------------------


async def test_room_select_defaults_to_all_rooms(hass: HomeAssistant) -> None:
    """Default current_option is All rooms (no room selected)."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)

    coordinator = entry.runtime_data
    entity = KarcherRoomSelect(coordinator)
    assert entity.current_option == ALL_ROOMS_LABEL


async def test_room_select_stores_selection_on_coordinator(hass: HomeAssistant) -> None:
    """Selecting a room stores its ID on the coordinator (FR-SL-3)."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)

    coordinator = entry.runtime_data
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.test_robot_room", "option": "Bedroom"},
        blocking=True,
    )

    assert coordinator.get_selected_room_id() == 2  # TEST_ROOMS[1].room_id


async def test_room_select_all_rooms_clears_selection(hass: HomeAssistant) -> None:
    """Selecting All rooms clears the coordinator selection (FR-SL-3)."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)

    coordinator = entry.runtime_data
    coordinator.set_selected_room_id(1)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.test_robot_room", "option": ALL_ROOMS_LABEL},
        blocking=True,
    )

    assert coordinator.get_selected_room_id() is None


# ---------------------------------------------------------------------------
# vacuum async_start consumes selected room (FR-V-1, FR-V-2)
# ---------------------------------------------------------------------------


async def test_start_uses_selected_room(hass: HomeAssistant) -> None:
    """async_start sends only the selected room ID when one is selected (FR-V-2)."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)

    coordinator = entry.runtime_data
    coordinator.set_selected_room_id(2)

    await hass.services.async_call(
        "vacuum", "start", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert len(fake.commands_sent) == 1
    _, params = fake.commands_sent[0]
    assert params["room_ids"] == [2]


async def test_start_consumes_selection_one_shot(hass: HomeAssistant) -> None:
    """The selection is consumed by exactly one start; the next start is whole-home.

    Regression guard for the Apple Home full-clean bug: HAMH dispatches
    "clean all rooms" from Apple Home as a parameterless vacuum.start. A
    persistent selection (stale card map-tap or dropdown pick) turned every
    such start into a single-room clean.
    """
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)

    coordinator = entry.runtime_data
    coordinator.set_selected_room_id(2)

    await hass.services.async_call(
        "vacuum", "start", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )
    _, params = fake.commands_sent[0]
    assert params["room_ids"] == [2]
    assert coordinator.get_selected_room_ids() == set()

    # Robot is still idle in this fixture, so a second start dispatches a new
    # clean — now whole-home, because the selection was consumed.
    await hass.services.async_call(
        "vacuum", "start", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )
    _, params = fake.commands_sent[1]
    assert set(params["room_ids"]) == {r.room_id for r in TEST_ROOMS}


async def test_start_uses_all_rooms_when_none_selected(hass: HomeAssistant) -> None:
    """async_start sends all room IDs when no room is selected (FR-V-1)."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)

    coordinator = entry.runtime_data
    assert coordinator.get_selected_room_id() is None

    await hass.services.async_call(
        "vacuum", "start", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    _, params = fake.commands_sent[0]
    assert set(params["room_ids"]) == {1, 2}


# ---------------------------------------------------------------------------
# map_id change triggers room refresh (FR-SL-7, P3-6)
# ---------------------------------------------------------------------------


async def test_map_id_change_clears_rooms(hass: HomeAssistant) -> None:
    """A push with a new current_map_id clears rooms and resets selection (FR-SL-7)."""
    props_map1 = make_props(
        work_mode=0, status=0, charge_state=0, fault=0, battery=80, current_map_id="map-1"
    )
    fake = FakeAdapter(props=props_map1, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)

    coordinator = entry.runtime_data
    coordinator.set_selected_room_id(1)
    assert coordinator.rooms == TEST_ROOMS

    # Push with new map_id — FakeAdapter.get_rooms will return [] for new maps
    props_map2 = make_props(
        work_mode=0, status=0, charge_state=0, fault=0, battery=80, current_map_id="map-2"
    )
    fake._props = props_map2
    fake._rooms = []  # new map has no rooms yet

    fake.fire_push(props_map2)
    await hass.async_block_till_done()

    assert coordinator.rooms == []
    assert coordinator.get_selected_room_id() is None


async def test_map_id_no_change_does_not_refresh(hass: HomeAssistant) -> None:
    """Same current_map_id does not trigger a room refresh (FR-SL-7)."""
    props = make_props(
        work_mode=0, status=0, charge_state=0, fault=0, battery=80, current_map_id="map-1"
    )
    fake = FakeAdapter(props=props, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)

    coordinator = entry.runtime_data
    initial_rooms = list(coordinator.rooms)

    # Push same map_id
    fake.fire_push(props)
    await hass.async_block_till_done()

    assert coordinator.rooms == initial_rooms


# ---------------------------------------------------------------------------
# Empty rooms path (FR-SL-2, P3-8)
# ---------------------------------------------------------------------------


async def test_empty_rooms_vacuum_start_sends_empty_list(hass: HomeAssistant) -> None:
    """When no rooms are known, async_start sends an empty room_ids list (P3-8).

    The robot is expected to clean everything in this case.
    """
    fake = FakeAdapter(props=PROPS_IDLE, rooms=[])
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum", "start", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert len(fake.commands_sent) == 1
    _, params = fake.commands_sent[0]
    assert params["room_ids"] == []


# ---------------------------------------------------------------------------
# Endpoint snapshot persisted (FR-RG-2)
# ---------------------------------------------------------------------------


async def test_endpoint_snapshot_stored_in_entry_data(hass: HomeAssistant) -> None:
    """get_endpoint_snapshot() result is persisted in config entry data (FR-RG-2)."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)

    assert "region_endpoint_snapshot" in entry.data
    snapshot = entry.data["region_endpoint_snapshot"]
    assert "rest_base_url" in snapshot
    assert "mqtt_url" in snapshot


# ---------------------------------------------------------------------------
# current_option fallback when selected room ID is not in room list
# ---------------------------------------------------------------------------


async def test_room_current_option_falls_back_when_id_not_in_list(
    hass: HomeAssistant,
) -> None:
    """current_option returns ALL_ROOMS_LABEL when selected room_id no longer in list.

    Covers: select.py lines 100->99, 102
    """
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)

    coordinator = entry.runtime_data
    entity = KarcherRoomSelect(coordinator)

    # Select a room ID that does not exist in the room list.
    coordinator.set_selected_room_id(999)
    assert entity.current_option == ALL_ROOMS_LABEL


async def test_room_select_option_unknown_name_raises(
    hass: HomeAssistant,
) -> None:
    """async_select_option with an unknown room name raises ServiceValidationError.

    Covers: select.py line 113
    """
    import pytest
    from homeassistant.exceptions import ServiceValidationError

    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)

    coordinator = entry.runtime_data
    entity = KarcherRoomSelect(coordinator)

    with pytest.raises(ServiceValidationError):
        await entity.async_select_option("Nonexistent Room")
    assert coordinator.get_selected_room_id() is None


async def test_duplicate_room_name_logs_warning(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_name_to_id logs a warning when two rooms share the same name (select.py line 89).

    The first room's ID wins; the second is ignored.
    """
    dup_rooms = [Room(room_id=1, name="Kitchen"), Room(room_id=2, name="Kitchen")]
    fake = FakeAdapter(props=PROPS_IDLE, rooms=dup_rooms)
    entry = await _setup(hass, fake)

    coordinator = entry.runtime_data
    entity = KarcherRoomSelect(coordinator)

    with caplog.at_level(logging.WARNING, logger="custom_components.karcher_home_robots.select"):
        name_to_id = entity._name_to_id()

    assert "Duplicate room name" in caplog.text
    assert name_to_id["Kitchen"] == 1


# ---------------------------------------------------------------------------
# async_start sends room_ids in preference order, not map order
# ---------------------------------------------------------------------------


async def test_start_sends_room_ids_in_preference_order(hass: HomeAssistant) -> None:
    """async_start delegates to default_clean_room_ids → preference order on the wire.

    Regression guard for the per-room-order bug: HA used to send
    `[r.room_id for r in coordinator.rooms]` (map-parser order). The robot
    honours the order of room_ids in set_room_clean
    (ControlMainActivity.java:2410-2419), so the user-arranged order was lost.
    """
    from custom_components.karcher_home_robots._types import RoomPreference

    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    # Preference order is inverted vs. coordinator.rooms (which is TEST_ROOMS).
    coordinator.prefer_mode = "standard"
    coordinator.room_preferences = [
        RoomPreference(
            room_id=2,
            room_name="Bedroom",
            mode=0,
            wind=1,
            water=2,
            repeat=0,
            check=0,
            carpet_avoidance=0,
        ),
        RoomPreference(
            room_id=1,
            room_name="Living Room",
            mode=0,
            wind=1,
            water=2,
            repeat=0,
            check=0,
            carpet_avoidance=0,
        ),
    ]

    await hass.services.async_call(
        "vacuum", "start", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    _, params = fake.commands_sent[-1]
    assert params["room_ids"] == [2, 1]
