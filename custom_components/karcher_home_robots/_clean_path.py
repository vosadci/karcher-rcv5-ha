# SPDX-License-Identifier: MIT
"""One clean's drawn path on a robot whose pushes drop points (the RVM 4 Comfort).

Pure — no HA, no I/O. It follows what both Kärcher apps do: the map's history is the
base, and pushed points numbered above the history's last pose ID are drawn on top.
The history alone also says which points are new cleaning points for room tracking:
it carries every pose with its true flag, which the pushes do not.

At clean start the robot still reports the previous clean's history for a few
seconds. Those snapshots carry no task_begin_date (checked on every RVM 4 clean start
we have logs for), and they are not drawn.
"""

from __future__ import annotations

PathPoint = tuple[float, float, float, int]


class CleanPath:
    """The history base, the pushed tail above it, and the room-tracking watermark."""

    def __init__(self) -> None:
        self.start()

    def start(self) -> None:
        """A clean (or a new map) begins: forget the path and what was fed to the room."""
        self._history: list[PathPoint] = []
        self._tail: list[tuple[int, PathPoint]] = []
        self._last_id: int | None = None
        self._seen_len: int | None = None
        self._push_top: int | None = None

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
            f"history_id={self._last_id} seen_len={self._seen_len} tail={len(self._tail)} "
            f"push_top={self._push_top}"
        )

    def on_history(
        self,
        xy: list[tuple[float, float]],
        flags: list[int],
        last_id: int | None,
        task_begin: int | None,
    ) -> list[tuple[float, float]]:
        """Take a snapshot's history as the base; return its new cleaning points.

        A snapshot without task_begin is not of a running task, so its history is the
        previous clean's and is left alone. The returned points are the ones appended
        since the previous snapshot, for room tracking.
        """
        if task_begin is None:
            return []
        if len(flags) != len(xy):
            flags = [1] * len(xy)
        return self._adopt(xy, flags, last_id, self._first_new(len(xy), last_id))

    def on_push(
        self, start_id: int | None, points: list[PathPoint]
    ) -> tuple[list[PathPoint], bool]:
        """Take a path push; return (points to draw, rewrote).

        Points numbered at or below what the path already holds are not drawn again.
        A push that starts below the newest pushed ID began a new numbering, so the
        tail above the history goes, and `rewrote` tells the caller that the drawn path
        must be replaced by `points` instead of appended to. A push without a start ID
        is drawn as it comes.
        """
        if start_id is None:
            return points, False
        numbered = list(enumerate(points, start_id))
        if not numbered:
            return [], False
        rewrote = self._push_top is not None and start_id < self._push_top
        if rewrote:
            self._tail = []
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
        return [p for _i, p in draw], rewrote

    def _first_new(self, n: int, last_id: int | None) -> int:
        seen = self._seen_len
        if seen is None:
            return n
        if last_id is not None and self._last_id is not None and last_id < self._last_id:
            self._tail = []
            self._push_top = None
            return 0
        return seen if n > seen else n

    def _adopt(
        self, xy: list[tuple[float, float]], flags: list[int], last_id: int | None, first_new: int
    ) -> list[tuple[float, float]]:
        n = len(xy)
        fresh = [xy[i] for i in range(first_new, n) if flags[i]]
        self._history = [(x, y, 0.0, flag) for (x, y), flag in zip(xy, flags, strict=True)]
        self._last_id = last_id
        self._seen_len = n
        self._tail = [(i, p) for i, p in self._tail if last_id is not None and i > last_id]
        return fresh
