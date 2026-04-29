# SPDX-License-Identifier: MIT
"""Select entities — room, cleaning mode, water level.

Covers: FR-SL-1, FR-SL-2, FR-SL-3, FR-SL-4, FR-SL-5, FR-SL-6, FR-SL-7, FR-AH-2
"""

from __future__ import annotations

import logging
from typing import Final

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CLEANING_MODE_MOP, CLEANING_MODE_VACUUM, CLEANING_MODE_VACUUM_AND_MOP
from .coordinator import KarcherCoordinator
from .entity import KarcherEntity

_LOGGER = logging.getLogger(__name__)

# Cleaning-mode select options (FR-SL-4)
CLEANING_MODE_VACUUM_LABEL: Final = "Vacuum"
CLEANING_MODE_VACUUM_AND_MOP_LABEL: Final = "Vacuum & Mop"
CLEANING_MODE_MOP_LABEL: Final = "Mop"

_CLEANING_MODE_TO_VALUE: dict[str, int] = {
    CLEANING_MODE_VACUUM_LABEL: CLEANING_MODE_VACUUM,
    CLEANING_MODE_VACUUM_AND_MOP_LABEL: CLEANING_MODE_VACUUM_AND_MOP,
    CLEANING_MODE_MOP_LABEL: CLEANING_MODE_MOP,
}
_CLEANING_MODE_TO_LABEL: dict[int, str] = {v: k for k, v in _CLEANING_MODE_TO_VALUE.items()}

# Water-level select options (FR-SL-5)
WATER_LOW_LABEL: Final = "Low"
WATER_MEDIUM_LABEL: Final = "Medium"
WATER_HIGH_LABEL: Final = "High"

_WATER_LEVEL_TO_VALUE: dict[str, int] = {
    WATER_LOW_LABEL: 1,
    WATER_MEDIUM_LABEL: 2,
    WATER_HIGH_LABEL: 3,
}
_WATER_LEVEL_TO_LABEL: dict[int, str] = {v: k for k, v in _WATER_LEVEL_TO_VALUE.items()}

# Room select sentinel (FR-SL-1)
ALL_ROOMS_LABEL: Final = "All rooms"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities from a config entry."""
    coordinator: KarcherCoordinator = entry.runtime_data
    async_add_entities(
        [
            KarcherRoomSelect(coordinator),
            KarcherCleaningModeSelect(coordinator),
            KarcherWaterLevelSelect(coordinator),
        ]
    )


class KarcherRoomSelect(KarcherEntity, SelectEntity):
    """Room select: All rooms | per-room name (FR-SL-1..3, FR-SL-7).

    Options are derived from coordinator.rooms at render time so they
    update automatically when FR-SL-7 triggers a room refresh.
    Unavailable when no rooms are known (FR-SL-2).
    Selection is stored on the coordinator and consumed by async_start (FR-SL-3).
    """

    _attr_translation_key = "room"

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        device = coordinator._device
        self._attr_unique_id = f"{device.device_id}_room"

    @property
    def available(self) -> bool:
        """Unavailable when no rooms are known (FR-SL-2)."""
        return bool(self.coordinator.rooms)

    @property
    def options(self) -> list[str]:
        """Return All rooms plus each room name (FR-SL-1)."""
        return [ALL_ROOMS_LABEL] + [r.name for r in self.coordinator.rooms]

    @property
    def current_option(self) -> str | None:
        """Return the currently selected room name, or All rooms."""
        selected_id = self.coordinator.get_selected_room_id()
        if selected_id is None:
            return ALL_ROOMS_LABEL
        for room in self.coordinator.rooms:
            if room.room_id == selected_id:
                return room.name
        return ALL_ROOMS_LABEL

    async def async_select_option(self, option: str) -> None:
        """Store the selected room on the coordinator (FR-SL-3)."""
        if option == ALL_ROOMS_LABEL:
            self.coordinator.set_selected_room_id(None)
            return
        for room in self.coordinator.rooms:
            if room.name == option:
                self.coordinator.set_selected_room_id(room.room_id)
                return
        _LOGGER.warning("Room %r not found in room list; ignoring", option)


class KarcherCleaningModeSelect(KarcherEntity, SelectEntity):
    """Cleaning-mode select: Vacuum / Vacuum & Mop / Mop (FR-SL-4).

    Writes prop.set {"mode": 0|1|2} immediately on selection.
    """

    _attr_translation_key = "cleaning_mode"
    _attr_options: list[str] = [  # noqa: RUF012
        CLEANING_MODE_VACUUM_LABEL,
        CLEANING_MODE_VACUUM_AND_MOP_LABEL,
        CLEANING_MODE_MOP_LABEL,
    ]

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        device = coordinator._device
        self._attr_unique_id = f"{device.device_id}_cleaning_mode"

    @property
    def current_option(self) -> str | None:
        """Return the current cleaning mode as a label."""
        data = self._data
        if data is None or data.mode is None:
            return None
        return _CLEANING_MODE_TO_LABEL.get(data.mode)

    async def async_select_option(self, option: str) -> None:
        """Write the selected mode via prop.set (FR-SL-4)."""
        value = _CLEANING_MODE_TO_VALUE.get(option)
        if value is None:
            _LOGGER.warning("Unknown cleaning mode %r; ignoring", option)
            return
        await self.coordinator.async_set_property({"mode": value})


class KarcherWaterLevelSelect(KarcherEntity, SelectEntity):
    """Water-level select: Low / Medium / High (FR-SL-5).

    Disabled by default (FR-SL-6). Unavailable when mode = Vacuum-only.
    """

    _attr_translation_key = "water_level"
    _attr_entity_registry_enabled_default = False
    _attr_options: list[str] = [WATER_LOW_LABEL, WATER_MEDIUM_LABEL, WATER_HIGH_LABEL]  # noqa: RUF012

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        device = coordinator._device
        self._attr_unique_id = f"{device.device_id}_water_level"

    @property
    def available(self) -> bool:
        """Unavailable when coordinator data is absent or mode is Vacuum-only (FR-SL-5)."""
        data = self._data
        if data is None:
            return False
        return data.mode != CLEANING_MODE_VACUUM

    @property
    def current_option(self) -> str | None:
        """Return the current water level as a label."""
        data = self._data
        if data is None or data.water is None:
            return None
        return _WATER_LEVEL_TO_LABEL.get(data.water)

    async def async_select_option(self, option: str) -> None:
        """Write the selected water level via prop.set."""
        value = _WATER_LEVEL_TO_VALUE.get(option)
        if value is None:
            _LOGGER.warning("Unknown water level %r; ignoring", option)
            return
        await self.coordinator.async_set_property({"water": value})
