# SPDX-License-Identifier: MIT
"""Tests for room-names-changed repair issue lifecycle."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.karcher_home_robots.adapter import Room
from custom_components.karcher_home_robots.const import DOMAIN
from custom_components.karcher_home_robots.coordinator import KarcherCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from tests.conftest import TEST_DEVICE, make_entry, make_props


def _make_coord(hass: HomeAssistant) -> KarcherCoordinator:
    adapter = MagicMock()
    entry = make_entry()
    entry.add_to_hass(hass)
    return KarcherCoordinator(hass, adapter, TEST_DEVICE, config_entry=entry)


def _rooms(*pairs: tuple[int, str]) -> list[Room]:
    return [Room(room_id=rid, name=name) for rid, name in pairs]


# ---------------------------------------------------------------------------
# _check_room_names_changed
# ---------------------------------------------------------------------------


async def test_names_changed_creates_repair_issue(hass: HomeAssistant) -> None:
    """Repair issue created when room names differ from the known baseline."""
    coord = _make_coord(hass)
    entry_id = coord.config_entry.entry_id  # type: ignore[union-attr]
    issue_id = f"room_names_changed_{entry_id}"

    coord._check_room_names_changed(_rooms((1, "Kitchen"), (2, "Hall")))
    coord._check_room_names_changed(_rooms((1, "Cucina"), (2, "Hall")))

    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert coord._room_names_changed_repair is True


async def test_names_reverted_dismisses_repair_issue(hass: HomeAssistant) -> None:
    """Repair issue dismissed when names revert to match the known baseline."""
    coord = _make_coord(hass)
    entry_id = coord.config_entry.entry_id  # type: ignore[union-attr]
    issue_id = f"room_names_changed_{entry_id}"

    # Establish baseline, then trigger mismatch, then revert.
    coord._check_room_names_changed(_rooms((1, "Kitchen")))
    coord._check_room_names_changed(_rooms((1, "Cucina")))
    assert coord._room_names_changed_repair is True

    coord._check_room_names_changed(_rooms((1, "Cucina")))

    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is None
    assert coord._room_names_changed_repair is False


async def test_names_changed_again_while_repair_active_no_duplicate(
    hass: HomeAssistant,
) -> None:
    """A second name change while the repair is already active does not duplicate it."""
    coord = _make_coord(hass)
    entry_id = coord.config_entry.entry_id  # type: ignore[union-attr]
    issue_id = f"room_names_changed_{entry_id}"

    coord._check_room_names_changed(_rooms((1, "Kitchen")))
    coord._check_room_names_changed(_rooms((1, "Cucina")))
    assert coord._room_names_changed_repair is True

    coord._check_room_names_changed(_rooms((1, "Cuisine")))

    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert coord._room_names_changed_repair is True


async def test_names_match_no_repair_no_side_effect(hass: HomeAssistant) -> None:
    """No repair issue created or deleted when names match and flag is already False."""
    coord = _make_coord(hass)
    entry_id = coord.config_entry.entry_id  # type: ignore[union-attr]
    issue_id = f"room_names_changed_{entry_id}"

    coord._check_room_names_changed(_rooms((1, "Kitchen")))
    coord._check_room_names_changed(_rooms((1, "Kitchen")))

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert coord._room_names_changed_repair is False


# ---------------------------------------------------------------------------
# Map-change path: repair dismissed on map switch
# ---------------------------------------------------------------------------


async def test_map_change_dismisses_repair_when_flag_set(hass: HomeAssistant) -> None:
    """Switching maps clears a pending room-names-changed repair issue."""
    coord = _make_coord(hass)
    entry_id = coord.config_entry.entry_id  # type: ignore[union-attr]
    issue_id = f"room_names_changed_{entry_id}"

    # Pre-arm: simulate a repair already raised.
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
