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

# status while the wash station works on the docked robot: 9 washing, 10 drying.
# Captured on an RVM 4 (issue #217); polled replies alternate these with 4.
_STATUS_STATION_WORK = frozenset({9, 10})

# station_act values device-confirmed on the RVM 4 (issue #217). The firmware's
# TStationMode also names 3 collect dust, 4 swap water and 11 cut hair, but the
# Indoor Robots app reads 3 and 4 differently, so those stay "busy"
# (doc/PROTOCOL.md §15.2).
_STATION_PHASES: dict[int, str] = {
    0: "idle",
    1: "washing_mops",
    2: "drying",
    5: "emptying_dust",
}
STATION_PHASE_BUSY = "busy"
STATION_PHASE_OPTIONS = [*_STATION_PHASES.values(), STATION_PHASE_BUSY]


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


def derive_station_phase(props: DeviceProperties) -> str | None:
    """Station phase slug, or None when the robot has never reported one.

    dust_action wins, as in the Indoor Robots app (getDeviceWorkStatusTip). An
    active phase needs the robot on the dock: station_act is pushed only on
    change, so a missed "done" push must not outlive the robot leaving. A plain
    dock (charge_station_type 0) reports nothing rather than a lasting "idle".
    """
    docked = _is_docked(props) or props.status in _STATUS_STATION_WORK
    if props.dust_action and docked:
        return _STATION_PHASES[5]
    act = props.station_act
    if act is None:
        return None
    if act == 0:
        return None if props.charge_station_type == 0 else _STATION_PHASES[0]
    if not docked:
        return _STATION_PHASES[0]
    return _STATION_PHASES.get(act, STATION_PHASE_BUSY)


def drying_seconds_left(props: DeviceProperties) -> int | None:
    """Seconds of mop drying left: 0 when the station is not drying."""
    phase = derive_station_phase(props)
    if phase is None:
        return None
    if phase != _STATION_PHASES[2]:
        return 0
    return props.work_time_surplus


def _derive_idle_state(props: DeviceProperties, docked: bool) -> VacuumState:
    if docked:
        return VacuumState.DOCKED
    if props.fault and props.fault not in NON_ERROR_FAULT_CODES:
        return VacuumState.ERROR
    return VacuumState.IDLE
