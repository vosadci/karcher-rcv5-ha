# SPDX-License-Identifier: MIT
"""Integration tests for outage repair issue and log throttle."""

from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock, patch

from custom_components.karcher_home_robots.const import DOMAIN
from custom_components.karcher_home_robots.coordinator import (
    OUTAGE_REPAIR_THRESHOLD,
    KarcherCoordinator,
)
from custom_components.karcher_home_robots.exceptions import TransientError
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from tests.conftest import PROPS_IDLE, TEST_DEVICE, make_entry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coord_with_entry(hass: HomeAssistant) -> tuple[KarcherCoordinator, MagicMock]:
    """Return a coordinator backed by a MagicMock adapter, with a real entry_id."""
    adapter = MagicMock()
    adapter.fetch_properties = MagicMock()
    entry = make_entry()
    entry.add_to_hass(hass)
    coord = KarcherCoordinator(hass, adapter, TEST_DEVICE, config_entry=entry)
    return coord, adapter


def _logger_for(coord: KarcherCoordinator) -> logging.Logger:
    """Return the logger used by the coordinator module."""
    return logging.getLogger("custom_components.karcher_home_robots.coordinator")


# ---------------------------------------------------------------------------
# FR-OF-6: repair issue created after threshold
# ---------------------------------------------------------------------------


async def test_repair_issue_created_after_threshold(hass: HomeAssistant) -> None:
    """After OUTAGE_REPAIR_THRESHOLD of continuous failures, repair issue is created."""
    coord, _ = _coord_with_entry(hass)
    threshold = OUTAGE_REPAIR_THRESHOLD.total_seconds()

    # Simulate outage start far enough in the past to exceed the threshold.
    coord._outage_start = time.monotonic() - (threshold + 1)
    coord._last_throttled_log = coord._outage_start

    exc = TransientError("timeout")
    with patch("time.monotonic", return_value=coord._outage_start + threshold + 1):
        coord._handle_outage_start(exc)

    issue_reg = ir.async_get(hass)
    entry_id = coord.config_entry.entry_id  # type: ignore[union-attr]
    issue = issue_reg.async_get_issue(DOMAIN, f"cloud_outage_persistent_{entry_id}")
    assert issue is not None, "Repair issue was not created after outage threshold"
    assert issue.severity == ir.IssueSeverity.WARNING


async def test_repair_issue_not_created_before_threshold(hass: HomeAssistant) -> None:
    """No repair issue is created if the outage is shorter than the threshold."""
    coord, _ = _coord_with_entry(hass)

    # Only 30 minutes into an outage.
    coord._outage_start = time.monotonic() - 1800

    exc = TransientError("timeout")
    coord._handle_outage_start(exc)

    issue_reg = ir.async_get(hass)
    entry_id = coord.config_entry.entry_id  # type: ignore[union-attr]
    issue = issue_reg.async_get_issue(DOMAIN, f"cloud_outage_persistent_{entry_id}")
    assert issue is None, "Repair issue created too early"


# ---------------------------------------------------------------------------
# FR-OF-7: repair issue dismissed on recovery
# ---------------------------------------------------------------------------


async def test_repair_issue_dismissed_on_recovery(hass: HomeAssistant) -> None:
    """Repair issue is dismissed when the cloud becomes reachable again."""
    coord, _ = _coord_with_entry(hass)
    entry_id = coord.config_entry.entry_id  # type: ignore[union-attr]
    issue_id = f"cloud_outage_persistent_{entry_id}"

    # Pre-create the repair issue to simulate it having been raised.
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="cloud_outage_persistent",
    )
    coord._outage_start = time.monotonic() - 3700
    coord._outage_repair_created = True

    coord._handle_outage_end()

    issue_reg = ir.async_get(hass)
    issue = issue_reg.async_get_issue(DOMAIN, issue_id)
    assert issue is None, "Repair issue was not dismissed on recovery"
    assert coord._outage_start is None
    assert not coord._outage_repair_created


async def test_incoming_push_ends_outage(hass: HomeAssistant) -> None:
    """A push (not just a poll) is proof of reachability and must end the outage."""
    coord, _ = _coord_with_entry(hass)
    entry_id = coord.config_entry.entry_id  # type: ignore[union-attr]
    issue_id = f"cloud_outage_persistent_{entry_id}"

    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="cloud_outage_persistent",
    )
    coord._outage_start = time.monotonic() - 3700
    coord._outage_repair_created = True
    assert not coord.is_robot_reachable

    coord._handle_push(PROPS_IDLE)
    await hass.async_block_till_done()

    assert coord._outage_start is None
    assert coord.is_robot_reachable
    issue_reg = ir.async_get(hass)
    assert issue_reg.async_get_issue(DOMAIN, issue_id) is None


async def test_stale_repair_issue_cleared_on_first_healthy_poll(hass: HomeAssistant) -> None:
    """A persistent outage issue left by a previous session is cleared on first success.

    Regression guard: the issue is is_persistent (survives restart) but
    _outage_repair_created resets to False, so without reconciliation a stale
    issue would linger forever if the cloud recovers before any new outage.
    """
    coord, _ = _coord_with_entry(hass)
    entry_id = coord.config_entry.entry_id  # type: ignore[union-attr]
    issue_id = f"cloud_outage_persistent_{entry_id}"

    # Simulate the issue surviving a restart: present in the registry, but the
    # fresh coordinator has no active outage and never created it this session.
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="cloud_outage_persistent",
    )
    assert coord._outage_start is None
    assert not coord._outage_repair_created

    coord._handle_outage_end()

    issue_reg = ir.async_get(hass)
    assert issue_reg.async_get_issue(DOMAIN, issue_id) is None, "Stale repair issue not cleared"
    assert coord._outage_repair_reconciled


# ---------------------------------------------------------------------------
# FR-OF-8: log throttle
# ---------------------------------------------------------------------------


async def test_first_failure_logs_at_warning(hass: HomeAssistant) -> None:
    """First poll failure logs at WARNING with traceback."""
    coord, _ = _coord_with_entry(hass)
    exc = TransientError("first failure")

    with patch.object(_logger_for(coord), "warning") as mock_warning:
        coord._handle_outage_start(exc)

    mock_warning.assert_called_once()


async def test_subsequent_failures_log_at_info_within_5min(hass: HomeAssistant) -> None:
    """Failures within the first 5 minutes log at INFO."""
    coord, _ = _coord_with_entry(hass)
    coord._outage_start = time.monotonic() - 60  # 1 min into outage
    coord._last_throttled_log = coord._outage_start

    exc = TransientError("ongoing failure")
    with patch.object(_logger_for(coord), "info") as mock_info:
        coord._handle_outage_start(exc)

    mock_info.assert_called_once()


async def test_no_log_before_interval_after_5min(hass: HomeAssistant) -> None:
    """After 5 minutes, no log is emitted until the 10-min interval expires."""
    now = time.monotonic()
    coord, _ = _coord_with_entry(hass)
    # 8 minutes into outage, last log was 2 minutes ago (not yet at 10 min).
    coord._outage_start = now - 480
    coord._last_throttled_log = now - 120

    exc = TransientError("ongoing")
    with patch.object(_logger_for(coord), "info") as mock_info:
        coord._handle_outage_start(exc)

    mock_info.assert_not_called()


async def test_log_emitted_after_10min_interval(hass: HomeAssistant) -> None:
    """After 10 minutes since the last throttled log, a line is emitted."""
    now = time.monotonic()
    coord, _ = _coord_with_entry(hass)
    coord._outage_start = now - 900  # 15 minutes into outage
    coord._last_throttled_log = now - 700  # last log was 700 s ago (>600)

    exc = TransientError("still down")
    with patch.object(_logger_for(coord), "info") as mock_info:
        coord._handle_outage_start(exc)

    mock_info.assert_called_once()


async def test_recovery_logs_at_warning(hass: HomeAssistant) -> None:
    """Recovery transition is logged at WARNING (FR-OF-8)."""
    coord, _ = _coord_with_entry(hass)
    coord._outage_start = time.monotonic() - 120

    with patch.object(_logger_for(coord), "warning") as mock_warning:
        coord._handle_outage_end()

    mock_warning.assert_called_once()
