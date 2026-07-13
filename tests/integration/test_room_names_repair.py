# SPDX-License-Identifier: MIT
"""Tests for room-names-changed repair issue lifecycle."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.karcher_home_robots.const import DOMAIN
from custom_components.karcher_home_robots.coordinator import (
    _ROOM_NAMES_CONFIRM_TICKS,
    KarcherCoordinator,
)
from custom_components.karcher_home_robots.map_data import RoomInfo
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from tests.conftest import TEST_DEVICE, make_entry, make_props


def _make_coord(hass: HomeAssistant) -> KarcherCoordinator:
    adapter = MagicMock()
    entry = make_entry()
    entry.add_to_hass(hass)
    return KarcherCoordinator(hass, adapter, TEST_DEVICE, config_entry=entry)


def _rooms(*pairs: tuple[int, str]) -> list[RoomInfo]:
    return [
        RoomInfo(room_id=rid, name=name, color_id=0, label_x=0.0, label_y=0.0)
        for rid, name in pairs
    ]


def _issue_id(coord: KarcherCoordinator) -> str:
    entry_id = coord.config_entry.entry_id  # type: ignore[union-attr]
    return f"room_names_changed_{entry_id}"


def _feed(coord: KarcherCoordinator, rooms: list[RoomInfo], times: int) -> None:
    for _ in range(times):
        coord._check_room_names(rooms)


# ---------------------------------------------------------------------------
# _check_room_names — firing (debounced)
# ---------------------------------------------------------------------------


async def test_confirmed_change_creates_repair(hass: HomeAssistant) -> None:
    """A differing name set that persists CONFIRM_TICKS refreshes fires the repair."""
    coord = _make_coord(hass)

    coord._check_room_names(_rooms((1, "Kitchen"), (2, "Hall")))  # seed baseline
    _feed(coord, _rooms((1, "Cucina"), (2, "Hall")), _ROOM_NAMES_CONFIRM_TICKS)

    assert ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(coord)) is not None
    assert coord._room_names_changed_repair is True


async def test_transient_change_below_threshold_no_repair(hass: HomeAssistant) -> None:
    """A brief blip that reverts before CONFIRM_TICKS never fires the repair."""
    coord = _make_coord(hass)

    coord._check_room_names(_rooms((1, "Kitchen")))  # seed baseline
    _feed(coord, _rooms((1, "Cucina")), _ROOM_NAMES_CONFIRM_TICKS - 1)
    coord._check_room_names(_rooms((1, "Kitchen")))  # recovered

    assert ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(coord)) is None
    assert coord._room_names_changed_repair is False


async def test_empty_rooms_ignored(hass: HomeAssistant) -> None:
    """Snapshots with no rooms (map transiently gone) don't touch the baseline."""
    coord = _make_coord(hass)

    coord._check_room_names(_rooms((1, "Kitchen")))  # seed baseline
    _feed(coord, [], _ROOM_NAMES_CONFIRM_TICKS + 2)

    assert ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(coord)) is None
    assert coord._known_room_names == {1: "Kitchen"}


async def test_all_blank_names_ignored(hass: HomeAssistant) -> None:
    """A relocalization read where every name is blank is ignored, not a change."""
    coord = _make_coord(hass)

    coord._check_room_names(_rooms((1, "Kitchen"), (2, "Hall")))  # seed baseline
    _feed(coord, _rooms((1, ""), (2, "")), _ROOM_NAMES_CONFIRM_TICKS + 2)

    assert ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(coord)) is None
    assert coord._known_room_names == {1: "Kitchen", 2: "Hall"}


# ---------------------------------------------------------------------------
# _check_room_names — clearing on revert (the relocalization-recovery bug)
# ---------------------------------------------------------------------------


async def test_revert_to_baseline_dismisses_repair(hass: HomeAssistant) -> None:
    """Once fired, the repair clears when names return to the baseline."""
    coord = _make_coord(hass)

    coord._check_room_names(_rooms((1, "Kitchen")))  # seed baseline
    _feed(coord, _rooms((1, "Cucina")), _ROOM_NAMES_CONFIRM_TICKS)
    assert coord._room_names_changed_repair is True

    coord._check_room_names(_rooms((1, "Kitchen")))  # recovered

    assert ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(coord)) is None
    assert coord._room_names_changed_repair is False
    assert coord._room_names_candidate is None
    assert coord._room_names_candidate_ticks == 0


async def test_persisting_change_no_duplicate(hass: HomeAssistant) -> None:
    """The changed set persisting past the threshold does not re-create the issue."""
    coord = _make_coord(hass)

    coord._check_room_names(_rooms((1, "Kitchen")))  # seed baseline
    _feed(coord, _rooms((1, "Cucina")), _ROOM_NAMES_CONFIRM_TICKS + 3)

    assert ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(coord)) is not None
    assert coord._room_names_changed_repair is True


async def test_stale_issue_reconciled_on_first_seed(hass: HomeAssistant) -> None:
    """A pre-existing issue (flag False, e.g. left by an older version) clears on
    the first valid baseline seed, without waiting for a full HA restart."""
    coord = _make_coord(hass)
    issue_id = _issue_id(coord)

    # Simulate a leftover issue in the registry with no in-memory flag set —
    # exactly what an older code path or a prior session leaves behind.
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="room_names_changed",
    )
    assert coord._room_names_changed_repair is False

    coord._check_room_names(_rooms((1, "Kitchen")))  # first valid seed

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_names_match_no_side_effect(hass: HomeAssistant) -> None:
    """No repair created when names keep matching the baseline."""
    coord = _make_coord(hass)

    coord._check_room_names(_rooms((1, "Kitchen")))  # seed baseline
    _feed(coord, _rooms((1, "Kitchen")), 3)

    assert ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(coord)) is None
    assert coord._room_names_changed_repair is False


# ---------------------------------------------------------------------------
# Map-change path: repair dismissed and baseline reset on map switch
# ---------------------------------------------------------------------------


async def test_map_change_dismisses_repair_and_resets_baseline(hass: HomeAssistant) -> None:
    """Switching maps clears a pending repair and drops the name baseline."""
    coord = _make_coord(hass)
    issue_id = _issue_id(coord)

    # Pre-arm: simulate a repair already raised with a live baseline/candidate.
    coord._known_room_names = {1: "Kitchen"}
    coord._room_names_candidate = {1: "Cucina"}
    coord._room_names_candidate_ticks = _ROOM_NAMES_CONFIRM_TICKS
    coord._room_names_changed_repair = True
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="room_names_changed",
    )

    coord._current_map_id = "map-A"
    await coord._maybe_refresh_rooms(make_props(current_map_id="map-B"))

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert coord._room_names_changed_repair is False
    assert coord._known_room_names == {}
    assert coord._room_names_candidate is None
    assert coord._room_names_candidate_ticks == 0
