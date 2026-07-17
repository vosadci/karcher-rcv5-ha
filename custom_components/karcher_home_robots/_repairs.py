# SPDX-License-Identifier: MIT
"""Shared vocabulary for the repair decisions the pure detector modules return.

A detector (`_room_names`, `_outage`) decides *what should happen* to its repair
issue; the coordinator owns the issue-registry I/O that carries the decision out.
Keeping the enum here lets detectors stay independent of one another.
"""

from __future__ import annotations

from enum import Enum


class RepairAction(Enum):
    """What the caller should do with the repair issue the detector owns."""

    NONE = "none"
    CREATE = "create"
    CLEAR = "clear"
