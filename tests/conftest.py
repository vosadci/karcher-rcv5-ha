# SPDX-License-Identifier: MIT
"""Shared test fixtures for all test layers."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from custom_components.karcher_home_robots._types import DeviceProperties
from custom_components.karcher_home_robots.adapter import Device, Room
from custom_components.karcher_home_robots.const import DOMAIN
from pytest_homeassistant_custom_component.common import MockConfigEntry

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


# ---------------------------------------------------------------------------
# Integration test helpers shared across multiple test modules
# ---------------------------------------------------------------------------

ENTRY_DATA = {
    "region": "eu",
    "email": "test@example.com",
    "password": "secret",
    "device_id": TEST_DEVICE.device_id,
}


class FakeAdapter:
    """Stand-in adapter used by integration tests.

    All methods are async and return canned values without touching the
    network or the real karcher-home library.
    """

    def __init__(
        self,
        props: DeviceProperties = PROPS_IDLE,
        devices: list[Device] | None = None,
        rooms: list[Room] | None = None,
        authenticate_raises: Exception | None = None,
        fetch_raises: Exception | None = None,
        preference_result: dict[str, Any] | None = None,
    ) -> None:
        self._props = props
        self._devices = devices if devices is not None else [TEST_DEVICE]
        self._rooms = rooms if rooms is not None else TEST_ROOMS
        self._authenticate_raises = authenticate_raises
        self._fetch_raises = fetch_raises
        self._preference_result: dict[str, Any] = (
            preference_result if preference_result is not None else {"rooms": [], "prefer_on": 0}
        )
        self.closed = False
        self.subscribed = False
        self._push_callback: Callable[[DeviceProperties], None] | None = None
        self.commands_sent: list[tuple[str, dict[str, Any]]] = []
        self.properties_set: list[dict[str, Any]] = []
        self.preferences_set: list[tuple[int, list[Any]]] = []
        self.preference_type_set: list[int] = []

    async def async_setup(self) -> None:
        pass

    def get_endpoint_snapshot(self) -> dict[str, str | None]:
        return {"rest_base_url": "https://fake.example.com", "mqtt_url": None}

    async def authenticate(self, email: str, password: str) -> None:
        if self._authenticate_raises is not None:
            raise self._authenticate_raises

    async def get_devices(self) -> list[Device]:
        return self._devices

    async def get_rooms(self, device: Device) -> list[Room]:
        return self._rooms

    async def get_map_snapshot(self, device: Device, cur_path: Any = None) -> None:
        return None

    async def subscribe(
        self,
        device: Device,
        on_push: Callable[[DeviceProperties], None],
        on_path: Any = None,
    ) -> None:
        self.subscribed = True
        self._push_callback = on_push

    async def unsubscribe(self, device: Device) -> None:
        self.subscribed = False

    async def fetch_properties(self, device: Device) -> DeviceProperties:
        if self._fetch_raises is not None:
            raise self._fetch_raises
        return self._props

    async def send_command(
        self,
        device: Device,
        service: str,
        params: dict[str, Any],
    ) -> None:
        self.commands_sent.append((service, dict(params)))

    async def set_property(self, device: Device, params: dict[str, Any]) -> None:
        self.properties_set.append(dict(params))

    async def get_preference(self, device: Device, map_id: int) -> dict[str, Any]:
        return self._preference_result

    async def set_preference(self, device: Device, map_id: int, room_preference: list[Any]) -> None:
        self.preferences_set.append((map_id, list(room_preference)))

    async def set_preference_type(self, device: Device, prefer_type: int) -> None:
        self.preference_type_set.append(prefer_type)

    async def close(self) -> None:
        self.closed = True

    def fire_push(self, props: DeviceProperties) -> None:
        if self._push_callback is not None:
            self._push_callback(props)


def make_entry(**kwargs: Any) -> MockConfigEntry:
    data = {**ENTRY_DATA, **kwargs}
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        unique_id=data["device_id"],
        version=3,
    )


@contextlib.contextmanager
def patch_adapter(fake: FakeAdapter) -> Any:
    """Patch KarcherAdapter in _account_registry (and config_flow) to return fake."""
    factory = lambda *a, **kw: fake  # noqa: E731
    with (
        patch(
            "custom_components.karcher_home_robots._account_registry.KarcherAdapter",
            side_effect=factory,
        ),
        patch(
            "custom_components.karcher_home_robots.config_flow.KarcherAdapter",
            side_effect=factory,
        ),
    ):
        yield
