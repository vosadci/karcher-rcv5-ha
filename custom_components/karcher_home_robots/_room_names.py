# SPDX-License-Identifier: MIT
"""Debounced room-name-change detection.

Pure state machine — no HA, no I/O. `observe()` and `reset()` fold map-snapshot
room names into the baseline and return the `RepairAction` the caller should
apply, so the repair-issue I/O stays with the coordinator.
"""

from __future__ import annotations

import logging
from enum import Enum

from .map_data import RoomInfo

_LOGGER = logging.getLogger(__name__)


class RepairAction(Enum):
    """What the caller should do with the room-names repair issue."""

    NONE = "none"
    CREATE = "create"
    CLEAR = "clear"


class RoomNameWatcher:
    """Tracks the room names the robot reports and decides when they really changed.

    The robot re-reports names on every map refresh. A relocalization blip can
    briefly report inconsistent — or blank — names before the map settles, so a
    differing set must persist `confirm_ticks` consecutive observations before it
    counts as a rename. The repair clears again when names revert to the baseline.

    Owning these four fields together is the point: the baseline, the pending
    candidate, its tick count, and the raised flag are only meaningful in
    combination, and every transition between them lives in this one class.
    """

    def __init__(self, confirm_ticks: int) -> None:
        self._confirm_ticks = confirm_ticks
        self._known: dict[int, str] = {}
        self._candidate: dict[int, str] | None = None
        self._candidate_ticks = 0
        self._repair_active = False

    @property
    def known_names(self) -> dict[int, str]:
        """The baseline the robot has stably reported; empty until the first seed."""
        return dict(self._known)

    @property
    def repair_active(self) -> bool:
        """True when a confirmed change is currently raised as a repair."""
        return self._repair_active

    def observe(self, rooms: list[RoomInfo]) -> RepairAction:
        """Fold one map snapshot's room names into the baseline."""
        current = {r.room_id: r.name for r in rooms}
        if not current or not any(current.values()):
            # No rooms, or every name blank — map transiently unavailable.
            return RepairAction.NONE
        if not self._known:
            return self._seed(current)
        if current == self._known:
            return self._match_baseline()
        return self._track_change(current)

    def reset(self) -> RepairAction:
        """Drop the baseline and any pending candidate, clearing a raised repair.

        Called on a map switch: new segmentation is not a rename, so the new map's
        names become the reference point at the next `observe()`.
        """
        self._known = {}
        self._candidate = None
        self._candidate_ticks = 0
        return self._lower_repair()

    def _seed(self, current: dict[int, str]) -> RepairAction:
        """Adopt the first valid read as the baseline; nothing is pending yet."""
        self._known = current
        self._repair_active = False
        # CLEAR unconditionally: a non-persistent issue from an earlier session or
        # integration version can still sit in the registry while this watcher's
        # flag starts False, and nothing else would drop it (a config-entry reload
        # does not; only a full HA restart would). Deleting an absent issue is a
        # no-op, so this is safe when there is nothing stale.
        return RepairAction.CLEAR

    def _match_baseline(self) -> RepairAction:
        """Names are back to the baseline — drop the candidate, clear any repair."""
        self._candidate = None
        self._candidate_ticks = 0
        return self._lower_repair()

    def _track_change(self, current: dict[int, str]) -> RepairAction:
        """Names differ from the baseline: advance the debounce, fire once confirmed."""
        if current == self._candidate:
            self._candidate_ticks += 1
        else:
            self._candidate = current
            self._candidate_ticks = 1
        if self._candidate_ticks < self._confirm_ticks or self._repair_active:
            return RepairAction.NONE
        _LOGGER.debug("Room names changed from %s to %s", self._known, current)
        self._repair_active = True
        return RepairAction.CREATE

    def _lower_repair(self) -> RepairAction:
        """Clear a raised repair, or do nothing when none is raised."""
        if not self._repair_active:
            return RepairAction.NONE
        self._repair_active = False
        return RepairAction.CLEAR
