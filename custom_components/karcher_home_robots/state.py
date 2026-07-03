# SPDX-License-Identifier: MIT
"""Pure derivation of the HA vacuum state from raw device telemetry."""

from __future__ import annotations

import logging
from enum import Enum

from ._types import DeviceProperties
from .const import (
    NON_ERROR_FAULT_CODES,
    WORK_MODE_CLEANING,
    WORK_MODE_GO_HOME,
    WORK_MODE_IDLE,
    WORK_MODE_PAUSE,
)

_LOGGER = logging.getLogger(__name__)

# status value meaning "robot is on the dock".
# Source: doc/PROTOCOL.md §6, confirmed 2026-03-28.
_STATUS_DOCKED = 4


class VacuumState(Enum):
    """HA-visible vacuum states derived from raw device telemetry."""

    CLEANING = "cleaning"
    PAUSED = "paused"
    RETURNING = "returning"
    DOCKED = "docked"
    IDLE = "idle"
    ERROR = "error"
    UNKNOWN = "unknown"


def _is_docked(props: DeviceProperties) -> bool:
    return props.status == _STATUS_DOCKED or bool(props.charge_state)


def derive_vacuum_state(props: DeviceProperties) -> VacuumState:
    """Derive the HA vacuum state from a DeviceProperties snapshot.

    Rules (doc/PROTOCOL.md §6):
      CLEANING work_mode           → Cleaning
      GO_HOME  work_mode + docked  → Docked;  else → Returning
      PAUSE    work_mode           → Paused
      IDLE     work_mode + docked  → Docked;  fault → Error; else → Idle
      unknown  work_mode + docked  → Docked;  else → Unknown

    Error only fires when idle + faulted + not docked; transient faults
    during cleaning or returning do not surface as Error. The 21xx lifecycle
    range (NON_ERROR_FAULT_CODES) is excluded — the app's own
    isStatusNoThisFault() routes those to a status display, not its error
    dialog.
    """
    work_mode = props.work_mode
    docked = _is_docked(props)

    if work_mode in WORK_MODE_CLEANING:
        return VacuumState.CLEANING

    if work_mode in WORK_MODE_PAUSE:
        return VacuumState.PAUSED

    if work_mode in WORK_MODE_GO_HOME:
        return VacuumState.DOCKED if docked else VacuumState.RETURNING

    if work_mode in WORK_MODE_IDLE:
        return _derive_idle_state(props, docked)

    _LOGGER.debug("unknown work_mode %s; docked=%s", work_mode, docked)
    return VacuumState.DOCKED if docked else VacuumState.UNKNOWN


def _derive_idle_state(props: DeviceProperties, docked: bool) -> VacuumState:
    if docked:
        return VacuumState.DOCKED
    if props.fault and props.fault not in NON_ERROR_FAULT_CODES:
        return VacuumState.ERROR
    return VacuumState.IDLE
