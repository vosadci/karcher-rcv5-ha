# SPDX-License-Identifier: MIT
"""Shared test fixtures for all test layers."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from custom_components.karcher_home_robots._types import DeviceProperties
from custom_components.karcher_home_robots.adapter import Device, Room

# ---------------------------------------------------------------------------
# DeviceProperties helpers
# ---------------------------------------------------------------------------


def make_props(**kwargs: Any) -> DeviceProperties:
    """Build a DeviceProperties with all optional fields defaulting to None."""
    defaults: dict[str, Any] = {
        "battery": None,
        "cleaning_area": None,
        "cleaning_time": None,
        "work_mode": None,
        "status": None,
        "charge_state": None,
        "fault": None,
        "wind": None,
        "water": None,
        "mode": None,
        "tank_state": None,
        "cloth_state": None,
        "current_map_id": None,
    }
    defaults.update(kwargs)
    return DeviceProperties(**defaults)


PROPS_IDLE = make_props(work_mode=0, status=0, charge_state=0, fault=0, battery=80)
PROPS_CLEANING = make_props(work_mode=1, status=0, charge_state=0, fault=0, battery=70)
PROPS_PAUSED = make_props(work_mode=4, status=0, charge_state=0, fault=0, battery=65)
PROPS_DOCKED = make_props(work_mode=0, status=4, charge_state=1, fault=0, battery=95)
PROPS_RETURNING = make_props(work_mode=5, status=0, charge_state=0, fault=0, battery=60)
PROPS_ERROR = make_props(work_mode=0, status=0, charge_state=0, fault=1, battery=50)


# ---------------------------------------------------------------------------
# Adapter Device / Room
# ---------------------------------------------------------------------------


TEST_DEVICE = Device(
    device_id="test-device-id-1",
    sn="SN001",
    product_id="1540149850806333440",
    nickname="Test Robot",
    mac="AA:BB:CC:DD:EE:FF",
    product_mode_code="CRL350",
)

TEST_ROOMS = [
    Room(room_id=1, name="Living Room"),
    Room(room_id=2, name="Bedroom"),
]


# ---------------------------------------------------------------------------
# Fake hass for non-HA tests
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_hass() -> MagicMock:
    """Return a lightweight hass mock with async executor support."""
    hass = MagicMock()

    async def async_add_executor_job(func: Any, *args: Any) -> Any:
        return func(*args)

    hass.async_add_executor_job = async_add_executor_job
    return hass
