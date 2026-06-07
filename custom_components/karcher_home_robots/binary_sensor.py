# SPDX-License-Identifier: MIT
"""Binary sensor — robot error indicator."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KarcherCoordinator, VacuumState
from .entity import KarcherEntity

PARALLEL_UPDATES = 0

# FAULT_ROBOT_CHARGE_FINISH — robot is docked and fully charged, no longer drawing
# current. Treat as "not charging" so the binary sensor matches the app's UI.
# See doc/PROTOCOL.md §charge_state and APK RobotError.java:45.
_FAULT_CHARGE_FINISHED = 2105


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = entry.runtime_data
    async_add_entities([KarcherErrorSensor(coordinator), KarcherChargingSensor(coordinator)])


class KarcherErrorSensor(KarcherEntity, BinarySensorEntity):
    """Robot error indicator.

    On only when vacuum_state == ERROR (idle + faulted + not docked).
    Transient faults during cleaning or returning do not flip this sensor.
    """

    _attr_translation_key = "error"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_error"

    @property
    def is_on(self) -> bool | None:
        if self._data is None:
            return None
        return self.coordinator.vacuum_state == VacuumState.ERROR


class KarcherChargingSensor(KarcherEntity, BinarySensorEntity):
    _attr_translation_key = "charging"
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_charging"

    @property
    def is_on(self) -> bool | None:
        data = self._data
        if data is None:
            return None
        return data.charge_state == 1 and data.fault != _FAULT_CHARGE_FINISHED
