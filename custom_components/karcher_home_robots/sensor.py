# SPDX-License-Identifier: MIT
"""Sensor entities — battery, cleaning area, cleaning time.

Covers: FR-SE-1, FR-SE-2, FR-SE-3, FR-SE-4
"""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfArea, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import KarcherCoordinator
from .entity import KarcherEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from a config entry."""
    coordinator: KarcherCoordinator = entry.runtime_data
    async_add_entities(
        [
            KarcherBatterySensor(coordinator),
            KarcherCleaningAreaSensor(coordinator),
            KarcherCleaningTimeSensor(coordinator),
        ]
    )


class KarcherBatterySensor(KarcherEntity, SensorEntity):
    """Battery percentage sensor (FR-SE-1).

    Separate entity because HA 2026.8 removed battery from VacuumEntity.
    """

    _attr_translation_key = "battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        device = coordinator.device
        self._attr_unique_id = f"{device.device_id}_battery"

    @property
    def native_value(self) -> int | None:
        """Return the battery level in percent."""
        data = self._data
        if data is None:
            return None
        return data.battery


class KarcherCleaningAreaSensor(KarcherEntity, SensorEntity):
    """Cleaning area sensor in m² (FR-SE-2).

    Raw value from device is in units of 0.01 m²; divide by 100.
    Source: doc/PROTOCOL.md §6, confirmed 2026-03-28.
    """

    _attr_translation_key = "cleaning_area"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.AREA
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfArea.SQUARE_METERS

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        device = coordinator.device
        self._attr_unique_id = f"{device.device_id}_cleaning_area"

    @property
    def native_value(self) -> float | None:
        """Return the area cleaned in m²."""
        data = self._data
        if data is None or data.cleaning_area is None:
            return None
        return data.cleaning_area / 100.0


class KarcherCleaningTimeSensor(KarcherEntity, SensorEntity):
    """Cleaning time sensor in minutes (FR-SE-3)."""

    _attr_translation_key = "cleaning_time"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        device = coordinator.device
        self._attr_unique_id = f"{device.device_id}_cleaning_time"

    @property
    def native_value(self) -> int | None:
        """Return the cleaning time in minutes."""
        data = self._data
        if data is None:
            return None
        return data.cleaning_time
