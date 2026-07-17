# SPDX-License-Identifier: MIT
"""Cloud-outage tracking: when a prolonged outage becomes a repair, and log throttling.

Pure state machine — no HA, no I/O. `observe_failure()` and `observe_success()` fold
poll/push outcomes into the outage state and return the `RepairAction` the caller
should apply, so the repair-issue I/O stays with the coordinator. The caller supplies
the clock, which keeps this module testable without patching time.
"""

from __future__ import annotations

import logging

from ._repairs import RepairAction

_LOGGER = logging.getLogger(__name__)

# After this long in an outage, drop from one line per failure to one per interval.
_LOG_THROTTLE_AFTER = 300.0
_LOG_THROTTLE_INTERVAL = 600.0


class OutageTracker:
    """Tracks whether the cloud is reachable and how loudly to say so.

    Two things are debounced against a continuous outage: the persistent repair
    issue (raised only once the outage passes `repair_threshold`) and the log
    volume (every failure early on, then one line per `_LOG_THROTTLE_INTERVAL`).
    """

    def __init__(self, repair_threshold: float) -> None:
        self._repair_threshold = repair_threshold
        # Clock reading when the current outage began; None means healthy.
        self._start: float | None = None
        self._repair_created = False
        self._repair_reconciled = False
        self._last_throttled_log = 0.0

    @property
    def is_healthy(self) -> bool:
        """True when no outage is in progress."""
        return self._start is None

    def observe_failure(self, now: float, exc: Exception) -> RepairAction:
        """Record an unreachable cloud; CREATE once the outage is prolonged."""
        if self._start is None:
            self._start = now
            self._last_throttled_log = now
            _LOGGER.warning("Cloud unreachable: %s. Entities will become unavailable.", exc)
            return RepairAction.NONE

        duration = now - self._start
        action = RepairAction.NONE
        if not self._repair_created and duration >= self._repair_threshold:
            self._repair_created = True
            action = RepairAction.CREATE

        self._log_continued_outage(now, duration, exc)
        return action

    def observe_success(self, now: float) -> RepairAction:
        """Record a reachable cloud; CLEAR when a repair should be dismissed."""
        if self._start is None:
            return self._reconcile_stale_repair()

        _LOGGER.warning(
            "Cloud reachable again after %.0f min outage.",
            (now - self._start) / 60,
        )
        self._start = None
        self._last_throttled_log = 0.0
        self._repair_reconciled = True

        if self._repair_created:
            self._repair_created = False
            return RepairAction.CLEAR
        return RepairAction.NONE

    def _log_continued_outage(self, now: float, duration: float, exc: Exception) -> None:
        if duration < _LOG_THROTTLE_AFTER:
            _LOGGER.info("Cloud still unreachable: %s", exc)
        elif now - self._last_throttled_log >= _LOG_THROTTLE_INTERVAL:
            self._last_throttled_log = now
            _LOGGER.info("Cloud unreachable for %.0f min: %s", duration / 60, exc)

    def _reconcile_stale_repair(self) -> RepairAction:
        """Clear a repair a previous session left behind, once.

        The repair is persistent so it outlives a restart, but `_repair_created`
        does not — without this, a stale issue would linger forever whenever the
        cloud recovered before this process ever saw an outage. One-shot: after it,
        any issue present was raised by this session and is tracked properly.
        """
        if self._repair_reconciled:
            return RepairAction.NONE
        self._repair_reconciled = True
        return RepairAction.CLEAR
