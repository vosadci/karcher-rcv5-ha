# SPDX-License-Identifier: MIT
"""First-sight logging for property values our tables do not describe.

Every model gets the full entity set, so a robot whose firmware reports a work
mode, fault code or restricted-zone type we have never seen renders it as
"unknown" rather than failing. That is the right runtime behaviour and the wrong
diagnostic one: the value vanishes silently. This records each distinct
out-of-table value once, logs it once, and hands the collection to diagnostics —
which is how a support tier gets promoted on evidence rather than on hope.

Pure state: no HA, no I/O, no clock. The support tier only picks a log level.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ._model_profile import SupportTier
from .const import (
    FAULT_CODE_DESCRIPTIONS,
    WORK_MODE_CLEANING,
    WORK_MODE_GO_HOME,
    WORK_MODE_IDLE,
    WORK_MODE_PAUSE,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .map_data import RestrictedZone

_LOGGER = logging.getLogger(__name__)

# Zone type IDs anything in this integration accounts for. Deliberately the union
# of both sources rather than either one: map_data.py documents no-mop as 3 and
# map_render.py draws it as 6, and "novel" has to mean outside everything we have
# written down — otherwise this reports our own internal disagreement as a
# discovery on every user's map.
KNOWN_ZONE_TYPE_IDS: frozenset[int] = frozenset({1, 2, 3, 6})

# The tables a value is novel against, keyed by the `kind` passed to observe().
KNOWN_VALUES: dict[str, frozenset[int]] = {
    "work_mode": WORK_MODE_CLEANING | WORK_MODE_GO_HOME | WORK_MODE_PAUSE | WORK_MODE_IDLE,
    # FAULT_CODE_DESCRIPTIONS already carries 0 as "none", so a healthy robot
    # never reports a discovery.
    "fault": frozenset(FAULT_CODE_DESCRIPTIONS),
    "zone_type": KNOWN_ZONE_TYPE_IDS,
}


class NovelValueTracker:
    """Remembers out-of-table values seen this session, logging each one once.

    Louder on the maintainer's own model: an unrecognised value there is a real
    hole in our tables, because those tables were built from that robot. On any
    other model it is the expected consequence of shipping full entities to
    unverified hardware — worth recording, not worth interrupting the log for.

    A `kind` with no table is treated as having an empty one, so every value is
    novel. That is the safe direction: a typo'd kind produces noise in
    diagnostics, not a KeyError inside a user's Home Assistant.
    """

    def __init__(self, tier: SupportTier | None) -> None:
        self._level = logging.WARNING if tier is SupportTier.MAINTAINER_VERIFIED else logging.INFO
        self._seen: dict[str, list[int]] = {}

    @property
    def novel(self) -> dict[str, list[int]]:
        """Out-of-table values seen this session, in first-sight order."""
        return {kind: list(values) for kind, values in self._seen.items()}

    def observe(self, kind: str, value: int | None) -> None:
        """Record `value` when our table for `kind` does not describe it."""
        if value is None or value in KNOWN_VALUES.get(kind, frozenset()):
            return
        seen = self._seen.setdefault(kind, [])
        if value in seen:
            return
        seen.append(value)
        _LOGGER.log(self._level, "Robot reported an unrecognised %s: %s", kind, value)

    def observe_zone_types(self, zones: Iterable[RestrictedZone]) -> None:
        """Record every restricted-zone type the renderer does not draw.

        The loop lives here rather than at the call site to keep it out of
        coordinator.py, which is pinned at 100% branch coverage.
        """
        for zone in zones:
            self.observe("zone_type", zone.type_id)
