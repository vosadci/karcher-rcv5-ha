# SPDX-License-Identifier: MIT
"""Tests for NovelValueTracker — the out-of-table value recorder.

Its whole job is a judgement call: which values are worth telling a human
about, once, and how loudly. So the assertions here are about that judgement,
not about the bookkeeping — that a known value is silent, that an unknown one is
recorded exactly once, and that the tier chooses the volume.

The known-value tables are asserted against `const.py` rather than restated, so
these tests cannot drift into agreeing with a copy of themselves.
"""

from __future__ import annotations

import logging

import pytest
from custom_components.karcher_home_robots._model_profile import SupportTier
from custom_components.karcher_home_robots._novel_values import (
    KNOWN_VALUES,
    NovelValueTracker,
)
from custom_components.karcher_home_robots.const import (
    FAULT_CODE_DESCRIPTIONS,
    WORK_MODE_CLEANING,
    WORK_MODE_GO_HOME,
    WORK_MODE_IDLE,
    WORK_MODE_PAUSE,
)
from custom_components.karcher_home_robots.map_data import RestrictedZone

# Chosen to be outside every table; asserted below rather than assumed.
_NOVEL_WORK_MODE = 9001
_NOVEL_FAULT = 9002
_NOVEL_ZONE = 9003


def _tracker(tier: SupportTier | None = SupportTier.EXPECTED) -> NovelValueTracker:
    return NovelValueTracker(tier)


def _zone(type_id: int) -> RestrictedZone:
    return RestrictedZone(zone_id=1, type_id=type_id, points=[(0.0, 0.0)])


# ---------------------------------------------------------------------------
# The tables themselves
# ---------------------------------------------------------------------------


def test_work_mode_table_is_every_mode_the_state_machine_knows() -> None:
    """Novel means outside `state.derive_vacuum_state`'s reach, so the table is
    exactly the four sets that function dispatches on — no more, no less."""
    assert KNOWN_VALUES["work_mode"] == (
        WORK_MODE_CLEANING | WORK_MODE_GO_HOME | WORK_MODE_PAUSE | WORK_MODE_IDLE
    )


def test_fault_table_is_the_description_table() -> None:
    """Including 0, which that table already carries as "none" — otherwise every
    healthy poll on every robot would report a discovery."""
    assert KNOWN_VALUES["fault"] == frozenset(FAULT_CODE_DESCRIPTIONS)
    assert FAULT_CODE_DESCRIPTIONS[0] == "none"


def test_zone_table_spans_both_internal_sources() -> None:
    """map_data.py documents no-mop as 3 and map_render.py draws it as 6. Both
    are in the table on purpose: reporting our own disagreement as a discovery
    would fire on every user who has ever drawn a no-mop area."""
    assert {1, 2, 3, 6} == KNOWN_VALUES["zone_type"]


@pytest.mark.parametrize(
    ("kind", "value"),
    [("work_mode", _NOVEL_WORK_MODE), ("fault", _NOVEL_FAULT), ("zone_type", _NOVEL_ZONE)],
)
def test_the_probe_values_really_are_outside_the_tables(kind: str, value: int) -> None:
    """Guards every test below: if a table ever grew to include a probe value,
    those tests would pass while asserting nothing."""
    assert value not in KNOWN_VALUES[kind]


# ---------------------------------------------------------------------------
# observe()
# ---------------------------------------------------------------------------


def test_a_known_value_is_never_recorded() -> None:
    tracker = _tracker()

    tracker.observe("work_mode", next(iter(WORK_MODE_CLEANING)))
    tracker.observe("fault", 0)

    assert tracker.novel == {}


def test_a_missing_value_is_never_recorded() -> None:
    """None is "the robot did not report this", not a discovery."""
    tracker = _tracker()

    tracker.observe("work_mode", None)

    assert tracker.novel == {}


def test_an_unknown_value_is_recorded_once(caplog: pytest.LogCaptureFixture) -> None:
    """Once, not once per poll — this runs every 30 seconds forever."""
    tracker = _tracker()

    with caplog.at_level(logging.DEBUG):
        for _ in range(5):
            tracker.observe("work_mode", _NOVEL_WORK_MODE)

    assert tracker.novel == {"work_mode": [_NOVEL_WORK_MODE]}
    assert len([r for r in caplog.records if str(_NOVEL_WORK_MODE) in r.getMessage()]) == 1


def test_distinct_values_are_all_kept_in_first_sight_order() -> None:
    tracker = _tracker()

    tracker.observe("work_mode", _NOVEL_WORK_MODE + 1)
    tracker.observe("work_mode", _NOVEL_WORK_MODE)
    tracker.observe("work_mode", _NOVEL_WORK_MODE + 1)

    assert tracker.novel == {"work_mode": [_NOVEL_WORK_MODE + 1, _NOVEL_WORK_MODE]}


def test_kinds_are_tracked_separately() -> None:
    """A fault code and a work mode can collide numerically; they must not be
    deduplicated against each other."""
    tracker = _tracker()

    tracker.observe("work_mode", _NOVEL_WORK_MODE)
    tracker.observe("fault", _NOVEL_WORK_MODE)

    assert tracker.novel == {"work_mode": [_NOVEL_WORK_MODE], "fault": [_NOVEL_WORK_MODE]}


def test_an_unknown_kind_records_rather_than_raises() -> None:
    """A typo'd kind must produce noise in diagnostics, never a KeyError inside
    a user's Home Assistant."""
    tracker = _tracker()

    tracker.observe("wrok_mode", 5)

    assert tracker.novel == {"wrok_mode": [5]}


def test_novel_is_a_copy_callers_cannot_corrupt() -> None:
    """diagnostics.py hands this straight into a JSON dump; a caller mutating it
    must not edit the tracker's own record."""
    tracker = _tracker()
    tracker.observe("fault", _NOVEL_FAULT)

    tracker.novel["fault"].append(1)
    tracker.novel.clear()

    assert tracker.novel == {"fault": [_NOVEL_FAULT]}


# ---------------------------------------------------------------------------
# Log level by tier
# ---------------------------------------------------------------------------


def test_maintainer_verified_model_logs_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    """On the robot the tables were built from, an unrecognised value is a real
    hole in those tables — say so out loud."""
    tracker = _tracker(SupportTier.MAINTAINER_VERIFIED)

    with caplog.at_level(logging.DEBUG):
        tracker.observe("work_mode", _NOVEL_WORK_MODE)

    assert [r.levelno for r in caplog.records] == [logging.WARNING]


@pytest.mark.parametrize(
    "tier",
    [SupportTier.COMMUNITY_VERIFIED, SupportTier.EXPECTED, SupportTier.UNCERTAIN, None],
)
def test_any_other_model_logs_at_info(
    tier: SupportTier | None, caplog: pytest.LogCaptureFixture
) -> None:
    """Everywhere else it is the expected consequence of shipping full entities
    to unverified hardware: record it, don't shout."""
    tracker = _tracker(tier)

    with caplog.at_level(logging.DEBUG):
        tracker.observe("work_mode", _NOVEL_WORK_MODE)

    assert [r.levelno for r in caplog.records] == [logging.INFO]


# ---------------------------------------------------------------------------
# observe_zone_types()
# ---------------------------------------------------------------------------


def test_zone_types_are_filtered_against_the_table() -> None:
    tracker = _tracker()

    tracker.observe_zone_types([_zone(1), _zone(_NOVEL_ZONE), _zone(6), _zone(_NOVEL_ZONE)])

    assert tracker.novel == {"zone_type": [_NOVEL_ZONE]}


def test_a_map_with_no_zones_records_nothing() -> None:
    tracker = _tracker()

    tracker.observe_zone_types([])

    assert tracker.novel == {}
