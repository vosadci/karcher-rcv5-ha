# SPDX-License-Identifier: MIT
"""Select entities — room, cleaning mode, water level."""

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

PARALLEL_UPDATES = 1

CLEANING_MODE_VACUUM_LABEL: Final = "vacuum"
CLEANING_MODE_VACUUM_AND_MOP_LABEL: Final = "vacuum_and_mop"
CLEANING_MODE_MOP_LABEL: Final = "mop"

_CLEANING_MODE_TO_VALUE: dict[str, int] = {
    CLEANING_MODE_VACUUM_LABEL: CLEANING_MODE_VACUUM,
    CLEANING_MODE_VACUUM_AND_MOP_LABEL: CLEANING_MODE_VACUUM_AND_MOP,
    CLEANING_MODE_MOP_LABEL: CLEANING_MODE_MOP,
}
_CLEANING_MODE_TO_LABEL: dict[int, str] = {v: k for k, v in _CLEANING_MODE_TO_VALUE.items()}

WATER_LOW_LABEL: Final = "low"
WATER_MEDIUM_LABEL: Final = "medium"
WATER_HIGH_LABEL: Final = "high"

_WATER_LEVEL_TO_VALUE: dict[str, int] = {
    WATER_LOW_LABEL: 1,
    WATER_MEDIUM_LABEL: 2,
    WATER_HIGH_LABEL: 3,
}
_WATER_LEVEL_TO_LABEL: dict[int, str] = {v: k for k, v in _WATER_LEVEL_TO_VALUE.items()}

# Translation key listed in strings.json entity.select.room.state — HA renders it localised.
ALL_ROOMS_LABEL: Final = "all_rooms"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = entry.runtime_data
    async_add_entities(
        [
            KarcherRoomSelect(coordinator),
            KarcherCleaningModeSelect(coordinator),
            KarcherWaterLevelSelect(coordinator),
        ]
    )


class KarcherRoomSelect(KarcherEntity, SelectEntity):
    """Room select: All rooms | per-room name.

    Options derive from coordinator.rooms at render time — updates automatically
    when a map-ID change triggers a room refresh. Unavailable when no rooms are known.
    Selection is stored on the coordinator and consumed by async_start.
    """

    _attr_translation_key = "room"

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        device = coordinator.device
        self._attr_unique_id = f"{device.device_id}_room"

    @property
    def available(self) -> bool:
        return bool(self.coordinator.rooms)

    def _name_to_id(self) -> dict[str, int]:
        # Known limitation: two rooms with identical names collapse to one option string;
        # first match wins. options/current_option use the same ordering, so selection
        # remains self-consistent even when names collide.
        mapping: dict[str, int] = {}
        for room in self.coordinator.rooms:
            if room.name in mapping:
                _LOGGER.warning(
                    "Duplicate room name %r (IDs %d and %d); first match used",
                    room.name,
                    mapping[room.name],
                    room.room_id,
                )
            else:
                mapping[room.name] = room.room_id
        return mapping

    @property
    def options(self) -> list[str]:
        return [ALL_ROOMS_LABEL] + [r.name for r in self.coordinator.rooms]

    @property
    def current_option(self) -> str | None:
        selected_id = self.coordinator.get_selected_room_id()
        if selected_id is None:
            return ALL_ROOMS_LABEL
        for room in self.coordinator.rooms:
            if room.room_id == selected_id:
                return room.name
        return ALL_ROOMS_LABEL

    async def async_select_option(self, option: str) -> None:
        if option == ALL_ROOMS_LABEL:
            self.coordinator.set_selected_room_id(None)
        else:
            room_id = self._name_to_id().get(option)
            if room_id is None:
                _LOGGER.warning("Room %r not found in room list; ignoring", option)
                return
            self.coordinator.set_selected_room_id(room_id)
        self.async_write_ha_state()


class KarcherCleaningModeSelect(KarcherEntity, SelectEntity):
    """Cleaning-mode select: Vacuum / Vacuum & Mop / Mop."""

    _attr_translation_key = "cleaning_mode"
    _attr_options: list[str] = [  # noqa: RUF012
        CLEANING_MODE_VACUUM_LABEL,
        CLEANING_MODE_VACUUM_AND_MOP_LABEL,
        CLEANING_MODE_MOP_LABEL,
    ]

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        device = coordinator.device
        self._attr_unique_id = f"{device.device_id}_cleaning_mode"

    @property
    def current_option(self) -> str | None:
        data = self._data
        if data is None or data.mode is None:
            return None
        return _CLEANING_MODE_TO_LABEL.get(data.mode)

    async def async_select_option(self, option: str) -> None:
        value = _CLEANING_MODE_TO_VALUE.get(option)
        if value is None:
            _LOGGER.warning("Unknown cleaning mode %r; ignoring", option)
            return
        await self.coordinator.async_set_property({"mode": value})


class KarcherWaterLevelSelect(KarcherEntity, SelectEntity):
    """Water-level select. Disabled by default; unavailable in Vacuum-only mode."""

    _attr_translation_key = "water_level"
    _attr_entity_registry_enabled_default = False
    _attr_options: list[str] = [WATER_LOW_LABEL, WATER_MEDIUM_LABEL, WATER_HIGH_LABEL]  # noqa: RUF012

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        device = coordinator.device
        self._attr_unique_id = f"{device.device_id}_water_level"

    @property
    def available(self) -> bool:
        data = self._data
        if data is None:
            return False
        return data.mode != CLEANING_MODE_VACUUM

    @property
    def current_option(self) -> str | None:
        data = self._data
        if data is None or data.water is None:
            return None
        return _WATER_LEVEL_TO_LABEL.get(data.water)

    async def async_select_option(self, option: str) -> None:
        value = _WATER_LEVEL_TO_VALUE.get(option)
        if value is None:
            _LOGGER.warning("Unknown water level %r; ignoring", option)
            return
        await self.coordinator.async_set_property({"water": value})
