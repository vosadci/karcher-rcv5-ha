# SPDX-License-Identifier: MIT
"""Sensor entities — battery, cleaning area, cleaning time, consumables, room progress."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfArea, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ._types import DeviceProperties
from .coordinator import KarcherCoordinator
from .entity import KarcherEntity

if TYPE_CHECKING:
    from .adapter import Room

PARALLEL_UPDATES = 0


@dataclass(frozen=True)
class KarcherSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[DeviceProperties], int | float | None] = lambda _: None


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
        icon="mdi:brush",
        # Full life 360 h = 21 600 min; value is minutes elapsed.
        value_fn=lambda d: math.floor(max(0, 21600 - d.main_brush) / 21600 * 100)
        if d.main_brush is not None
        else None,
    ),
    KarcherSensorEntityDescription(
        key="side_brush",
        translation_key="side_brush",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:brush",
        # Full life 180 h = 10 800 min; value is minutes elapsed.
        value_fn=lambda d: math.floor(max(0, 10800 - d.side_brush) / 10800 * 100)
        if d.side_brush is not None
        else None,
    ),
    KarcherSensorEntityDescription(
        key="hypa",
        translation_key="hypa",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:air-filter",
        # Full life 180 h = 10 800 min; value is minutes elapsed.
        value_fn=lambda d: math.floor(max(0, 10800 - d.hypa) / 10800 * 100)
        if d.hypa is not None
        else None,
    ),
    KarcherSensorEntityDescription(
        key="mop_life",
        translation_key="mop_life",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:mop",
        # Full life 180 h = 10 800 min; value is minutes elapsed.
        value_fn=lambda d: math.floor(max(0, 10800 - d.mop_life) / 10800 * 100)
        if d.mop_life is not None
        else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = entry.runtime_data
    async_add_entities(KarcherSensor(coordinator, desc) for desc in _SENSORS)
    async_add_entities([CurrentRoomSensor(coordinator)])

    room_entities: dict[int, RoomProgressSensor] = {}

    def _sync_room_sensors() -> None:
        current_ids = {r.room_id for r in coordinator.rooms}

        # Add sensors for rooms that are new.
        added = [r for r in coordinator.rooms if r.room_id not in room_entities]
        if added:
            new_entities = [RoomProgressSensor(coordinator, r) for r in added]
            for entity in new_entities:
                room_entities[entity.room_id] = entity
            async_add_entities(new_entities)

        # Remove sensors for rooms that no longer exist.
        removed = [rid for rid in list(room_entities) if rid not in current_ids]
        for rid in removed:
            hass.async_create_task(room_entities.pop(rid).async_remove())

        # Update names for rooms that were renamed.
        for room in coordinator.rooms:
            existing = room_entities.get(room.room_id)
            if existing is not None and existing.name != f"{room.name} progress":
                existing.update_name(room.name)

    # Add sensors for rooms already known at setup time.
    _sync_room_sensors()

    # Re-check whenever the coordinator updates (rooms arrive after first map load).
    entry.async_on_unload(coordinator.async_add_listener(_sync_room_sensors))


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
    def native_value(self) -> int | float | None:
        data = self._data
        if data is None:
            return None
        return self.entity_description.value_fn(data)


class RoomProgressSensor(KarcherEntity, SensorEntity):
    """Per-room cleaning progress sensor (0-100 %)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:progress-check"

    def __init__(self, coordinator: KarcherCoordinator, room: Room) -> None:
        super().__init__(coordinator)
        self._room_id: int = room.room_id
        self._attr_unique_id = f"{coordinator.device.device_id}_room_progress_{room.room_id}"
        self._attr_name = f"{room.name} progress"

    @property
    def room_id(self) -> int:
        return self._room_id

    def update_name(self, room_name: str) -> None:
        self._attr_name = f"{room_name} progress"
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        return self.coordinator.room_progress.get(self._room_id)


class CurrentRoomSensor(KarcherEntity, SensorEntity):
    """Sensor reporting the name of the room the robot is currently in.

    Used by HAMH as the `currentRoomEntity` to advance per-room progress rings
    in Apple Home in real time.
    """

    _attr_translation_key = "current_room"
    _attr_icon = "mdi:robot-vacuum"

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_current_room"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.current_room_name
