# SPDX-License-Identifier: MIT
"""Unit tests for OutageTracker — the pure cloud-outage state machine.

The repair *wiring* (registry issues, the poll and push paths, log throttling) is
covered by tests/integration/test_outage_repair.py. These cover the decision rules
directly: no hass, no coordinator, and no clock patching — the caller supplies the
time, so boundaries can be hit exactly.
"""

from __future__ import annotations

import pytest
from custom_components.karcher_home_robots._outage import OutageTracker
from custom_components.karcher_home_robots._repairs import RepairAction

THRESHOLD = 3600.0
T0 = 1000.0


@pytest.fixture
def tracker() -> OutageTracker:
    return OutageTracker(THRESHOLD)


def _err() -> Exception:
    return TimeoutError("unreachable")


# --- reachability ----------------------------------------------------------


def test_starts_healthy(tracker: OutageTracker) -> None:
    assert tracker.is_healthy


def test_failure_makes_unhealthy(tracker: OutageTracker) -> None:
    tracker.observe_failure(T0, _err())

    assert not tracker.is_healthy


def test_success_restores_healthy(tracker: OutageTracker) -> None:
    tracker.observe_failure(T0, _err())
    tracker.observe_success(T0 + 60)

    assert tracker.is_healthy


# --- repair threshold ------------------------------------------------------


def test_first_failure_never_creates_a_repair(tracker: OutageTracker) -> None:
    """The outage has no duration yet — one failed poll is not an incident."""
    assert tracker.observe_failure(T0, _err()) is RepairAction.NONE


def test_repair_created_exactly_at_the_threshold(tracker: OutageTracker) -> None:
    """The boundary is inclusive: duration == threshold fires."""
    tracker.observe_failure(T0, _err())

    assert tracker.observe_failure(T0 + THRESHOLD, _err()) is RepairAction.CREATE


def test_repair_not_created_just_below_the_threshold(tracker: OutageTracker) -> None:
    tracker.observe_failure(T0, _err())

    assert tracker.observe_failure(T0 + THRESHOLD - 0.5, _err()) is RepairAction.NONE


def test_repair_created_only_once_per_outage(tracker: OutageTracker) -> None:
    tracker.observe_failure(T0, _err())
    assert tracker.observe_failure(T0 + THRESHOLD, _err()) is RepairAction.CREATE

    for i in range(1, 5):
        assert tracker.observe_failure(T0 + THRESHOLD + i * 60, _err()) is RepairAction.NONE


# --- recovery --------------------------------------------------------------


def test_recovery_clears_a_created_repair(tracker: OutageTracker) -> None:
    tracker.observe_failure(T0, _err())
    tracker.observe_failure(T0 + THRESHOLD, _err())

    assert tracker.observe_success(T0 + THRESHOLD + 60) is RepairAction.CLEAR


def test_recovery_from_a_short_outage_clears_nothing(tracker: OutageTracker) -> None:
    """Nothing was raised, so there is nothing to dismiss."""
    tracker.observe_failure(T0, _err())

    assert tracker.observe_success(T0 + 60) is RepairAction.NONE


def test_a_second_outage_can_raise_the_repair_again(tracker: OutageTracker) -> None:
    """Recovery re-arms the detector rather than latching it off."""
    tracker.observe_failure(T0, _err())
    tracker.observe_failure(T0 + THRESHOLD, _err())
    tracker.observe_success(T0 + THRESHOLD + 60)

    later = T0 + 100_000
    tracker.observe_failure(later, _err())

    assert tracker.observe_failure(later + THRESHOLD, _err()) is RepairAction.CREATE


# --- stale-repair reconciliation -------------------------------------------


def test_first_success_clears_a_stale_repair(tracker: OutageTracker) -> None:
    """A fresh tracker cannot know whether a persistent issue survived a restart,
    so its first healthy read clears one unconditionally."""
    assert tracker.observe_success(T0) is RepairAction.CLEAR


def test_reconcile_is_spent_after_one_success(tracker: OutageTracker) -> None:
    tracker.observe_success(T0)

    assert tracker.observe_success(T0 + 60) is RepairAction.NONE


def test_recovering_from_an_outage_also_spends_the_reconcile(tracker: OutageTracker) -> None:
    """Otherwise a later healthy poll would clear a repair this session raised."""
    tracker.observe_failure(T0, _err())
    tracker.observe_success(T0 + 60)

    assert tracker.observe_success(T0 + 120) is RepairAction.NONE
