# SPDX-License-Identifier: MIT
"""Coordinator -- state ownership, push/poll reconciliation, state derivation.

Responsibilities (spec/04-architecture.md §4.2, §5, §6):
  - Own DeviceProperties for one config entry.
  - Derive VacuumState from raw properties via derive_vacuum_state().
  - Reconcile push and poll updates using monotonic receipt timestamps
    so that an older poll never overwrites a newer push (FR-UP-5, NFR-R-5).
  - Propagate unavailability to entities when the cloud is unreachable
    (FR-OF-1).
  - Hold the selected room ID for the vacuum entity (FR-SL-3).

The coordinator never imports adapter.py directly; it receives an
adapter instance via dependency injection in async_setup().
"""

from __future__ import annotations

import logging
from enum import Enum

from ._types import DeviceProperties
from .const import (
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
    """HA-visible vacuum states derived from raw device telemetry.

    Maps to homeassistant.components.vacuum.VacuumActivity values in
    the entity layer; the coordinator is decoupled from HA enums so
    derive_vacuum_state() is testable without an HA environment.
    """

    CLEANING = "cleaning"
    PAUSED = "paused"
    RETURNING = "returning"
    DOCKED = "docked"
    IDLE = "idle"
    ERROR = "error"
    UNKNOWN = "unknown"


def _is_docked(props: DeviceProperties) -> bool:
    """Return True when the robot is physically on the charging dock."""
    return props.status == _STATUS_DOCKED or bool(props.charge_state)


def derive_vacuum_state(props: DeviceProperties) -> VacuumState:
    """Derive the HA vacuum state from a DeviceProperties snapshot.

    Derivation rules (spec/04-architecture.md §5, doc/PROTOCOL.md §6):
      1. work_mode in WORK_MODE_CLEANING -> Cleaning.
      2. work_mode in WORK_MODE_GO_HOME:
           docked  -> Docked; else -> Returning.
      3. work_mode in WORK_MODE_PAUSE -> Paused.
      4. work_mode in WORK_MODE_IDLE:
           docked  -> Docked;
           fault   -> Error;
           else    -> Idle.
      5. Unknown work_mode (logged at DEBUG):
           docked  -> Docked; else -> Unknown.

    "Docked" means status == 4 OR charge_state > 0.

    FR-BS-1: Error is only set when the robot is idle AND faulted AND
    not docked -- transient faults during cleaning or returning do not
    surface as Error (FR-BS-2).

    Args:
        props: Frozen snapshot of device telemetry from the adapter.

    Returns:
        The derived VacuumState.
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
    """Return the state for a robot whose work_mode is in WORK_MODE_IDLE."""
    if docked:
        return VacuumState.DOCKED
    if props.fault:
        return VacuumState.ERROR
    return VacuumState.IDLE
