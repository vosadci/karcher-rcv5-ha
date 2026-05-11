# SPDX-License-Identifier: MIT
"""Unit tests for entity unique_id shape.

Asserts that every entity class produces the canonical unique_id string.
If any unique_id format changes here, entity IDs for existing installations
will break — treat any failure as a breaking change.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from custom_components.karcher_home_robots.binary_sensor import KarcherChargingSensor, KarcherErrorSensor
from custom_components.karcher_home_robots.select import (
    KarcherCleaningModeSelect,
    KarcherRoomSelect,
    KarcherWaterLevelSelect,
)
from custom_components.karcher_home_robots.sensor import _SENSORS, KarcherSensor
from custom_components.karcher_home_robots.vacuum import KarcherVacuum
from tests.conftest import TEST_DEVICE

# Canonical unique_id list.
# Any change here is a breaking change for existing installations.
_EXPECTED: dict[str, str] = {
    "vacuum": f"{TEST_DEVICE.device_id}_vacuum",
    "battery": f"{TEST_DEVICE.device_id}_battery",
    "cleaning_area": f"{TEST_DEVICE.device_id}_cleaning_area",
    "cleaning_time": f"{TEST_DEVICE.device_id}_cleaning_time",
    "error": f"{TEST_DEVICE.device_id}_error",
    "charging": f"{TEST_DEVICE.device_id}_charging",
    "room": f"{TEST_DEVICE.device_id}_room",
    "cleaning_mode": f"{TEST_DEVICE.device_id}_cleaning_mode",
    "water_level": f"{TEST_DEVICE.device_id}_water_level",
    "main_brush": f"{TEST_DEVICE.device_id}_main_brush",
    "side_brush": f"{TEST_DEVICE.device_id}_side_brush",
    "hypa": f"{TEST_DEVICE.device_id}_hypa",
    "mop_life": f"{TEST_DEVICE.device_id}_mop_life",
}

_SENSOR_DESC_BY_KEY = {desc.key: desc for desc in _SENSORS}


def _make_coordinator() -> MagicMock:
    coord = MagicMock()
    coord.device = TEST_DEVICE
    coord.rooms = []
    coord.data = None
    return coord


def _make_entity(key: str) -> object:
    coord = _make_coordinator()
    if key == "vacuum":
        return KarcherVacuum(coord)
    if key == "error":
        return KarcherErrorSensor(coord)
    if key == "charging":
        return KarcherChargingSensor(coord)
    if key == "room":
        return KarcherRoomSelect(coord)
    if key == "cleaning_mode":
        return KarcherCleaningModeSelect(coord)
    if key == "water_level":
        return KarcherWaterLevelSelect(coord)
    return KarcherSensor(coord, _SENSOR_DESC_BY_KEY[key])


@pytest.mark.parametrize("key,expected", list(_EXPECTED.items()))
def test_unique_id(key: str, expected: str) -> None:
    entity = _make_entity(key)
    assert entity._attr_unique_id == expected  # type: ignore[union-attr]
