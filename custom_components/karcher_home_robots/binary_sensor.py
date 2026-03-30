"""Kärcher binary sensor entities."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, STATUS_DOCKED, WORK_MODE_IDLE
from .coordinator import KarcherCoordinator
from .entity import KarcherEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([KarcherErrorBinarySensor(coordinator)])


class KarcherErrorBinarySensor(KarcherEntity, BinarySensorEntity):
    """Error (fault) binary sensor for a Kärcher robot vacuum."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_name = "Error"

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_error"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        props = self.coordinator.data
        if props.fault == 0:
            return False
        # Non-zero fault can coexist with normal operation (transient warnings
        # during cleaning or charging). Only surface as a real error when the
        # robot is idle and not docked.
        return props.work_mode in WORK_MODE_IDLE and props.status != STATUS_DOCKED
