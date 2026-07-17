# SPDX-License-Identifier: MIT
"""Unit tests for RoomNameWatcher — the pure room-rename state machine.

The repair *wiring* (registry issues, the map-refresh path) is covered by
tests/integration/test_room_names_repair.py. These cover the decision rules
directly: no hass, no coordinator, no I/O.
"""

from __future__ import annotations

import pytest
from custom_components.karcher_home_robots._room_names import RepairAction, RoomNameWatcher
from custom_components.karcher_home_robots.map_data import RoomInfo

CONFIRM_TICKS = 3


@pytest.fixture
def watcher() -> RoomNameWatcher:
    return RoomNameWatcher(CONFIRM_TICKS)


def _rooms(*pairs: tuple[int, str]) -> list[RoomInfo]:
    return [
        RoomInfo(room_id=rid, name=name, color_id=0, label_x=0.0, label_y=0.0)
        for rid, name in pairs
    ]


def _observe(watcher: RoomNameWatcher, rooms: list[RoomInfo], times: int) -> RepairAction:
    """Feed `rooms` `times` times; return the last action."""
    action = RepairAction.NONE
    for _ in range(times):
        action = watcher.observe(rooms)
    return action


# --- seeding ---------------------------------------------------------------


def test_first_read_seeds_baseline_and_clears(watcher: RoomNameWatcher) -> None:
    """The first valid read is the baseline; CLEAR reconciles any stale issue."""
    assert watcher.observe(_rooms((1, "Kitchen"))) is RepairAction.CLEAR
    assert watcher.known_names == {1: "Kitchen"}
    assert watcher.repair_active is False


def test_empty_read_does_not_seed(watcher: RoomNameWatcher) -> None:
    assert watcher.observe([]) is RepairAction.NONE
    assert watcher.known_names == {}


def test_all_blank_read_does_not_seed(watcher: RoomNameWatcher) -> None:
    assert watcher.observe(_rooms((1, ""), (2, ""))) is RepairAction.NONE
    assert watcher.known_names == {}


def test_partially_blank_read_does_seed(watcher: RoomNameWatcher) -> None:
    """Only an *entirely* blank read is discarded — one real name is a valid map."""
    assert watcher.observe(_rooms((1, "Kitchen"), (2, ""))) is RepairAction.CLEAR
    assert watcher.known_names == {1: "Kitchen", 2: ""}


# --- debounce --------------------------------------------------------------


def test_change_fires_only_after_confirm_ticks(watcher: RoomNameWatcher) -> None:
    watcher.observe(_rooms((1, "Kitchen")))
    changed = _rooms((1, "Cucina"))

    for _ in range(CONFIRM_TICKS - 1):
        assert watcher.observe(changed) is RepairAction.NONE
    assert watcher.observe(changed) is RepairAction.CREATE
    assert watcher.repair_active is True


def test_flapping_names_never_confirm(watcher: RoomNameWatcher) -> None:
    """A candidate that keeps changing restarts the count and never fires."""
    watcher.observe(_rooms((1, "Kitchen")))

    for i in range(CONFIRM_TICKS * 3):
        assert watcher.observe(_rooms((1, f"Name{i}"))) is RepairAction.NONE
    assert watcher.repair_active is False


def test_confirmed_change_does_not_refire(watcher: RoomNameWatcher) -> None:
    watcher.observe(_rooms((1, "Kitchen")))
    _observe(watcher, _rooms((1, "Cucina")), CONFIRM_TICKS)  # CREATE

    assert _observe(watcher, _rooms((1, "Cucina")), 5) is RepairAction.NONE


def test_blank_read_mid_debounce_does_not_reset_count(watcher: RoomNameWatcher) -> None:
    """Blank reads are skipped outright — they neither advance nor reset the debounce."""
    watcher.observe(_rooms((1, "Kitchen")))
    changed = _rooms((1, "Cucina"))

    _observe(watcher, changed, CONFIRM_TICKS - 1)
    assert watcher.observe([]) is RepairAction.NONE  # ignored
    assert watcher.observe(changed) is RepairAction.CREATE


# --- revert ----------------------------------------------------------------


def test_revert_to_baseline_clears(watcher: RoomNameWatcher) -> None:
    watcher.observe(_rooms((1, "Kitchen")))
    _observe(watcher, _rooms((1, "Cucina")), CONFIRM_TICKS)

    assert watcher.observe(_rooms((1, "Kitchen"))) is RepairAction.CLEAR
    assert watcher.repair_active is False


def test_revert_resets_the_debounce(watcher: RoomNameWatcher) -> None:
    """After a revert the next change starts a fresh count, not a resumed one."""
    watcher.observe(_rooms((1, "Kitchen")))
    _observe(watcher, _rooms((1, "Cucina")), CONFIRM_TICKS)
    watcher.observe(_rooms((1, "Kitchen")))  # revert → CLEAR

    assert watcher.observe(_rooms((1, "Cucina"))) is RepairAction.NONE


def test_baseline_match_without_repair_is_quiet(watcher: RoomNameWatcher) -> None:
    """Steady state: matching reads with nothing raised produce no action."""
    watcher.observe(_rooms((1, "Kitchen")))

    assert _observe(watcher, _rooms((1, "Kitchen")), 5) is RepairAction.NONE


# --- reset (map switch) ----------------------------------------------------


def test_reset_drops_baseline_and_clears_raised_repair(watcher: RoomNameWatcher) -> None:
    watcher.observe(_rooms((1, "Kitchen")))
    _observe(watcher, _rooms((1, "Cucina")), CONFIRM_TICKS)

    assert watcher.reset() is RepairAction.CLEAR
    assert watcher.known_names == {}
    assert watcher.repair_active is False


def test_reset_without_raised_repair_is_quiet(watcher: RoomNameWatcher) -> None:
    watcher.observe(_rooms((1, "Kitchen")))

    assert watcher.reset() is RepairAction.NONE
    assert watcher.known_names == {}


def test_reset_makes_next_read_a_fresh_seed(watcher: RoomNameWatcher) -> None:
    """After a map switch the new map's names are the reference, not a rename."""
    watcher.observe(_rooms((1, "Kitchen")))
    _observe(watcher, _rooms((1, "Cucina")), CONFIRM_TICKS)
    watcher.reset()

    assert watcher.observe(_rooms((1, "Cucina"))) is RepairAction.CLEAR  # seed, not fire
    assert _observe(watcher, _rooms((1, "Cucina")), CONFIRM_TICKS) is RepairAction.NONE


# --- encapsulation ---------------------------------------------------------


def test_known_names_is_a_copy(watcher: RoomNameWatcher) -> None:
    """Callers cannot mutate the baseline through the accessor."""
    watcher.observe(_rooms((1, "Kitchen")))

    watcher.known_names[1] = "Tampered"

    assert watcher.known_names == {1: "Kitchen"}
