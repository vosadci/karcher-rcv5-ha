"""Kärcher room selection entity."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import KarcherCoordinator
from .entity import KarcherEntity

_OPTION_ALL = "All rooms"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([KarcherRoomSelect(coordinator)])


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
