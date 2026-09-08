# SPDX-License-Identifier: MIT
"""Property-based tests for PathProjection's incremental-cache invariants.

The example tests next door pin these rules at hand-picked boundaries. What they
cannot do is vary the *alignment*: `_trim`'s correctness argument is about
residues mod `step`, and a fixed schedule (batches of 10, step 3, cap 30) explores
exactly one of them. A cap that lands mid-stride, a batch that straddles the tip,
a layout change arriving between two pushes — those are alignment cases, and the
class's whole reason to exist is that the projection stays correct across them.

Two invariants are asserted, both through the published surface (`pixels`), never
through the cache fields that implement them:

1. Trimming only ever loses the oldest history. A capped projection publishes a
   *suffix* of what an uncapped twin publishes — identical over every surviving
   point, shorter only at the front. This is the real payoff of rounding the drop
   to whole strides; a ragged drop would shift the decimation phase and the two
   would diverge in the middle rather than at the start.
2. Incremental growth equals full reprojection. Feeding points in arbitrary batches,
   with layout changes interleaved, lands on exactly what one fresh projection of
   the whole path under the final layout produces.

Asserting through `pixels` is deliberate: it is what the card consumes, and it keeps
these tests honest if the cache is ever restructured.
"""

from __future__ import annotations

from custom_components.karcher_home_robots._path import PathProjection
from custom_components.karcher_home_robots.map_data import MapGrid, MapSnapshot
from custom_components.karcher_home_robots.map_render import RenderLayout
from hypothesis import given, settings
from hypothesis import strategies as st

_GRID = MapGrid(width=60, height=60, data=bytes(3600), resolution=0.05, min_x=0.0, min_y=0.0)
_SNAPSHOT = MapSnapshot(grid=_GRID, robot=None, charger=None)


def _layout(col0: int = 0, row0: int = 0, scale: int = 2) -> RenderLayout:
    return RenderLayout(
        col0=col0,
        row0=row0,
        crop_w=60,
        crop_h=60,
        scale=scale,
        out_w=60 * scale,
        out_h=60 * scale,
    )


_LAYOUT = _layout()


def _pts(start: int, count: int) -> list[tuple[float, float, float, int]]:
    """A run of distinct path points; coordinates stay inside the grid extent."""
    return [(0.01 * (start + i) % 2.9, 0.01 * (start + i) % 2.9, 0.0, 1) for i in range(count)]


@settings(max_examples=200, deadline=None)
@given(
    batches=st.lists(st.integers(min_value=1, max_value=25), min_size=1, max_size=30),
    step=st.integers(min_value=1, max_value=5),
    cap=st.integers(min_value=5, max_value=60),
)
def test_trimming_only_ever_drops_the_oldest_points(
    batches: list[int], step: int, cap: int
) -> None:
    """A capped path publishes a suffix of what an uncapped twin publishes.

    This is what rounding the drop to whole strides actually guarantees. Every
    surviving point keeps its residue mod step, so the capped projection lands on
    the same decimated indices the uncapped one does and `project()`'s tip check
    stays in phase — the two agree everywhere they overlap and differ only by the
    history the cap deliberately discarded.

    A ragged drop would break that: the phase would shift and the outputs would
    diverge in the *middle*, not just at the front. Only some (cap, batch, step)
    alignments expose it, which is why this is randomised rather than one schedule.
    """
    capped = PathProjection(step=step, max_raw=cap)
    uncapped = PathProjection(step=step, max_raw=10**9)

    total = 0
    for size in batches:
        points = _pts(total, size)
        total += size
        for projection in (capped, uncapped):
            projection.extend(points)
            projection.project(_SNAPSHOT, _LAYOUT)
        suffix_len = len(capped.pixels)
        assert capped.pixels == uncapped.pixels[len(uncapped.pixels) - suffix_len :]
        # Pixels come in (x, y) pairs; a suffix that split a pair would mean the
        # phase had shifted, which is exactly the failure this guards against.
        assert suffix_len % 2 == 0


@settings(max_examples=200, deadline=None)
@given(
    batches=st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=25),
            st.integers(min_value=0, max_value=3),  # col0 of the layout for this push
        ),
        min_size=1,
        max_size=25,
    ),
    step=st.integers(min_value=1, max_value=5),
)
def test_incremental_growth_equals_one_full_reprojection(
    batches: list[tuple[int, int]], step: int
) -> None:
    """Growing the projection push-by-push lands on the same pixels as one pass.

    The cache exists so a path push costs O(new points) rather than O(whole path).
    That optimisation is only sound if it is unobservable, including across the
    layout changes that force a full rebuild (the explored map growing shifts
    `col0`). Cap is left at the default so trimming stays out of this property —
    trimming has its own test above.
    """
    live = PathProjection(step=step)
    all_points: list[tuple[float, float, float, int]] = []
    layout = _LAYOUT

    total = 0
    for size, col0 in batches:
        points = _pts(total, size)
        total += size
        all_points.extend(points)
        layout = _layout(col0=col0)
        live.extend(points)
        live.project(_SNAPSHOT, layout)

    fresh = PathProjection(step=step)
    fresh.extend(all_points)
    fresh.project(_SNAPSHOT, layout)

    assert live.pixels == fresh.pixels


@settings(max_examples=100, deadline=None)
@given(
    before=st.lists(st.integers(min_value=1, max_value=20), min_size=1, max_size=10),
    after=st.lists(st.integers(min_value=1, max_value=20), min_size=1, max_size=10),
    history=st.integers(min_value=0, max_value=30),
)
def test_a_cleared_path_never_resurrects_earlier_points(
    before: list[int], after: list[int], history: int
) -> None:
    """After clear(), no later seed or push can bring the old path back.

    `clear()` spends the history seed precisely because the robot still reports the
    *previous* clean's history_pose at clean start; a seed arriving after the clear
    would resurrect the abandoned trail into the live run. The published path after
    a clear must therefore contain only what was pushed after it.
    """
    projection = PathProjection(step=2)

    total = 0
    for size in before:
        projection.extend(_pts(total, size))
        total += size
    projection.project(_SNAPSHOT, _LAYOUT)

    projection.clear()
    # A refresh lands after the clear and offers the old clean's history.
    projection.seed_from_history([(0.5 + 0.01 * i, 0.5) for i in range(history)])

    fresh_points: list[tuple[float, float, float, int]] = []
    for size in after:
        points = _pts(1000 + len(fresh_points), size)
        fresh_points.extend(points)
        projection.extend(points)
    projection.project(_SNAPSHOT, _LAYOUT)

    assert projection.points == fresh_points

    expected = PathProjection(step=2)
    expected.extend(fresh_points)
    expected.project(_SNAPSHOT, _LAYOUT)
    assert projection.pixels == expected.pixels


def test_a_binding_cap_really_does_shorten_the_published_path() -> None:
    """Non-vacuity guard for the suffix property above.

    The randomised test asserts a suffix relationship, which a cap that never binds
    would satisfy trivially (a list is a suffix of itself). It cannot assert that
    trimming *happened* on any given input — `_trim` rounds the drop down to whole
    strides, so a small overflow legitimately drops nothing. So pin the binding case
    once, with numbers chosen to force it.

    Note the layout change at the end. While the decimated base survives, it still
    holds pixels for points the raw buffer has dropped, so the published path does
    not shorten — that is the case the example test next door covers. The loss only
    becomes visible on the next full reprojection, when there is no longer any raw
    point to project. That is the behaviour `_trim`'s docstring now describes, and
    the only configuration in which this property has real content.
    """
    capped = PathProjection(step=3, max_raw=10)
    uncapped = PathProjection(step=3, max_raw=10**9)

    for start in range(0, 120, 6):
        for projection in (capped, uncapped):
            projection.extend(_pts(start, 6))
            projection.project(_SNAPSHOT, _LAYOUT)

    assert len(capped.points) < len(uncapped.points)  # the cap really bound
    assert len(capped.pixels) == len(uncapped.pixels)  # ...but nothing is lost yet

    # The explored map grows: layout shifts, both caches rebuild from raw.
    shifted = _layout(col0=1)
    for projection in (capped, uncapped):
        projection.project(_SNAPSHOT, shifted)

    assert len(capped.pixels) < len(uncapped.pixels)  # now the dropped history is gone
    assert capped.pixels == uncapped.pixels[len(uncapped.pixels) - len(capped.pixels) :]
