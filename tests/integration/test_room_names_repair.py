# SPDX-License-Identifier: MIT
"""Tests for room-names-changed repair issue lifecycle.

Assertions go through the issue registry (the user-visible outcome) rather than
the detector's internal flags. "Baseline intact / baseline reset" is likewise
proven by consequence: feed a name set and check whether it debounces into a
repair, which only holds for one of the two baselines.
"""

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


def _raised(coord: KarcherCoordinator) -> bool:
    """True when the room_names_changed repair is currently shown to the user."""
    return ir.async_get(coord.hass).async_get_issue(DOMAIN, _issue_id(coord)) is not None


def _feed(coord: KarcherCoordinator, rooms: list[RoomInfo], times: int) -> None:
    for _ in range(times):
        coord._check_room_names(rooms)


def _confirm_change(coord: KarcherCoordinator, rooms: list[RoomInfo]) -> None:
    """Feed `rooms` enough times to clear the debounce."""
    _feed(coord, rooms, _ROOM_NAMES_CONFIRM_TICKS)


# ---------------------------------------------------------------------------
# _check_room_names — firing (debounced)
# ---------------------------------------------------------------------------


async def test_confirmed_change_creates_repair(hass: HomeAssistant) -> None:
    """A differing name set that persists CONFIRM_TICKS refreshes fires the repair."""
    coord = _make_coord(hass)

    coord._check_room_names(_rooms((1, "Kitchen"), (2, "Hall")))  # seed baseline
    _confirm_change(coord, _rooms((1, "Cucina"), (2, "Hall")))

    assert _raised(coord)


async def test_transient_change_below_threshold_no_repair(hass: HomeAssistant) -> None:
    """A brief blip that reverts before CONFIRM_TICKS never fires the repair."""
    coord = _make_coord(hass)

    coord._check_room_names(_rooms((1, "Kitchen")))  # seed baseline
    _feed(coord, _rooms((1, "Cucina")), _ROOM_NAMES_CONFIRM_TICKS - 1)
    coord._check_room_names(_rooms((1, "Kitchen")))  # recovered

    assert not _raised(coord)


async def test_empty_rooms_ignored(hass: HomeAssistant) -> None:
    """Snapshots with no rooms (map transiently gone) don't touch the baseline."""
    coord = _make_coord(hass)

    coord._check_room_names(_rooms((1, "Kitchen")))  # seed baseline
    _feed(coord, [], _ROOM_NAMES_CONFIRM_TICKS + 2)
    assert not _raised(coord)

    # Baseline is still "Kitchen": a confirmed rename off it still fires. Had the
    # empty reads cleared it, "Cucina" would re-seed silently and never fire.
    _confirm_change(coord, _rooms((1, "Cucina")))
    assert _raised(coord)


async def test_all_blank_names_ignored(hass: HomeAssistant) -> None:
    """A relocalization read where every name is blank is ignored, not a change."""
    coord = _make_coord(hass)

    coord._check_room_names(_rooms((1, "Kitchen"), (2, "Hall")))  # seed baseline
    _feed(coord, _rooms((1, ""), (2, "")), _ROOM_NAMES_CONFIRM_TICKS + 2)
    assert not _raised(coord)

    # Baseline intact — see test_empty_rooms_ignored.
    _confirm_change(coord, _rooms((1, "Cucina"), (2, "Hall")))
    assert _raised(coord)


# ---------------------------------------------------------------------------
# _check_room_names — clearing on revert (the relocalization-recovery bug)
# ---------------------------------------------------------------------------


async def test_revert_to_baseline_dismisses_repair(hass: HomeAssistant) -> None:
    """Once fired, the repair clears when names return to the baseline."""
    coord = _make_coord(hass)

    coord._check_room_names(_rooms((1, "Kitchen")))  # seed baseline
    _confirm_change(coord, _rooms((1, "Cucina")))
    assert _raised(coord)

    coord._check_room_names(_rooms((1, "Kitchen")))  # recovered
    assert not _raised(coord)

    # The debounce counter reset too: a single changed read must not re-fire.
    coord._check_room_names(_rooms((1, "Cucina")))
    assert not _raised(coord)


async def test_persisting_change_no_duplicate(hass: HomeAssistant) -> None:
    """The changed set persisting past the threshold does not re-create the issue."""
    coord = _make_coord(hass)
    coord._create_repair = MagicMock()  # type: ignore[method-assign]

    coord._check_room_names(_rooms((1, "Kitchen")))  # seed baseline
    _feed(coord, _rooms((1, "Cucina")), _ROOM_NAMES_CONFIRM_TICKS + 3)

    coord._create_repair.assert_called_once_with("room_names_changed", persistent=False)


async def test_stale_issue_reconciled_on_first_seed(hass: HomeAssistant) -> None:
    """A pre-existing issue (left by an older version) clears on the first valid
    baseline seed, without waiting for a full HA restart."""
    coord = _make_coord(hass)

    # Simulate a leftover issue in the registry with no in-memory state set —
    # exactly what an older code path or a prior session leaves behind.
    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id(coord),
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="room_names_changed",
    )
    assert _raised(coord)

    coord._check_room_names(_rooms((1, "Kitchen")))  # first valid seed

    assert not _raised(coord)


async def test_names_match_no_side_effect(hass: HomeAssistant) -> None:
    """No repair created when names keep matching the baseline."""
    coord = _make_coord(hass)

    coord._check_room_names(_rooms((1, "Kitchen")))  # seed baseline
    _feed(coord, _rooms((1, "Kitchen")), 3)

    assert not _raised(coord)


# ---------------------------------------------------------------------------
# Map-change path: repair dismissed and baseline reset on map switch
# ---------------------------------------------------------------------------


async def test_map_change_dismisses_repair_and_resets_baseline(hass: HomeAssistant) -> None:
    """Switching maps clears a pending repair and drops the name baseline."""
    coord = _make_coord(hass)

    coord._check_room_names(_rooms((1, "Kitchen")))  # seed baseline
    _confirm_change(coord, _rooms((1, "Cucina")))
    assert _raised(coord)

    coord._current_map_id = "map-A"
    await coord._maybe_refresh_rooms(make_props(current_map_id="map-B"))
    assert not _raised(coord)

    # Baseline was dropped, so the new map's names are simply the new reference:
    # re-feeding "Cucina" re-seeds instead of re-firing.
    _feed(coord, _rooms((1, "Cucina")), _ROOM_NAMES_CONFIRM_TICKS + 1)
    assert not _raised(coord)


async def test_relocalizing_map_id_zero_clears_repair_without_refetch(
    hass: HomeAssistant,
) -> None:
    """current_map_id "0" (transient, while relocalizing) is not a map switch: it
    clears a pending repair and resets the baseline, but does not refetch rooms
    from the no-map state (which would seed a bad baseline)."""
    coord = _make_coord(hass)

    coord._current_map_id = "506"
    coord._check_room_names(_rooms((1, "Kitchen")))  # seed baseline
    _confirm_change(coord, _rooms((1, "Cucina")))
    assert _raised(coord)

    await coord._maybe_refresh_rooms(make_props(current_map_id="0"))

    assert not _raised(coord)
    coord._adapter.get_rooms.assert_not_called()

    # Baseline dropped — see test_map_change_dismisses_repair_and_resets_baseline.
    _feed(coord, _rooms((1, "Cucina")), _ROOM_NAMES_CONFIRM_TICKS + 1)
    assert not _raised(coord)
