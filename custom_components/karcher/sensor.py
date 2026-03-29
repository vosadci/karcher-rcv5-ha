"""Kärcher sensor entities."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfArea, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import KarcherCoordinator
from .entity import KarcherEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        KarcherBatterySensor(coordinator),
        KarcherCleaningAreaSensor(coordinator),
        KarcherCleaningTimeSensor(coordinator),
    ])


class KarcherBatterySensor(KarcherEntity, SensorEntity):
    """Battery level sensor for a Kärcher robot vacuum."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 0
    _attr_name = "Battery"

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_battery"

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.quantity


class KarcherCleaningAreaSensor(KarcherEntity, SensorEntity):
    """Cleaning area sensor for a Kärcher robot vacuum."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfArea.SQUARE_METERS
    _attr_suggested_display_precision = 1
    _attr_name = "Cleaning Area"

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_cleaning_area"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.cleaning_area


class KarcherCleaningTimeSensor(KarcherEntity, SensorEntity):
    """Cleaning time sensor for a Kärcher robot vacuum."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_suggested_display_precision = 0
    _attr_name = "Cleaning Time"

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_cleaning_time"

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.cleaning_time
