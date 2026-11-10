# SPDX-License-Identifier: MIT
"""One clean's drawn path on a robot whose pushes drop points (the RVM 4 Comfort).

Pure — no HA, no I/O. It follows what both Kärcher apps do: the map's history is the
base, and pushed points numbered above the history's last pose ID are drawn on top.
No per-point IDs are kept for the history: counted back from its last ID they drift
by a point or two over a clean, so only the newest entries can be given an ID.

A clean that has just started is "gated": the history still holds the previous
clean's path (or has just been reset to the docked pose). Nothing of it is drawn
until it proves fresh — it falls (a new numbering), shrinks to the docked pose, or
grows past what the first snapshot showed.
"""

from __future__ import annotations

PathPoint = tuple[float, float, float, int]

# A history shorter than half the one before it is a new record, not the robot
# trimming a few points mid-clean.
_NEW_RECORD_RATIO = 2


class CleanPath:
    """The history base, the pushed tail above it, and the room-tracking watermark."""

    def __init__(self) -> None:
        self._gated = False
        self._stale_ref: tuple[int, int | None] | None = None
        self._reset()

    def _reset(self) -> None:
        self._history: list[PathPoint] = []
        self._tail: list[tuple[int, PathPoint]] = []
        self._last_id: int | None = None
        self._seen_len: int | None = None
        self._push_top: int | None = None
        self._observed_id: int | None = None

    @property
    def points(self) -> list[PathPoint]:
        """The path to draw: the history, then the pushes numbered above it."""
        return [*self._history, *(point for _i, point in self._tail)]

    @property
    def push_pose_id(self) -> int | None:
        """The newest pushed pose ID, for comparing with the snapshot's robot pose."""
        return self._push_top

    def summary(self) -> str:
        """One line for the DEBUG snapshot log."""
        return (
            f"gated={self._gated} history_id={self._last_id} seen_len={self._seen_len} "
            f"tail={len(self._tail)} push_top={self._push_top} observed_id={self._observed_id}"
        )

    def start(self) -> None:
        """A clean (or a new map) begins: draw nothing until the history proves fresh."""
        self._reset()
        self._gated = True
        self._stale_ref = None

    def on_history(
        self, xy: list[tuple[float, float]], flags: list[int], last_id: int | None
    ) -> list[tuple[float, float]]:
        """Take a snapshot's history as the base; return its new cleaning points.

        The returned points are the ones room tracking has not seen: appended since
        the previous snapshot and not already fed from a push.
        """
        if len(flags) != len(xy):
            flags = [1] * len(xy)
        if self._gated:
            first_new = self._gate_release(len(xy), last_id)
            if first_new is None:
                return []
        else:
            first_new = self._first_new(len(xy), last_id)
        return self._adopt(xy, flags, last_id, first_new)

    def on_push(
        self, start_id: int | None, points: list[PathPoint]
    ) -> tuple[list[PathPoint], list[PathPoint], bool]:
        """Take a path push; return (points to draw, points for room tracking, rewrote).

        Points numbered at or below what the path already holds are not drawn again.
        A push that starts below the newest pushed ID began a new numbering, so the
        tail above the history goes, and `rewrote` tells the caller that the drawn path
        must be replaced by `points` instead of appended to. A push without a start ID
        is drawn as it comes.
        """
        if start_id is None:
            return points, points, False
        numbered = list(enumerate(points, start_id))
        if not numbered:
            return [], [], False
        rewrote = self._push_top is not None and start_id < self._push_top
        if rewrote:
            self._tail = []
            self._observed_id = None
        floor = max(
            (
                i
                for i in (self._last_id, self._tail[-1][0] if self._tail else None)
                if i is not None
            ),
            default=None,
        )
        draw = [(i, p) for i, p in numbered if floor is None or i > floor]
        self._tail.extend(draw)
        self._push_top = numbered[-1][0]
        observed = self._observed_id
        tracked = [(i, p) for i, p in numbered if observed is None or i > observed]
        cleaning = [i for i, p in tracked if p[3] != 0]
        if cleaning:
            self._observed_id = cleaning[-1]
        return [p for _i, p in draw], [p for _i, p in tracked], rewrote

    def _gate_release(self, n: int, last_id: int | None) -> int | None:
        """Where this snapshot's new points begin, or None while the gate holds."""
        if n <= 1:
            first_new = n
        elif self._stale_ref is None:
            self._stale_ref = (n, last_id)
            return None
        else:
            ref_n, ref_id = self._stale_ref
            if self._fell(n, last_id, ref_n, ref_id):
                first_new = 0
            elif n > ref_n:
                first_new = ref_n
            else:
                return None
        self._gated = False
        self._stale_ref = None
        return first_new

    def _first_new(self, n: int, last_id: int | None) -> int:
        seen = self._seen_len
        if seen is None:
            return n
        if self._fell(n, last_id, seen, self._last_id):
            self._tail = []
            self._push_top = None
            self._observed_id = None
            return 0
        return seen if n > seen else n

    @staticmethod
    def _fell(n: int, last_id: int | None, ref_n: int, ref_id: int | None) -> bool:
        """The history started a new numbering: its ID fell, or it is far shorter."""
        id_fell = last_id is not None and ref_id is not None and last_id < ref_id
        return id_fell or n < ref_n // _NEW_RECORD_RATIO

    def _adopt(
        self, xy: list[tuple[float, float]], flags: list[int], last_id: int | None, first_new: int
    ) -> list[tuple[float, float]]:
        n = len(xy)
        fresh: list[tuple[float, float]] = []
        newest_id: int | None = None
        for i in range(first_new, n):
            if not flags[i]:
                continue
            entry_id = None if last_id is None else last_id - (n - 1 - i)
            seen = self._observed_id
            if entry_id is not None and seen is not None and entry_id <= seen:
                continue
            fresh.append(xy[i])
            newest_id = entry_id
        if fresh and newest_id is not None:
            self._observed_id = newest_id
        self._history = [(x, y, 0.0, flag) for (x, y), flag in zip(xy, flags, strict=True)]
        self._last_id = last_id
        self._seen_len = n
        self._tail = [(i, p) for i, p in self._tail if last_id is not None and i > last_id]
        return fresh
