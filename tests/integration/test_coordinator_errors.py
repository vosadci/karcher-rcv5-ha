# SPDX-License-Identifier: MIT
"""Integration tests for coordinator error-taxonomy and flap prevention."""

from __future__ import annotations

import asyncio
import contextlib

import pytest
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
