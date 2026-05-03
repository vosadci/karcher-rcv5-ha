# SPDX-License-Identifier: MIT
"""Sensor entities — battery, cleaning area, cleaning time."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = entry.runtime_data
    async_add_entities(KarcherSensor(coordinator, desc) for desc in _SENSORS)


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
