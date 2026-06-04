# SPDX-License-Identifier: MIT
"""Integration tests for coordinator error-taxonomy and flap prevention."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest
from custom_components.karcher_home_robots._types import RoomPreference
from custom_components.karcher_home_robots.const import DOMAIN
from custom_components.karcher_home_robots.coordinator import KarcherCoordinator, VacuumState
from custom_components.karcher_home_robots.exceptions import (
    AuthError,
    PermanentError,
    ProtocolError,
    TransientError,
    ValidationError,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers.update_coordinator import UpdateFailed
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
# Error taxonomy — _async_update_data branches
# ---------------------------------------------------------------------------


async def test_validation_error_returns_cached_data(hass: HomeAssistant) -> None:
    """ValidationError during poll returns cached data (no UpdateFailed)."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    # Confirm we have data
    assert coordinator.data is not None

    # Inject a ValidationError on the next poll
    fake._fetch_raises = ValidationError("bad field")
    result = await coordinator._async_update_data()

    assert result is PROPS_IDLE


async def test_protocol_error_returns_cached_data(hass: HomeAssistant) -> None:
    """ProtocolError during poll returns cached data."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    fake._fetch_raises = ProtocolError("malformed")
    result = await coordinator._async_update_data()

    assert result is PROPS_IDLE


async def test_transient_error_below_threshold_returns_cached(hass: HomeAssistant) -> None:
    """First TransientError (below threshold=2) returns cached data."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    assert coordinator._consecutive_failures == 0

    fake._fetch_raises = TransientError("timeout")
    result = await coordinator._async_update_data()

    assert coordinator._consecutive_failures == 1
    assert result is PROPS_IDLE


async def test_transient_error_at_threshold_raises_update_failed(hass: HomeAssistant) -> None:
    """TransientError at or above threshold raises UpdateFailed.

    Flap prevention: threshold exceeded
    """
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    # Pre-load the failure counter to threshold - 1
    coordinator._consecutive_failures = 1
    fake._fetch_raises = TransientError("timeout again")

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_permanent_error_raises_config_entry_error(hass: HomeAssistant) -> None:
    """PermanentError during poll raises ConfigEntryError (not UpdateFailed)."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    fake._fetch_raises = PermanentError("device banned")

    with pytest.raises(ConfigEntryError):
        await coordinator._async_update_data()


# ---------------------------------------------------------------------------
# vacuum_state when data is None
# ---------------------------------------------------------------------------


async def test_vacuum_state_unknown_when_no_data(hass: HomeAssistant) -> None:
    """vacuum_state returns UNKNOWN when coordinator.data is None.

    Covers: coordinator.py line 341
    """
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    coordinator.data = None  # type: ignore[assignment]
    assert coordinator.vacuum_state is VacuumState.UNKNOWN


# ---------------------------------------------------------------------------
# get_selected_room_id
# ---------------------------------------------------------------------------


async def test_get_selected_room_id_returns_none_by_default(hass: HomeAssistant) -> None:
    """get_selected_room_id returns None before any selection.

    Covers: coordinator.py line 350
    """
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    assert coordinator.get_selected_room_id() is None


async def test_get_selected_room_id_returns_set_value(hass: HomeAssistant) -> None:
    """get_selected_room_id returns the value set by set_selected_room_id."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    coordinator.set_selected_room_id(42)
    assert coordinator.get_selected_room_id() == 42


# ---------------------------------------------------------------------------
# Initial room fetch failure (coordinator setup)
# ---------------------------------------------------------------------------


async def test_initial_room_fetch_failure_does_not_abort_setup(hass: HomeAssistant) -> None:
    """A failure on the initial get_rooms call logs a warning but setup succeeds.

    Covers: coordinator.py lines 188-189
    """

    class RoomFailAdapter(FakeAdapter):
        async def get_rooms(self, device):  # type: ignore[override]
            raise RuntimeError("network error")

    fake = RoomFailAdapter(props=PROPS_IDLE)
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
    coordinator = entry.runtime_data
    assert coordinator.rooms == []


# ---------------------------------------------------------------------------
# async_shutdown with pending room retry task
# ---------------------------------------------------------------------------


async def test_shutdown_cancels_room_retry_task(hass: HomeAssistant) -> None:
    """async_shutdown cancels a pending _room_retry_task without raising.

    Covers: coordinator.py lines 198-200
    """
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    # Plant a never-completing task to simulate an in-flight room retry.
    coordinator._room_retry_task = hass.loop.create_task(asyncio.sleep(9999))

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert coordinator._room_retry_task.cancelled()


# ---------------------------------------------------------------------------
# _maybe_refresh_rooms: new_map_id is None
# ---------------------------------------------------------------------------


async def test_maybe_refresh_rooms_no_op_when_map_id_becomes_none(
    hass: HomeAssistant,
) -> None:
    """_maybe_refresh_rooms clears rooms but skips fetch when new_map_id is None.

    Covers: coordinator.py line 250
    """
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    coordinator._current_map_id = 1
    coordinator.rooms = [make_props()]  # type: ignore[list-item]

    props_no_map = make_props(work_mode=0, status=0, charge_state=0, fault=0, battery=80)
    await coordinator._maybe_refresh_rooms(props_no_map)

    assert coordinator.rooms == []
    assert coordinator._current_map_id is None


# ---------------------------------------------------------------------------
# _maybe_refresh_rooms: get_rooms raises
# ---------------------------------------------------------------------------


async def test_maybe_refresh_rooms_handles_get_rooms_exception(
    hass: HomeAssistant,
) -> None:
    """_maybe_refresh_rooms logs a warning when get_rooms raises after map change.

    Covers: coordinator.py lines 253-254
    """

    class RoomFailAdapter(FakeAdapter):
        async def get_rooms(self, device):  # type: ignore[override]
            raise RuntimeError("rooms unavailable")

    fake = RoomFailAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    coordinator._current_map_id = None
    props_new_map = make_props(
        work_mode=0, status=0, charge_state=0, fault=0, battery=80, current_map_id=99
    )
    await coordinator._maybe_refresh_rooms(props_new_map)

    assert coordinator.rooms == []


# ---------------------------------------------------------------------------
# ValidationError with no cache raises UpdateFailed directly
# ---------------------------------------------------------------------------


async def test_validation_error_no_cache_raises_update_failed_directly(
    hass: HomeAssistant,
) -> None:
    """ValidationError with coordinator.data=None raises UpdateFailed immediately.

    Covers: coordinator.py line 280
    """
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    coordinator.data = None  # type: ignore[assignment]
    fake._fetch_raises = ValidationError("bad data")

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


# ---------------------------------------------------------------------------
# Poll path: room retry task created when rooms empty but map exists
# ---------------------------------------------------------------------------


async def test_poll_creates_room_retry_task_when_rooms_empty(
    hass: HomeAssistant,
) -> None:
    """A poll result with no rooms but a valid map_id spawns a retry task.

    Covers: coordinator.py line 305
    """
    props_with_map = make_props(
        work_mode=0, status=0, charge_state=0, fault=0, battery=80, current_map_id=1
    )
    fake = FakeAdapter(props=props_with_map, rooms=[])
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    coordinator.rooms = []
    coordinator._room_retry_task = None

    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert coordinator._room_retry_task is not None


# ---------------------------------------------------------------------------
# _retry_room_fetch: success and failure branches
# ---------------------------------------------------------------------------


async def test_retry_room_fetch_success_populates_rooms(hass: HomeAssistant) -> None:
    """_retry_room_fetch populates rooms when get_rooms succeeds.

    Covers: coordinator.py lines 316-318
    """
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    coordinator.rooms = []
    await coordinator._retry_room_fetch()

    assert coordinator.rooms == TEST_ROOMS


async def test_retry_room_fetch_failure_leaves_rooms_empty(hass: HomeAssistant) -> None:
    """_retry_room_fetch logs and returns without raising when get_rooms fails.

    Covers: coordinator.py lines 313-315
    """

    class RoomFailAdapter(FakeAdapter):
        async def get_rooms(self, device):  # type: ignore[override]
            raise RuntimeError("timeout")

    fake = RoomFailAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    coordinator.rooms = []
    await coordinator._retry_room_fetch()

    assert coordinator.rooms == []


async def test_auth_error_during_poll_raises_config_entry_auth_failed(
    hass: HomeAssistant,
) -> None:
    """AuthError from fetch_properties surfaces as ConfigEntryAuthFailed.

    Covers: coordinator.py line 273
    """
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    fake._fetch_raises = AuthError("token expired")
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_data_none_after_first_refresh_skips_map_id_capture(
    hass: HomeAssistant,
) -> None:
    """When first refresh yields no data, _current_map_id is not set.

    Covers: coordinator.py line 192->exit (false branch of 'if self.data is not None')
    """
    # Adapter whose fetch always raises so first_refresh yields no data.
    fake = FakeAdapter(props=PROPS_IDLE, fetch_raises=TransientError("offline"))

    coordinator = KarcherCoordinator(hass=hass, adapter=fake, device=TEST_DEVICE)
    # async_setup calls first_refresh which calls _async_update_data → raises
    # UpdateFailed; first_refresh then sets coordinator.data = None and re-raises.
    with contextlib.suppress(Exception):
        await coordinator.async_setup()

    assert coordinator._current_map_id is None


# ---------------------------------------------------------------------------
# async_shutdown with pending push tasks
# ---------------------------------------------------------------------------


async def test_shutdown_cancels_push_tasks(hass: HomeAssistant) -> None:
    """async_shutdown cancels in-flight _push_tasks and awaits them without raising.

    Covers: coordinator.py lines 177, 179
    """
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    # Plant a never-completing task to simulate an in-flight push side-effect.
    never_done: asyncio.Task[None] = hass.loop.create_task(asyncio.sleep(9999))
    coordinator._push_tasks.add(never_done)
    never_done.add_done_callback(coordinator._push_tasks.discard)

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert never_done.cancelled()


# ---------------------------------------------------------------------------
# _fetch_preference — preference loading and synthesis
# ---------------------------------------------------------------------------


async def test_fetch_preference_loads_rooms_from_reply(hass: HomeAssistant) -> None:
    """_fetch_preference parses the robot's reply into room_preferences (lines 271-302).

    When get_preference returns a valid room array, room_preferences is populated
    and prefer_mode reflects prefer_on.
    """
    raw_room = [1, "Kitchen", 0, 0, 1, 2, 0, 0, 0, 0, 0, 0]
    props = make_props(
        work_mode=0, status=0, charge_state=0, fault=0, battery=80, current_map_id="7"
    )
    fake = FakeAdapter(
        props=props,
        rooms=TEST_ROOMS,
        preference_result={"rooms": [raw_room], "prefer_on": 1},
    )
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    assert len(coordinator.room_preferences) == 1
    assert coordinator.room_preferences[0].room_id == 1
    assert coordinator.prefer_mode == "customise"


async def test_fetch_preference_synthesises_defaults_when_empty(hass: HomeAssistant) -> None:
    """_fetch_preference synthesises neutral defaults when robot has no stored prefs (281-299).

    Empty rooms array + non-empty room list → one synthetic pref per room.
    """
    props = make_props(
        work_mode=0, status=0, charge_state=0, fault=0, battery=80, current_map_id="7"
    )
    fake = FakeAdapter(
        props=props,
        rooms=TEST_ROOMS,
        preference_result={"rooms": [], "prefer_on": 0},
    )
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    assert len(coordinator.room_preferences) == len(TEST_ROOMS)
    assert coordinator.room_preferences[0].room_id == TEST_ROOMS[0].room_id
    assert coordinator.prefer_mode == "standard"


async def test_fetch_preference_skips_malformed_rows(hass: HomeAssistant) -> None:
    """_fetch_preference skips rows where from_raw returns None (branch 278->276).

    A malformed row (too short) is skipped; only the valid row is stored.
    """
    valid_row = [1, "Kitchen", 0, 0, 1, 2, 0, 0, 0, 0, 0, 0]
    bad_row: list[Any] = [1, 2]
    props = make_props(
        work_mode=0, status=0, charge_state=0, fault=0, battery=80, current_map_id="7"
    )
    fake = FakeAdapter(
        props=props,
        rooms=TEST_ROOMS,
        preference_result={"rooms": [bad_row, valid_row], "prefer_on": 0},
    )
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    assert len(coordinator.room_preferences) == 1
    assert coordinator.room_preferences[0].room_id == 1


# ---------------------------------------------------------------------------
# async_set_room_preference
# ---------------------------------------------------------------------------


async def test_set_room_preference_no_map_raises(hass: HomeAssistant) -> None:
    """async_set_room_preference raises ServiceValidationError when no map loaded (492-494)."""
    from homeassistant.exceptions import ServiceValidationError

    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    coordinator._current_map_id = None

    pref = RoomPreference(
        room_id=1, room_name="r", mode=0, wind=1, water=2, repeat=0, check=0, carpet_avoidance=0
    )
    with pytest.raises(ServiceValidationError, match="No map"):
        await coordinator.async_set_room_preference(1, pref)


async def test_set_room_preference_updates_cached_prefs(hass: HomeAssistant) -> None:
    """async_set_room_preference writes updated pref and refreshes local cache (lines 496-531)."""
    props = make_props(
        work_mode=0, status=0, charge_state=0, fault=0, battery=80, current_map_id="7"
    )
    raw_room = [1, "Kitchen", 0, 0, 1, 2, 0, 0, 0, 0, 0, 0]
    fake = FakeAdapter(
        props=props,
        rooms=TEST_ROOMS,
        preference_result={"rooms": [raw_room], "prefer_on": 0},
    )
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    updated = RoomPreference(
        room_id=1,
        room_name="Kitchen",
        mode=1,
        wind=2,
        water=3,
        repeat=1,
        check=1,
        carpet_avoidance=0,
    )
    await coordinator.async_set_room_preference(1, updated)

    assert len(fake.preferences_set) == 1
    saved_prefs = coordinator.room_preferences
    matching = [p for p in saved_prefs if p.room_id == 1]
    assert len(matching) == 1
    assert matching[0].mode == 1
    assert matching[0].wind == 2


async def test_set_room_preference_appends_unseen_rooms(hass: HomeAssistant) -> None:
    """async_set_room_preference appends rooms not yet in cached prefs (lines 507-524).

    When room_preferences is empty (e.g. get_preference timed out), the method
    builds the list from coordinator.rooms. The target room gets updated; others
    get neutral defaults.
    """
    props = make_props(
        work_mode=0, status=0, charge_state=0, fault=0, battery=80, current_map_id="7"
    )
    fake = FakeAdapter(
        props=props,
        rooms=TEST_ROOMS,
        preference_result={"rooms": [], "prefer_on": 0},
    )
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    coordinator.room_preferences = []

    updated = RoomPreference(
        room_id=1,
        room_name="Living Room",
        mode=0,
        wind=3,
        water=2,
        repeat=0,
        check=0,
        carpet_avoidance=0,
    )
    await coordinator.async_set_room_preference(1, updated)

    result = coordinator.room_preferences
    target = next(p for p in result if p.room_id == 1)
    assert target.wind == 3
    other = next(p for p in result if p.room_id == 2)
    assert other.wind == 1


# ---------------------------------------------------------------------------
# async_set_preference_type
# ---------------------------------------------------------------------------


async def test_set_preference_type_standard(hass: HomeAssistant) -> None:
    """async_set_preference_type sets prefer_mode to 'standard' for prefer_type=0 (533-537)."""
    props = make_props(
        work_mode=0, status=0, charge_state=0, fault=0, battery=80, current_map_id="7"
    )
    fake = FakeAdapter(props=props, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    await coordinator.async_set_preference_type(0)

    assert fake.preference_type_set[-1] == 0
    assert coordinator.prefer_mode == "standard"


async def test_set_preference_type_customise(hass: HomeAssistant) -> None:
    """async_set_preference_type sets prefer_mode to 'customise' for prefer_type=1 (533-537)."""
    props = make_props(
        work_mode=0, status=0, charge_state=0, fault=0, battery=80, current_map_id="7"
    )
    fake = FakeAdapter(props=props, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    await coordinator.async_set_preference_type(1)

    assert fake.preference_type_set[-1] == 1
    assert coordinator.prefer_mode == "customise"


# ---------------------------------------------------------------------------
# async_set_room_order
# ---------------------------------------------------------------------------


async def test_set_room_order_no_map_raises(hass: HomeAssistant) -> None:
    """async_set_room_order raises ServiceValidationError when no map loaded."""
    from homeassistant.exceptions import ServiceValidationError

    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    coordinator._current_map_id = None

    with pytest.raises(ServiceValidationError, match="No map"):
        await coordinator.async_set_room_order([1, 2])


async def test_set_room_order_preserves_existing_prefs(hass: HomeAssistant) -> None:
    """async_set_room_order writes rooms in the requested sequence, preserving settings."""
    props = make_props(
        work_mode=0, status=0, charge_state=0, fault=0, battery=80, current_map_id="7"
    )
    raw_rooms = [
        [1, "Living Room", 0, 0, 1, 2, 0, 0, 0, 0, 0, 0],
        [2, "Kitchen", 0, 1, 2, 2, 0, 0, 1, 0, 0, 0],
    ]
    fake = FakeAdapter(
        props=props,
        rooms=TEST_ROOMS,
        preference_result={"rooms": raw_rooms, "prefer_on": 0},
    )
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    await coordinator.async_set_room_order([2, 1])

    assert len(fake.preferences_set) == 1
    result = coordinator.room_preferences
    assert result[0].room_id == 2
    assert result[1].room_id == 1
    assert result[0].mode == 1  # preserved from raw_rooms
    assert result[1].mode == 0


async def test_set_room_order_synthesises_unknown_room(hass: HomeAssistant) -> None:
    """async_set_room_order synthesises a neutral default for a room not in cached prefs."""
    props = make_props(
        work_mode=0, status=0, charge_state=0, fault=0, battery=80, current_map_id="7"
    )
    fake = FakeAdapter(
        props=props,
        rooms=TEST_ROOMS,
        preference_result={"rooms": [], "prefer_on": 0},
    )
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    coordinator.room_preferences = []

    await coordinator.async_set_room_order([1, 2])

    result = coordinator.room_preferences
    assert len(result) == 2
    assert result[0].room_id == 1
    assert result[1].room_id == 2
    assert result[0].wind == 1  # neutral default


# ---------------------------------------------------------------------------
# default_clean_room_ids
# ---------------------------------------------------------------------------


def _pref(room_id: int, name: str = "", check: int = 0) -> RoomPreference:
    return RoomPreference(
        room_id=room_id,
        room_name=name,
        mode=0,
        wind=1,
        water=2,
        repeat=0,
        check=check,
        carpet_avoidance=0,
    )


async def test_default_clean_room_ids_standard_no_selection(hass: HomeAssistant) -> None:
    """Standard mode with no selection returns preference order, all rooms."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    coordinator.prefer_mode = "standard"
    # Preference order intentionally inverted vs. coordinator.rooms (map order).
    coordinator.room_preferences = [_pref(2, "Bedroom"), _pref(1, "Living Room")]

    assert coordinator.default_clean_room_ids() == [2, 1]


async def test_default_clean_room_ids_standard_with_selection_uses_pref_order(
    hass: HomeAssistant,
) -> None:
    """Standard mode with tapped rooms returns only those, in preference order."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    coordinator.prefer_mode = "standard"
    coordinator.room_preferences = [_pref(2, "Bedroom"), _pref(1, "Living Room")]
    # Tap in id-ascending order; result must still be preference order (2, then 1).
    coordinator.set_selected_room_ids([1, 2])

    assert coordinator.default_clean_room_ids() == [2, 1]


async def test_default_clean_room_ids_standard_filters_to_selection(
    hass: HomeAssistant,
) -> None:
    """Standard mode with one tapped room returns just that room."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    coordinator.prefer_mode = "standard"
    coordinator.room_preferences = [_pref(2, "Bedroom"), _pref(1, "Living Room")]
    coordinator.set_selected_room_ids([1])

    assert coordinator.default_clean_room_ids() == [1]


async def test_default_clean_room_ids_customise_returns_checked_in_pref_order(
    hass: HomeAssistant,
) -> None:
    """Custom mode returns only rooms with check==1, in preference order."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    coordinator.prefer_mode = "customise"
    coordinator.room_preferences = [
        _pref(2, "Bedroom", check=1),
        _pref(1, "Living Room", check=0),
    ]

    assert coordinator.default_clean_room_ids() == [2]


async def test_default_clean_room_ids_customise_ignores_tap_selection(
    hass: HomeAssistant,
) -> None:
    """Custom mode uses the check field, not the map-tap selection set."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    coordinator.prefer_mode = "customise"
    coordinator.room_preferences = [
        _pref(1, "Living Room", check=1),
        _pref(2, "Bedroom", check=0),
    ]
    # A tap-selection from a stale Standard session must not leak into Custom.
    coordinator.set_selected_room_ids([2])

    assert coordinator.default_clean_room_ids() == [1]


async def test_default_clean_room_ids_customise_nothing_checked_raises(
    hass: HomeAssistant,
) -> None:
    """Custom mode with zero checked rooms raises ServiceValidationError."""
    from homeassistant.exceptions import ServiceValidationError

    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    coordinator.prefer_mode = "customise"
    coordinator.room_preferences = [_pref(1, check=0), _pref(2, check=0)]

    with pytest.raises(ServiceValidationError, match="No rooms checked"):
        coordinator.default_clean_room_ids()


async def test_default_clean_room_ids_no_prefs_falls_back_to_map_order(
    hass: HomeAssistant,
) -> None:
    """When preferences are not loaded, fall back to coordinator.rooms order."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    coordinator.room_preferences = []

    assert coordinator.default_clean_room_ids() == [r.room_id for r in TEST_ROOMS]


async def test_default_clean_room_ids_no_prefs_honours_selection(
    hass: HomeAssistant,
) -> None:
    """Fallback path still filters by selection set when one is present."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    coordinator.room_preferences = []
    coordinator.set_selected_room_ids([2])

    assert coordinator.default_clean_room_ids() == [2]
