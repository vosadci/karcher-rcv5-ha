# SPDX-License-Identifier: MIT
"""Integration tests for the cloud-outage repair issue and log throttle.

Assertions go through the user-visible surface: the issue registry, the
`is_robot_reachable` property (what the connectivity sensor reads), and the log
records actually emitted. Outage state is *driven* through the real failure and
recovery calls with a controlled clock — never armed by assigning private fields,
which would silently stop testing anything once that state moves into a helper.

Log assertions match on level + package, not on a logger name, so they stay valid
wherever inside the integration the line is emitted from.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from custom_components.karcher_home_robots.const import DOMAIN
from custom_components.karcher_home_robots.coordinator import (
    OUTAGE_REPAIR_THRESHOLD,
    KarcherCoordinator,
)
from custom_components.karcher_home_robots.exceptions import TransientError
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from tests.conftest import PROPS_IDLE, TEST_DEVICE, make_entry

_PKG = "custom_components.karcher_home_robots"

# Origin for the fake clock — any value works.
T0 = 10_000.0
_THRESHOLD = OUTAGE_REPAIR_THRESHOLD.total_seconds()
# Mirror _LOG_THROTTLE_AFTER / _LOG_THROTTLE_INTERVAL rather than importing them:
# these are the promised throttle behaviour, so changing the constants should have
# to be re-justified here rather than silently dragging the tests along.
_THROTTLE_AFTER = 300.0
_THROTTLE_INTERVAL = 600.0


def _make_coord(hass: HomeAssistant) -> KarcherCoordinator:
    adapter = MagicMock()
    entry = make_entry()
    entry.add_to_hass(hass)
    return KarcherCoordinator(hass, adapter, TEST_DEVICE, config_entry=entry)


@contextmanager
def _at(hass: HomeAssistant, when: float) -> Iterator[None]:
    """Run a synchronous coordinator call as if the loop clock read `when`."""
    with patch.object(hass.loop, "time", return_value=when):
        yield


def _issue_id(coord: KarcherCoordinator) -> str:
    entry_id = coord.config_entry.entry_id  # type: ignore[union-attr]
    return f"cloud_outage_persistent_{entry_id}"


def _raised(coord: KarcherCoordinator) -> bool:
    """True when the persistent outage repair is currently shown to the user."""
    return ir.async_get(coord.hass).async_get_issue(DOMAIN, _issue_id(coord)) is not None


def _plant_stale_issue(coord: KarcherCoordinator) -> None:
    """Recreate what a previous session leaves in the registry across a restart."""
    ir.async_create_issue(
        coord.hass,
        DOMAIN,
        _issue_id(coord),
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="cloud_outage_persistent",
    )


def _fail(coord: KarcherCoordinator, when: float) -> None:
    with _at(coord.hass, when):
        coord._handle_outage_start(TransientError("timeout"))


def _recover(coord: KarcherCoordinator, when: float) -> None:
    with _at(coord.hass, when):
        coord._handle_outage_end()


@contextmanager
def _capturing(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Capture this integration's records at INFO, discarding anything logged by setup.

    caplog accumulates for the whole test, so the buffer has to be cleared on entry
    or a scenario's arrange step shows up in its assertion.
    """
    with caplog.at_level(logging.INFO, logger=_PKG):
        caplog.clear()
        yield


def _levels(caplog: pytest.LogCaptureFixture) -> list[int]:
    """Levels of the records this integration emitted, in order."""
    return [r.levelno for r in caplog.records if r.name.startswith(_PKG)]


# ---------------------------------------------------------------------------
# Repair issue lifecycle
# ---------------------------------------------------------------------------


async def test_repair_raised_after_threshold_of_continuous_failure(
    hass: HomeAssistant,
) -> None:
    """An outage continuing past the threshold surfaces the persistent repair."""
    coord = _make_coord(hass)

    _fail(coord, T0)  # outage begins
    _fail(coord, T0 + _THRESHOLD + 1)  # still down, now past the threshold

    issue = ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(coord))
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.is_persistent  # must outlive a restart


async def test_repair_not_raised_before_threshold(hass: HomeAssistant) -> None:
    """An outage shorter than the threshold stays silent."""
    coord = _make_coord(hass)

    _fail(coord, T0)
    _fail(coord, T0 + _THRESHOLD - 1)

    assert not _raised(coord)


async def test_repair_raised_once_not_once_per_failure(hass: HomeAssistant) -> None:
    """Failures continuing past the threshold must not re-create the issue."""
    coord = _make_coord(hass)
    coord._create_repair = MagicMock()  # type: ignore[method-assign]

    _fail(coord, T0)
    for i in range(4):
        _fail(coord, T0 + _THRESHOLD + 1 + i * 30)

    coord._create_repair.assert_called_once_with("cloud_outage_persistent", persistent=True)


async def test_recovery_clears_the_repair(hass: HomeAssistant) -> None:
    """Reaching the cloud again dismisses the repair and restores reachability."""
    coord = _make_coord(hass)

    _fail(coord, T0)
    _fail(coord, T0 + _THRESHOLD + 1)
    assert _raised(coord)
    assert not coord.is_robot_reachable

    _recover(coord, T0 + _THRESHOLD + 60)

    assert not _raised(coord)
    assert coord.is_robot_reachable


async def test_push_ends_outage(hass: HomeAssistant) -> None:
    """A push is proof of reachability and must end an outage like a poll does."""
    coord = _make_coord(hass)

    _fail(coord, T0)
    _fail(coord, T0 + _THRESHOLD + 1)
    assert _raised(coord)
    assert not coord.is_robot_reachable

    coord._handle_push(PROPS_IDLE)
    await hass.async_block_till_done()

    assert coord.is_robot_reachable
    assert not _raised(coord)


async def test_reachable_tracks_outage_and_recovery(hass: HomeAssistant) -> None:
    """The property the connectivity sensor reads follows the outage state."""
    coord = _make_coord(hass)
    assert coord.is_robot_reachable

    _fail(coord, T0)
    assert not coord.is_robot_reachable

    _recover(coord, T0 + 60)
    assert coord.is_robot_reachable


# ---------------------------------------------------------------------------
# Stale-issue reconciliation (the repair is persistent; the "I raised it" flag is not)
# ---------------------------------------------------------------------------


async def test_stale_repair_cleared_on_first_healthy_poll(hass: HomeAssistant) -> None:
    """A repair left by a previous session clears on the first success.

    The issue survives a restart but the "did I create it" flag does not, so
    without an explicit reconcile a stale issue would linger forever whenever the
    cloud recovered before this process ever saw an outage.
    """
    coord = _make_coord(hass)
    _plant_stale_issue(coord)
    assert _raised(coord)

    _recover(coord, T0)  # first healthy poll, no outage seen this session

    assert not _raised(coord)


async def test_stale_reconcile_is_one_shot(hass: HomeAssistant) -> None:
    """Reconciliation spends itself, so it cannot fight a repair raised later.

    Proven by consequence: a second planted issue survives a later healthy poll,
    which only holds if the one-shot reconcile was already used up.
    """
    coord = _make_coord(hass)
    _plant_stale_issue(coord)
    _recover(coord, T0)
    assert not _raised(coord)

    _plant_stale_issue(coord)
    _recover(coord, T0 + 60)

    assert _raised(coord)


async def test_recovering_from_a_real_outage_also_spends_the_reconcile(
    hass: HomeAssistant,
) -> None:
    """A genuine outage→recovery cycle counts as the reconcile too."""
    coord = _make_coord(hass)

    _fail(coord, T0)
    _recover(coord, T0 + 60)

    _plant_stale_issue(coord)
    _recover(coord, T0 + 120)

    assert _raised(coord)  # untouched: the reconcile was already spent


# ---------------------------------------------------------------------------
# Log throttle
# ---------------------------------------------------------------------------


async def test_first_failure_logs_warning(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """The transition into unavailability is worth a WARNING."""
    coord = _make_coord(hass)

    with _capturing(caplog):
        _fail(coord, T0)

    assert _levels(caplog) == [logging.WARNING]


async def test_failure_within_throttle_window_logs_info(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Repeat failures early in an outage drop to INFO."""
    coord = _make_coord(hass)
    _fail(coord, T0)

    with _capturing(caplog):
        _fail(coord, T0 + 60)

    assert _levels(caplog) == [logging.INFO]


async def test_failure_after_throttle_point_is_silent(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Past the throttle point nothing is logged until the interval expires."""
    coord = _make_coord(hass)
    _fail(coord, T0)

    with _capturing(caplog):
        _fail(coord, T0 + _THROTTLE_AFTER + 180)  # 8 min in, 8 min since the last line

    assert _levels(caplog) == []


async def test_throttled_log_resumes_after_interval(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Once the interval has elapsed, a progress line is emitted."""
    coord = _make_coord(hass)
    _fail(coord, T0)

    with _capturing(caplog):
        _fail(coord, T0 + _THROTTLE_AFTER + _THROTTLE_INTERVAL + 1)

    assert _levels(caplog) == [logging.INFO]


async def test_throttled_logs_are_spaced_by_a_full_interval(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """After a throttled line the next waits a full interval, not just the window."""
    coord = _make_coord(hass)
    _fail(coord, T0)
    first_line = T0 + _THROTTLE_AFTER + _THROTTLE_INTERVAL + 1
    _fail(coord, first_line)

    with _capturing(caplog):
        _fail(coord, first_line + _THROTTLE_INTERVAL - 60)  # too soon
        assert _levels(caplog) == []

        caplog.clear()
        _fail(coord, first_line + _THROTTLE_INTERVAL + 1)  # interval elapsed
        assert _levels(caplog) == [logging.INFO]


async def test_recovery_logs_warning(hass: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """The transition back to available is worth a WARNING."""
    coord = _make_coord(hass)
    _fail(coord, T0)

    with _capturing(caplog):
        _recover(coord, T0 + 120)

    assert _levels(caplog) == [logging.WARNING]


async def test_healthy_poll_without_an_outage_is_quiet(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Ordinary healthy polls log nothing."""
    coord = _make_coord(hass)

    with _capturing(caplog):
        _recover(coord, T0)
        _recover(coord, T0 + 30)

    assert _levels(caplog) == []
