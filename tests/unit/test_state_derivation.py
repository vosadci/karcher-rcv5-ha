# SPDX-License-Identifier: MIT
"""Unit tests for derive_vacuum_state().

Table-driven; covers every work_mode set x docked x fault combination
documented in ARCHITECTURE.md and doc/PROTOCOL.md §6.

"""

from __future__ import annotations

import pytest
from custom_components.karcher_home_robots._types import DeviceProperties
from custom_components.karcher_home_robots.coordinator import (
    VacuumState,
    derive_vacuum_state,
)


def props(**kwargs: object) -> DeviceProperties:
    """Build a DeviceProperties with sane defaults for fields not under test."""
    defaults: dict[str, object] = {
        "battery": 80,
        "cleaning_area": 0,
        "cleaning_time": 0,
        "work_mode": 0,
        "status": 0,
        "charge_state": 0,
        "fault": 0,
        "wind": 1,
        "water": 0,
        "current_map_id": "1",
    }
    defaults.update(kwargs)
    return DeviceProperties(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Cleaning (work_mode in WORK_MODE_CLEANING)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wm", [1, 7, 25, 30, 36, 81])
def test_cleaning_modes(wm: int) -> None:
    """all documented cleaning work_modes map to Cleaning."""
    assert derive_vacuum_state(props(work_mode=wm)) == VacuumState.CLEANING


@pytest.mark.parametrize("wm", [1, 7, 25, 30, 36, 81])
def test_cleaning_with_fault_stays_cleaning(wm: int) -> None:
    """transient fault during cleaning does not flip to Error."""
    assert derive_vacuum_state(props(work_mode=wm, fault=5)) == VacuumState.CLEANING


# ---------------------------------------------------------------------------
# Returning / Docked (work_mode in WORK_MODE_GO_HOME)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wm", [5, 10, 11, 12, 21, 26, 32, 38, 47])
def test_go_home_not_docked(wm: int) -> None:
    """go-home work_modes while not docked -> Returning."""
    result = derive_vacuum_state(props(work_mode=wm, status=0, charge_state=0))
    assert result == VacuumState.RETURNING


@pytest.mark.parametrize("wm", [5, 10, 11, 12, 21, 26, 32, 38, 47])
def test_go_home_docked_via_status(wm: int) -> None:
    """go-home with status=4 -> Docked."""
    result = derive_vacuum_state(props(work_mode=wm, status=4, charge_state=0))
    assert result == VacuumState.DOCKED


@pytest.mark.parametrize("wm", [5, 10, 11, 12, 21, 26, 32, 38, 47])
def test_go_home_docked_via_charge_state(wm: int) -> None:
    """go-home with charge_state>0 -> Docked."""
    result = derive_vacuum_state(props(work_mode=wm, status=0, charge_state=1))
    assert result == VacuumState.DOCKED


# ---------------------------------------------------------------------------
# Paused (work_mode in WORK_MODE_PAUSE)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wm", [4, 9, 27, 31, 37, 82])
def test_paused_modes(wm: int) -> None:
    """all documented pause work_modes map to Paused."""
    assert derive_vacuum_state(props(work_mode=wm)) == VacuumState.PAUSED


@pytest.mark.parametrize("wm", [4, 9, 27, 31, 37, 82])
def test_paused_with_fault_stays_paused(wm: int) -> None:
    """transient fault during pause does not flip to Error."""
    assert derive_vacuum_state(props(work_mode=wm, fault=3)) == VacuumState.PAUSED


# ---------------------------------------------------------------------------
# Idle set (work_mode in WORK_MODE_IDLE)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wm", [0, 14, 23, 29, 35, 40, 85])
def test_idle_no_fault_not_docked(wm: int) -> None:
    """idle + not docked + no fault -> Idle."""
    result = derive_vacuum_state(props(work_mode=wm, status=0, charge_state=0, fault=0))
    assert result == VacuumState.IDLE


@pytest.mark.parametrize("wm", [0, 14, 23, 29, 35, 40, 85])
def test_idle_docked_via_status(wm: int) -> None:
    """idle + status=4 -> Docked (takes priority over fault)."""
    result = derive_vacuum_state(props(work_mode=wm, status=4, charge_state=0, fault=7))
    assert result == VacuumState.DOCKED


@pytest.mark.parametrize("wm", [0, 14, 23, 29, 35, 40, 85])
def test_idle_docked_via_charge_state(wm: int) -> None:
    """idle + charge_state>0 -> Docked."""
    result = derive_vacuum_state(props(work_mode=wm, status=0, charge_state=2, fault=0))
    assert result == VacuumState.DOCKED


@pytest.mark.parametrize("wm", [0, 14, 23, 29, 35, 40, 85])
def test_idle_with_fault_not_docked(wm: int) -> None:
    """idle + not docked + fault -> Error."""
    result = derive_vacuum_state(props(work_mode=wm, status=0, charge_state=0, fault=1))
    assert result == VacuumState.ERROR


# ---------------------------------------------------------------------------
# Docked signal precedence
# ---------------------------------------------------------------------------


def test_docked_status_4_beats_fault() -> None:
    """docked takes priority; no Error when docked with fault."""
    assert derive_vacuum_state(props(work_mode=0, status=4, fault=99)) == VacuumState.DOCKED


def test_docked_charge_state_beats_fault() -> None:
    """charging takes priority; no Error when charging with fault."""
    assert derive_vacuum_state(props(work_mode=0, charge_state=1, fault=99)) == VacuumState.DOCKED


# ---------------------------------------------------------------------------
# Unknown work_mode
# ---------------------------------------------------------------------------


def test_unknown_work_mode_not_docked() -> None:
    """undocumented work_mode + not docked -> Unknown."""
    result = derive_vacuum_state(props(work_mode=999, status=0, charge_state=0))
    assert result == VacuumState.UNKNOWN


def test_unknown_work_mode_docked_via_status() -> None:
    """undocumented work_mode + status=4 -> Docked."""
    assert derive_vacuum_state(props(work_mode=999, status=4, charge_state=0)) == VacuumState.DOCKED


def test_unknown_work_mode_docked_via_charge() -> None:
    """undocumented work_mode + charge_state>0 -> Docked."""
    assert derive_vacuum_state(props(work_mode=999, status=0, charge_state=1)) == VacuumState.DOCKED


# ---------------------------------------------------------------------------
# None work_mode (missing field from adapter)
# ---------------------------------------------------------------------------


def test_none_work_mode_not_docked() -> None:
    """None work_mode treated as unknown, not docked -> Unknown."""
    result = derive_vacuum_state(props(work_mode=None, status=0, charge_state=0))
    assert result == VacuumState.UNKNOWN


def test_none_work_mode_docked() -> None:
    """None work_mode with status=4 -> Docked."""
    assert derive_vacuum_state(props(work_mode=None, status=4)) == VacuumState.DOCKED


# ---------------------------------------------------------------------------
# DeviceProperties defaults and immutability
# ---------------------------------------------------------------------------


def test_device_properties_defaults() -> None:
    """DeviceProperties fields default to None."""
    dp = DeviceProperties()
    assert dp.battery is None
    assert dp.work_mode is None
    assert dp.fault is None


def test_device_properties_frozen() -> None:
    """DeviceProperties is immutable (frozen dataclass)."""
    dp = DeviceProperties(battery=50)
    with pytest.raises(AttributeError):
        dp.battery = 60  # type: ignore[misc]
