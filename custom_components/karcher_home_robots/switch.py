# SPDX-License-Identifier: MIT
"""Switch entities — per-room custom settings toggle."""

from __future__ import annotations

from dataclasses import replace as _dataclass_replace

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._types import RoomPreference
from .coordinator import KarcherCoordinator
from .entity import KarcherEntity, add_room_entities

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = entry.runtime_data
    add_room_entities(
        coordinator,
        entry,
        async_add_entities,
        lambda room: [KarcherRoomCustomSwitch(coordinator, room.room_id, room.name)],
    )


class KarcherRoomCustomSwitch(KarcherEntity, SwitchEntity):
    """Switch: enable/disable custom settings for one room.

    check=1 means the room uses its own mode/power/repeat overrides.
    check=0 means the room uses the global defaults.
    Maps to the checkbox in the app's custom clean settings screen
    (CustomRoomAdapter.java:54: checkBox.setChecked(item.getCheck() == 1)).
    """

    _attr_translation_key = "room_custom"

    def __init__(
        self,
        coordinator: KarcherCoordinator,
        room_id: int,
        room_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._room_id = room_id
        self._room_name = room_name
        self._attr_unique_id = f"{coordinator.device.device_id}_room_{room_id}_custom"

    @property
    def name(self) -> str:
        return f"{self._live_room_name(self._room_id, self._room_name)} custom settings"

    @property
    def available(self) -> bool:
        return self._pref() is not None

    @property
    def is_on(self) -> bool | None:
        pref = self._pref()
        if pref is None:
            return None
        return pref.check == 1

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._set_check(1)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._set_check(0)

    async def _set_check(self, value: int) -> None:
        pref = self._pref()
        if pref is None:
            raise ServiceValidationError("Room preference not loaded yet")
        await self.coordinator.async_set_room_preference(
            self._room_id, _dataclass_replace(pref, check=value)
        )

    def _pref(self) -> RoomPreference | None:
        return self.coordinator.preference_for_id(self._room_id)
