# SPDX-License-Identifier: MIT
"""Sensor entities — battery, cleaning area, cleaning time, consumables, wash station."""

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
from .entity import KarcherEntity, KarcherHeldEntity
from .state import STATION_PHASE_OPTIONS, derive_station_phase, drying_seconds_left

PARALLEL_UPDATES = 0


@dataclass(frozen=True)
class KarcherSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[DeviceProperties], int | float | str | None] = lambda _: None
    extra_fn: Callable[[DeviceProperties], dict[str, Any] | None] = field(default=lambda _: None)


def _life_pct(elapsed: int | None, full_life: int) -> int | None:
    """Remaining consumable life as a percentage; *full_life* is total minutes."""
    if elapsed is None:
        return None
    return math.floor(max(0, full_life - elapsed) / full_life * 100)


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
        value_fn=lambda d: _life_pct(d.main_brush, 21600),
    ),
    KarcherSensorEntityDescription(
        key="side_brush",
        translation_key="side_brush",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        # Full life 180 h = 10 800 min; value is minutes elapsed.
        value_fn=lambda d: _life_pct(d.side_brush, 10800),
    ),
    KarcherSensorEntityDescription(
        key="hypa",
        translation_key="hypa",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        # Full life 180 h = 10 800 min; value is minutes elapsed.
        value_fn=lambda d: _life_pct(d.hypa, 10800),
    ),
    KarcherSensorEntityDescription(
        key="mop_life",
        translation_key="mop_life",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        # Full life 180 h = 10 800 min; value is minutes elapsed.
        value_fn=lambda d: _life_pct(d.mop_life, 10800),
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


_CLEANING_TIME_DESC = next(d for d in _SENSORS if d.key == "cleaning_time")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = entry.runtime_data
    async_add_entities(
        CleaningTimeSensor(coordinator)
        if desc.key == "cleaning_time"
        else KarcherSensor(coordinator, desc)
        for desc in _SENSORS
    )
    async_add_entities(
        [
            CurrentRoomSensor(coordinator),
            StationStatusSensor(coordinator),
            DryingTimeLeftSensor(coordinator),
        ]
    )


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


class CleaningTimeSensor(KarcherSensor):
    """cleaning_time sensor that also exposes finished_at from the coordinator."""

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator, _CLEANING_TIME_DESC)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        ts = self.coordinator.last_clean_finished_at
        if ts is None:
            return None
        return {"finished_at": ts.isoformat()}


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


class _StationSensor(KarcherHeldEntity, SensorEntity):
    """Wash-station sensor that holds a drop to its rest value (STATION_BLIP_HOLD)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: KarcherCoordinator, key: str) -> None:
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.device.device_id}_{key}"
        super().__init__(coordinator)

    def _is_rest(self, value: int | str | None) -> bool:
        raise NotImplementedError

    def _holds(self, new: int | str | None, shown: int | str | None) -> bool:
        return self._is_rest(new) and not self._is_rest(shown)

    @property
    def native_value(self) -> int | str | None:
        shown: int | str | None = self._shown
        return shown


class StationStatusSensor(_StationSensor):
    """What the wash station is doing: washing mops, drying, emptying dust."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATION_PHASE_OPTIONS

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator, "station_status")

    def _value(self, data: DeviceProperties) -> str | None:
        return derive_station_phase(data)

    def _is_rest(self, value: int | str | None) -> bool:
        return value in (None, "idle")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self._data
        if data is None or data.station_act is None:
            return None
        return {"raw": data.station_act}


class DryingTimeLeftSensor(_StationSensor):
    """Time left until the wash station finishes drying the mops."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_suggested_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator, "drying_time_left")

    def _value(self, data: DeviceProperties) -> int | None:
        return drying_seconds_left(data)

    def _is_rest(self, value: int | str | None) -> bool:
        return value in (None, 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self._data
        if data is None or data.work_time_total is None:
            return None
        return {"total": data.work_time_total, "type": data.work_time_type}
