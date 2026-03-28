"""Kärcher select entities: room, cleaning mode, water level."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CLEANING_MODE_LIST,
    CLEANING_MODE_MAP,
    CLEANING_MODE_REVERSE,
    DOMAIN,
    WATER_LEVEL_LIST,
    WATER_LEVEL_MAP,
    WATER_LEVEL_REVERSE,
)
from .coordinator import KarcherCoordinator
from .entity import KarcherEntity

_LOGGER = logging.getLogger(__name__)
_OPTION_ALL = "All rooms"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        KarcherRoomSelect(coordinator),
        KarcherCleaningModeSelect(coordinator),
        KarcherWaterLevelSelect(coordinator),
    ])


class KarcherRoomSelect(KarcherEntity, SelectEntity):
    """Select entity for choosing which room to clean."""

    _attr_name = "Room"
    _attr_icon = "mdi:floor-plan"

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_room_select"

    @property
    def options(self) -> list[str]:
        return [_OPTION_ALL] + [r["name"] for r in self.coordinator.rooms]

    @property
    def current_option(self) -> str:
        if self.coordinator.selected_room_id is None:
            return _OPTION_ALL
        for r in self.coordinator.rooms:
            if r["id"] == self.coordinator.selected_room_id:
                return r["name"]
        return _OPTION_ALL

    async def async_select_option(self, option: str) -> None:
        if option == _OPTION_ALL:
            self.coordinator.selected_room_id = None
        else:
            for r in self.coordinator.rooms:
                if r["name"] == option:
                    self.coordinator.selected_room_id = r["id"]
                    break
        self.async_write_ha_state()


class KarcherCleaningModeSelect(KarcherEntity, SelectEntity):
    """Select entity for choosing the cleaning mode (vacuum / mop / both)."""

    _attr_name = "Cleaning Mode"
    _attr_icon = "mdi:broom"
    _attr_options = CLEANING_MODE_LIST

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_cleaning_mode"

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return CLEANING_MODE_REVERSE.get(self.coordinator.data.mode)

    async def async_select_option(self, option: str) -> None:
        mode = CLEANING_MODE_MAP.get(option)
        if mode is None:
            _LOGGER.warning("Unknown cleaning mode: %s", option)
            return
        await self.coordinator.api.async_set_property(
            self.coordinator.device, {"mode": mode}
        )
        await self.coordinator.async_request_refresh()


class KarcherWaterLevelSelect(KarcherEntity, SelectEntity):
    """Select entity for choosing the mop water level."""

    _attr_name = "Water Level"
    _attr_icon = "mdi:water"
    _attr_options = WATER_LEVEL_LIST

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_water_level"

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return WATER_LEVEL_REVERSE.get(self.coordinator.data.water)

    async def async_select_option(self, option: str) -> None:
        level = WATER_LEVEL_MAP.get(option)
        if level is None:
            _LOGGER.warning("Unknown water level: %s", option)
            return
        await self.coordinator.api.async_set_property(
            self.coordinator.device, {"water": level}
        )
        await self.coordinator.async_request_refresh()
