# SPDX-License-Identifier: MIT
"""The robot's traced path: raw world points, and their projection to image pixels.

Pure — no HA, no I/O. The caller supplies the map snapshot and render layout, which
is what keeps this module testable without a coordinator.
"""

from __future__ import annotations

from .map_data import MapSnapshot
from .map_render import RenderLayout, world_to_pixel

# Emit one path point per this many raw points when projecting to pixels — limits
# the published attribute size while preserving path shape at the card's display
# resolution.
_CUR_PATH_STEP = 3

# Defensive cap on retained raw points. Unbounded, this is O(session length); a very
# long or stuck-cleaning session should not grow memory without limit. Generous
# relative to any realistic single session, so trimming is rare in practice.
_CUR_PATH_MAX_RAW = 20_000


class PathProjection:
    """Owns the traced path and the incremental cache that projects it to pixels.

    Six pieces of state that are only meaningful together: the raw points, the
    one-shot history seed, the published pixels, the decimated cache behind them,
    how far that cache has consumed the raw buffer, and the layout it was built
    against. Every rule relating them lives here.

    The projection is grown incrementally — a path push costs O(new points), not
    O(whole path), which over a long clean is the difference between a cheap
    append and an O(n²) load on the event loop. Full reprojection happens only
    when the layout object changes or the raw buffer shrinks.
    """

    def __init__(self, *, step: int = _CUR_PATH_STEP, max_raw: int = _CUR_PATH_MAX_RAW) -> None:
        self._step = step
        self._max_raw = max_raw
        self._raw: list[tuple[float, float, float, int]] = []
        # Consumed on first use and force-cleared on clean start and map change, so a
        # stale previous-clean path can never be seeded into a live clean.
        self._seed_pending = True
        self.pixels: list[int] = []  # flat [x0, y0, x1, y1, ...]
        self._px_base: list[int] = []
        self._proj_idx = 0
        self._proj_layout: RenderLayout | None = None

    @property
    def points(self) -> list[tuple[float, float, float, int]]:
        """The raw path as the robot traced it — a copy, so callers cannot mutate it."""
        return list(self._raw)

    def clear(self) -> None:
        """Drop the path and spend the history seed (clean start, map change).

        Spending the seed is the point: the robot still reports the *previous*
        clean's history at clean start, so a later refresh must not restore it.
        """
        self._raw = []
        self._seed_pending = False

    def extend(self, points: list[tuple[float, float, float, int]]) -> None:
        """Append a path push's points, trimming already-projected history first."""
        self._trim()
        self._raw.extend(points)

    def seed_from_history(self, history: list[tuple[float, float]]) -> None:
        """Restore the path from the robot's history once, after an HA restart.

        Spent by the first call whether or not it seeded anything: a first refresh
        that finds no history must still disarm the seed, or it would sit waiting to
        fire at some later empty-path moment. Points are marked as cleaning (flag 1);
        history carries no per-point flag.
        """
        if self._seed_pending and not self._raw and history:
            self._raw = [(x, y, 0.0, 1) for x, y in history]
        self._seed_pending = False

    def project(self, snapshot: MapSnapshot | None, layout: RenderLayout | None) -> None:
        """Recompute `pixels` against the live layout, reusing the cache where valid."""
        if layout is None or snapshot is None or not self._raw:
            self._reset_cache(layout)
            self.pixels = []
            return

        if self._proj_layout is not layout or self._proj_idx > len(self._raw):
            # Layout shifted (the explored map grew) or the path was reset — either
            # way the cache holds pixels from a coordinate system that no longer
            # applies, so it cannot be appended to.
            self._reset_cache(layout)

        grid = snapshot.grid
        while self._proj_idx < len(self._raw):
            wx, wy, _phi, _flag = self._raw[self._proj_idx]
            px, py = world_to_pixel(
                wx,
                wy,
                layout=layout,
                grid_width=grid.width,
                grid_height=grid.height,
                resolution=grid.resolution,
                min_x=grid.min_x,
                min_y=grid.min_y,
            )
            self._px_base.extend([px, py])
            self._proj_idx += self._step

        pixels = list(self._px_base)
        # The base holds indices 0, step, 2*step, …; the true tip is index len-1. It
        # is already in the base iff (len-1) % step == 0, so append it only otherwise.
        if (len(self._raw) - 1) % self._step != 0:
            wx, wy, _phi, _flag = self._raw[-1]
            px, py = world_to_pixel(
                wx,
                wy,
                layout=layout,
                grid_width=grid.width,
                grid_height=grid.height,
                resolution=grid.resolution,
                min_x=grid.min_x,
                min_y=grid.min_y,
            )
            pixels.extend([px, py])
        self.pixels = pixels

    def _reset_cache(self, layout: RenderLayout | None) -> None:
        self._px_base = []
        self._proj_idx = 0
        self._proj_layout = layout

    def _trim(self) -> None:
        """Cap the raw buffer without disturbing the published projection.

        Only points already folded into the decimated base (raw index < _proj_idx)
        may be removed, so the published whole-session projection is never altered —
        the raw buffer shrinks and _proj_idx shifts down by the same amount, leaving
        the next incremental step on the correct (now-shifted) raw index.

        The drop is rounded down to a whole number of strides. _proj_idx is always a
        multiple of step (it only grows by +=step or resets to 0), so a step-aligned
        drop preserves every remaining and future index's residue mod step. project()'s
        tip check, (len(raw)-1) % step, assumes index 0 stays step-aligned to the
        original sequence; a ragged drop would desync that parity and make the tip
        decision diverge from the untrimmed case.
        """
        overflow = len(self._raw) - self._max_raw
        if overflow <= 0:
            return
        drop = (min(overflow, self._proj_idx) // self._step) * self._step
        if drop <= 0:
            return
        del self._raw[:drop]
        self._proj_idx -= drop
