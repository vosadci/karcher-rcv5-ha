# SPDX-License-Identifier: MIT
"""Binary sensor — robot error indicator.

Covers: FR-BS-1, FR-BS-2, FR-BS-3
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import KarcherCoordinator, VacuumState
from .entity import KarcherEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities from a config entry."""
    coordinator: KarcherCoordinator = entry.runtime_data
    async_add_entities([KarcherErrorSensor(coordinator)])


class KarcherErrorSensor(KarcherEntity, BinarySensorEntity):
    """Robot error indicator.

    Is 'on' only when the robot is idle, faulted, and not docked
    (vacuum_state == Error). Transient faults during cleaning or
    returning do NOT flip this sensor (FR-BS-2).

    Covers: FR-BS-1, FR-BS-2, FR-BS-3
    """

    _attr_translation_key = "error"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:robot-vacuum-alert"

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        device = coordinator._device
        self._attr_unique_id = f"{device.device_id}_error"

    @property
    def is_on(self) -> bool | None:
        """Return True when the robot is in Error state."""
        if self._data is None:
            return None
        return self.coordinator.vacuum_state == VacuumState.ERROR
