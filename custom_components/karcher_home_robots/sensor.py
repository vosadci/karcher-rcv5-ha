# SPDX-License-Identifier: MIT
"""Sensor entities — battery, cleaning area, cleaning time, consumables."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfArea, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._types import DeviceProperties
from .const import FAULT_CODE_DESCRIPTIONS
from .coordinator import KarcherCoordinator
from .entity import KarcherEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True)
class KarcherSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[DeviceProperties], int | float | str | None] = lambda _: None
    extra_fn: Callable[[DeviceProperties], dict[str, Any] | None] = field(default=lambda _: None)


_SENSORS: tuple[KarcherSensorEntityDescription, ...] = (
    KarcherSensorEntityDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda d: d.battery,
    ),
    KarcherSensorEntityDescription(
        key="cleaning_area",
        translation_key="cleaning_area",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.AREA,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        # Raw value is in units of 0.01 m²; divide by 100 for m².
        # Source: doc/PROTOCOL.md §6, confirmed 2026-03-28.
        value_fn=lambda d: d.cleaning_area / 100.0 if d.cleaning_area is not None else None,
    ),
    KarcherSensorEntityDescription(
        key="cleaning_time",
        translation_key="cleaning_time",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda d: d.cleaning_time,
    ),
    KarcherSensorEntityDescription(
        key="main_brush",
        translation_key="main_brush",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        # Full life 360 h = 21 600 min; value is minutes elapsed.
        value_fn=lambda d: (
            math.floor(max(0, 21600 - d.main_brush) / 21600 * 100)
            if d.main_brush is not None
            else None
        ),
    ),
    KarcherSensorEntityDescription(
        key="side_brush",
        translation_key="side_brush",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        # Full life 180 h = 10 800 min; value is minutes elapsed.
        value_fn=lambda d: (
            math.floor(max(0, 10800 - d.side_brush) / 10800 * 100)
            if d.side_brush is not None
            else None
        ),
    ),
    KarcherSensorEntityDescription(
        key="hypa",
        translation_key="hypa",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        # Full life 180 h = 10 800 min; value is minutes elapsed.
        value_fn=lambda d: (
            math.floor(max(0, 10800 - d.hypa) / 10800 * 100) if d.hypa is not None else None
        ),
    ),
    KarcherSensorEntityDescription(
        key="mop_life",
        translation_key="mop_life",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        # Full life 180 h = 10 800 min; value is minutes elapsed.
        value_fn=lambda d: (
            math.floor(max(0, 10800 - d.mop_life) / 10800 * 100) if d.mop_life is not None else None
        ),
    ),
    KarcherSensorEntityDescription(
        key="fault_code",
        translation_key="fault_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=list(FAULT_CODE_DESCRIPTIONS.values()),
        value_fn=lambda d: FAULT_CODE_DESCRIPTIONS.get(d.fault) if d.fault is not None else None,
        extra_fn=lambda d: {"raw": d.fault} if d.fault is not None else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = entry.runtime_data
    async_add_entities(KarcherSensor(coordinator, desc) for desc in _SENSORS)
    async_add_entities([CurrentRoomSensor(coordinator)])


class KarcherSensor(KarcherEntity, SensorEntity):
    entity_description: KarcherSensorEntityDescription

    def __init__(
        self,
        coordinator: KarcherCoordinator,
        description: KarcherSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device.device_id}_{description.key}"

    @property
    def native_value(self) -> int | float | str | None:
        data = self._data
        if data is None:
            return None
        return self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self._data
        if data is None:
            return None
        return self.entity_description.extra_fn(data)


class CurrentRoomSensor(KarcherEntity, SensorEntity):
    """Sensor reporting the name of the room the robot is currently in.

    Used by HAMH as the `currentRoomEntity` to advance per-room progress rings
    in Apple Home in real time.
    """

    _attr_translation_key = "current_room"

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_current_room"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.current_room_name
