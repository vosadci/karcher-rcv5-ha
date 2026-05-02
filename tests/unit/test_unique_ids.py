# SPDX-License-Identifier: MIT
"""Unit tests for entity unique_id shape (FR-MG-1).

Asserts that every entity class produces the canonical unique_id string.
This is a migration regression guard: if any unique_id format changes, this
test fails, signalling that async_migrate_entry must be updated in the same PR.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.karcher_home_robots.binary_sensor import KarcherErrorSensor
from custom_components.karcher_home_robots.select import (
    KarcherCleaningModeSelect,
    KarcherRoomSelect,
    KarcherWaterLevelSelect,
)
from custom_components.karcher_home_robots.sensor import (
    KarcherBatterySensor,
    KarcherCleaningAreaSensor,
    KarcherCleaningTimeSensor,
)
from custom_components.karcher_home_robots.vacuum import KarcherVacuum
from tests.conftest import TEST_DEVICE

# Canonical unique_id list — frozen per FR-MG-1.
# Any change here is a breaking migration change; bump async_migrate_entry.
_EXPECTED: dict[str, str] = {
    "vacuum": f"{TEST_DEVICE.device_id}_vacuum",
    "battery": f"{TEST_DEVICE.device_id}_battery",
    "cleaning_area": f"{TEST_DEVICE.device_id}_cleaning_area",
    "cleaning_time": f"{TEST_DEVICE.device_id}_cleaning_time",
    "error": f"{TEST_DEVICE.device_id}_error",
    "room": f"{TEST_DEVICE.device_id}_room",
    "cleaning_mode": f"{TEST_DEVICE.device_id}_cleaning_mode",
    "water_level": f"{TEST_DEVICE.device_id}_water_level",
}


def _make_coordinator() -> MagicMock:
    coord = MagicMock()
    coord._device = TEST_DEVICE
    coord.rooms = []
    coord.data = None
    return coord


def test_vacuum_unique_id() -> None:
    """Covers: FR-MG-1"""
    entity = KarcherVacuum(_make_coordinator())
    assert entity._attr_unique_id == _EXPECTED["vacuum"]


def test_battery_unique_id() -> None:
    """Covers: FR-MG-1"""
    entity = KarcherBatterySensor(_make_coordinator())
    assert entity._attr_unique_id == _EXPECTED["battery"]


def test_cleaning_area_unique_id() -> None:
    """Covers: FR-MG-1"""
    entity = KarcherCleaningAreaSensor(_make_coordinator())
    assert entity._attr_unique_id == _EXPECTED["cleaning_area"]


def test_cleaning_time_unique_id() -> None:
    """Covers: FR-MG-1"""
    entity = KarcherCleaningTimeSensor(_make_coordinator())
    assert entity._attr_unique_id == _EXPECTED["cleaning_time"]


def test_error_sensor_unique_id() -> None:
    """Covers: FR-MG-1"""
    entity = KarcherErrorSensor(_make_coordinator())
    assert entity._attr_unique_id == _EXPECTED["error"]


def test_room_select_unique_id() -> None:
    """Covers: FR-MG-1"""
    entity = KarcherRoomSelect(_make_coordinator())
    assert entity._attr_unique_id == _EXPECTED["room"]


def test_cleaning_mode_unique_id() -> None:
    """Covers: FR-MG-1"""
    entity = KarcherCleaningModeSelect(_make_coordinator())
    assert entity._attr_unique_id == _EXPECTED["cleaning_mode"]


def test_water_level_unique_id() -> None:
    """Covers: FR-MG-1"""
    entity = KarcherWaterLevelSelect(_make_coordinator())
    assert entity._attr_unique_id == _EXPECTED["water_level"]
