# SPDX-License-Identifier: MIT
"""Unit tests for PathProjection — the traced path and its pixel projection.

No hass, no coordinator: the caller supplies the snapshot, the layout, and the
policy knobs, so the rules can be hit at their exact boundaries. The wiring that
drives this object (clean start, dock, map change, refresh) is covered through the
coordinator's public surface in tests/integration/test_map_coordinator.py.
"""

from __future__ import annotations

from custom_components.karcher_home_robots._path import PathProjection
from custom_components.karcher_home_robots.map_data import MapGrid, MapSnapshot
from custom_components.karcher_home_robots.map_render import RenderLayout, world_to_pixel

_GRID = MapGrid(width=60, height=60, data=bytes(3600), resolution=0.05, min_x=0.0, min_y=0.0)
_SNAPSHOT = MapSnapshot(grid=_GRID, robot=None, charger=None)
_LAYOUT = RenderLayout(col0=0, row0=0, crop_w=60, crop_h=60, scale=2, out_w=120, out_h=120)


def _px(wx: float, wy: float, layout: RenderLayout = _LAYOUT) -> list[int]:
    x, y = world_to_pixel(
        wx, wy, layout, _GRID.width, _GRID.height, _GRID.resolution, _GRID.min_x, _GRID.min_y
    )
    return [x, y]


def _pts(n: int) -> list[tuple[float, float, float, int]]:
    return [(0.01 * i, 0.01 * i, 0.0, 1) for i in range(n)]


# ---------------------------------------------------------------------------
# the raw buffer
# ---------------------------------------------------------------------------


def test_extend_appends_points() -> None:
    p = PathProjection()
    p.extend(_pts(3))
    p.extend([(9.0, 9.0, 0.0, 1)])

    assert p.points == [*_pts(3), (9.0, 9.0, 0.0, 1)]


def test_points_returns_a_copy_callers_cannot_mutate_the_path() -> None:
    p = PathProjection()
    p.extend(_pts(2))

    p.points.append((99.0, 99.0, 0.0, 1))

    assert len(p.points) == 2


def test_clear_empties_the_path() -> None:
    p = PathProjection()
    p.extend(_pts(5))
    p.clear()

    assert p.points == []


# ---------------------------------------------------------------------------
# the one-shot history seed
# ---------------------------------------------------------------------------


def test_seed_restores_the_path_after_a_restart() -> None:
    p = PathProjection()
    p.seed_from_history([(1.0, 2.0), (3.0, 4.0)])

    # History carries no per-point flag; seeded points count as cleaning.
    assert p.points == [(1.0, 2.0, 0.0, 1), (3.0, 4.0, 0.0, 1)]


def test_seed_does_not_overwrite_a_live_path() -> None:
    p = PathProjection()
    p.extend([(9.0, 9.0, 0.5, 1)])
    p.seed_from_history([(1.0, 2.0), (3.0, 4.0)])

    assert p.points == [(9.0, 9.0, 0.5, 1)]


def test_seed_is_spent_by_the_first_call() -> None:
    p = PathProjection()
    p.seed_from_history([(1.0, 2.0)])
    p.clear()
    p.seed_from_history([(1.0, 2.0)])

    assert p.points == []


def test_seed_is_spent_even_when_there_was_nothing_to_seed() -> None:
    """A first refresh that finds no history must still disarm the seed."""
    p = PathProjection()
    p.seed_from_history([])
    p.seed_from_history([(1.0, 2.0)])

    assert p.points == []


def test_clear_spends_the_seed() -> None:
    """Clean start clears the path; the robot's history still holds the old clean."""
    p = PathProjection()
    p.clear()
    p.seed_from_history([(1.0, 2.0)])

    assert p.points == []


# ---------------------------------------------------------------------------
# projection
# ---------------------------------------------------------------------------


def test_project_without_a_map_yields_no_pixels() -> None:
    p = PathProjection()
    p.extend(_pts(4))

    p.project(None, _LAYOUT)
    assert p.pixels == []

    p.project(_SNAPSHOT, None)
    assert p.pixels == []


def test_project_decimates_by_step_and_forces_the_tip() -> None:
    p = PathProjection(step=3)
    raw = _pts(5)  # keeps 0 and 3; index 4 is the tip, (5-1) % 3 != 0 → appended
    p.extend(raw)
    p.project(_SNAPSHOT, _LAYOUT)

    assert p.pixels == [*_px(*raw[0][:2]), *_px(*raw[3][:2]), *_px(*raw[4][:2])]


def test_project_does_not_double_a_step_aligned_tip() -> None:
    p = PathProjection(step=3)
    raw = _pts(7)  # keeps 0, 3, 6; the tip IS index 6, (7-1) % 3 == 0 → not re-appended
    p.extend(raw)
    p.project(_SNAPSHOT, _LAYOUT)

    assert p.pixels == [*_px(*raw[0][:2]), *_px(*raw[3][:2]), *_px(*raw[6][:2])]


def test_incremental_projection_matches_a_single_full_projection() -> None:
    """The cache is an optimisation: growing a path in batches must not change output."""
    raw = _pts(23)

    incr = PathProjection()
    for batch in (raw[0:1], raw[1:5], raw[5:6], raw[6:20], raw[20:23]):
        incr.extend(list(batch))
        incr.project(_SNAPSHOT, _LAYOUT)

    full = PathProjection()
    full.extend(list(raw))
    full.project(_SNAPSHOT, _LAYOUT)

    assert incr.pixels == full.pixels


def test_layout_shift_reprojects_the_whole_path() -> None:
    """A grown map hands over a new layout object; cached pixels are in the old frame."""
    p = PathProjection()
    p.extend(_pts(9))  # step-aligned: _proj_idx lands on len, so only the layout check fires
    p.project(_SNAPSHOT, _LAYOUT)

    shifted = RenderLayout(col0=5, row0=3, crop_w=60, crop_h=60, scale=3, out_w=180, out_h=180)
    p.project(_SNAPSHOT, shifted)

    fresh = PathProjection()
    fresh.extend(_pts(9))
    fresh.project(_SNAPSHOT, shifted)
    assert p.pixels == fresh.pixels


def test_shrunk_path_reprojects_instead_of_reusing_a_stale_offset() -> None:
    p = PathProjection()
    p.extend(_pts(10))
    p.project(_SNAPSHOT, _LAYOUT)

    p.clear()
    p.extend(_pts(2))
    p.project(_SNAPSHOT, _LAYOUT)

    fresh = PathProjection()
    fresh.extend(_pts(2))
    fresh.project(_SNAPSHOT, _LAYOUT)
    assert p.pixels == fresh.pixels


# ---------------------------------------------------------------------------
# the raw-buffer cap
# ---------------------------------------------------------------------------


def test_trim_caps_the_raw_buffer() -> None:
    """The buffer settles near the cap instead of growing with session length.

    It sits slightly above it by construction, not by accident: the trim runs before
    the extend (so the newest batch is always still there), and the drop is rounded
    down to a whole stride (so up to step-1 points survive each pass).
    """
    p = PathProjection(step=3, max_raw=30)
    for start in range(0, 300, 10):
        p.extend(_pts(300)[start : start + 10])
        p.project(_SNAPSHOT, _LAYOUT)

    assert len(p.points) <= 30 + 10 + 3  # cap + one batch + stride rounding
    assert len(p.points) < 300  # actually bounded, not left to grow unchecked
    assert p.points  # the recent tail is kept, not emptied outright


def test_trim_does_not_change_the_published_projection() -> None:
    """The cap is a memory optimisation on already-projected history, nothing more."""
    capped = PathProjection(step=3, max_raw=30)
    uncapped = PathProjection(step=3, max_raw=10_000_000)
    for p in (capped, uncapped):
        for start in range(0, 300, 10):
            p.extend(_pts(300)[start : start + 10])
            p.project(_SNAPSHOT, _LAYOUT)

    assert len(capped.points) < len(uncapped.points)  # the cap really bound...
    assert capped.pixels == uncapped.pixels  # ...yet the output is identical


def test_trim_never_drops_unprojected_points() -> None:
    """Before the first map arrives nothing is projected, so nothing may be dropped."""
    capped = PathProjection(step=3, max_raw=30)
    uncapped = PathProjection(step=3, max_raw=10_000_000)
    for p in (capped, uncapped):
        for start in range(0, 200, 10):
            p.extend(_pts(200)[start : start + 10])  # no project() — no map yet

    assert len(capped.points) == 200
    capped.project(_SNAPSHOT, _LAYOUT)
    uncapped.project(_SNAPSHOT, _LAYOUT)
    assert capped.pixels == uncapped.pixels


def test_trim_keeps_the_buffer_step_aligned() -> None:
    """A ragged drop would desync the tip-append parity from the untrimmed sequence."""
    capped = PathProjection(step=3, max_raw=20)
    uncapped = PathProjection(step=3, max_raw=10_000_000)
    for p in (capped, uncapped):
        for start in range(0, 100, 7):  # batch 7: drops land off a step boundary
            p.extend(_pts(100)[start : start + 7])
            p.project(_SNAPSHOT, _LAYOUT)

    assert capped.pixels == uncapped.pixels
