# SPDX-License-Identifier: MIT
"""Number entities — per-room cleaning order."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import KarcherCoordinator
from .entity import KarcherEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = entry.runtime_data
    async_add_entities(
        KarcherRoomOrderNumber(coordinator, room.room_id, room.name) for room in coordinator.rooms
    )


class KarcherRoomOrderNumber(KarcherEntity, NumberEntity):
    """Number: cleaning order position for one room (1 = cleaned first).

    The order is the position of the room in the preference array sent via
    set_preference. Changing this entity reorders the array so the room moves
    to the requested position, shifting other rooms accordingly.
    """

    _attr_translation_key = "room_order"
    _attr_native_min_value = 1.0
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: KarcherCoordinator,
        room_id: int,
        room_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._room_id = room_id
        self._room_name = room_name
        self._attr_unique_id = f"{coordinator.device.device_id}_room_{room_id}_order"

    @property
    def name(self) -> str:
        return f"{self._room_name} clean order"

    @property
    def available(self) -> bool:
        return bool(self.coordinator.room_preferences)

    @property
    def native_max_value(self) -> float:
        return float(max(len(self.coordinator.room_preferences), 1))

    @property
    def native_value(self) -> float | None:
        prefs = self.coordinator.room_preferences
        for i, p in enumerate(prefs):
            if p.room_id == self._room_id:
                return float(i + 1)
        return None

    async def async_set_native_value(self, value: float) -> None:
        new_pos = int(value) - 1  # 0-based index
        prefs = list(self.coordinator.room_preferences)
        if not prefs:
            raise ServiceValidationError("Room preferences not loaded yet")

        current = next((p for p in prefs if p.room_id == self._room_id), None)
        if current is None:
            raise ServiceValidationError(f"Room {self._room_id} not in preference list")

        new_pos = max(0, min(new_pos, len(prefs) - 1))
        prefs.remove(current)
        prefs.insert(new_pos, current)

        map_id_str = self.coordinator._current_map_id
        if map_id_str is None:
            raise ServiceValidationError("No map loaded; cannot reorder rooms")

        raw = [p.to_raw() for p in prefs]
        await self.coordinator._adapter.set_preference(
            self.coordinator._device, int(map_id_str), raw
        )
        self.coordinator.room_preferences = prefs
        self.coordinator.async_update_listeners()
