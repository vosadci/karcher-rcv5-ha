# SPDX-License-Identifier: MIT
"""Binary sensor — robot error indicator."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import NON_ERROR_FAULT_CODES
from .coordinator import KarcherCoordinator
from .entity import KarcherEntity
from .state import VacuumState

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
    async_add_entities(
        [
            KarcherErrorSensor(coordinator),
            KarcherChargingSensor(coordinator),
            KarcherConnectivitySensor(coordinator),
            KarcherStationAttachedSensor(coordinator),
            KarcherEmptyingSensor(coordinator),
        ]
    )


class KarcherErrorSensor(KarcherEntity, BinarySensorEntity):
    """Robot error indicator.

    On when idle+faulted+not-docked (ERROR), or when PAUSED with a genuine
    fault. PAUSE is included because a real fault (e.g. a bumper/collision
    sensor block) makes the robot self-pause rather than going idle — that's
    the persistent-fault signal there, distinct from a transient bump that
    doesn't stop the robot (device-verified 2026-06-24). CLEANING/RETURNING/
    DOCKED stay excluded (FR-BS-2) — no evidence those need the same
    treatment, and most fault values seen there are routine lifecycle
    notifications, not failures. The 21xx lifecycle range is always excluded.
    """

    _attr_translation_key = "error"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_error"

    @property
    def is_on(self) -> bool | None:
        data = self._data
        if data is None:
            return None
        if not data.fault or data.fault in NON_ERROR_FAULT_CODES:
            return False
        return self.coordinator.vacuum_state in (VacuumState.ERROR, VacuumState.PAUSED)


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


class KarcherConnectivitySensor(KarcherEntity, BinarySensorEntity):
    _attr_translation_key = "connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_connectivity"

    @property
    def available(self) -> bool:
        # Always available — the point of this sensor is to report unreachability.
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_robot_reachable


class KarcherStationAttachedSensor(KarcherEntity, BinarySensorEntity):
    """Whether a Suction Station (vs. a plain charging dock) is attached.

    charge_station_type is poll-only, not pushed on change (doc/PROTOCOL.md
    §15) — refreshes on the coordinator's normal poll cadence, not instantly.
    """

    _attr_translation_key = "station_attached"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_station_attached"

    @property
    def is_on(self) -> bool | None:
        data = self._data
        if data is None or data.charge_station_type is None:
            return None
        return data.charge_station_type != 0


class KarcherEmptyingSensor(KarcherEntity, BinarySensorEntity):
    """Whether the Suction Station is actively emptying the dust container."""

    _attr_translation_key = "emptying"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_emptying"

    @property
    def is_on(self) -> bool | None:
        data = self._data
        if data is None or data.dust_action is None:
            return None
        return data.dust_action != 0
