# SPDX-License-Identifier: MIT
"""Number entities — per-room cleaning order."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KarcherCoordinator
from .entity import KarcherEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = entry.runtime_data

    # Per-room numbers are added dynamically — rooms may arrive after setup
    # (retried fetch or map change). See select.py for the same pattern.
    known_room_ids: set[int] = set()

    def _async_add_room_entities() -> None:
        new_rooms = [r for r in coordinator.rooms if r.room_id not in known_room_ids]
        if not new_rooms:
            return
        known_room_ids.update(r.room_id for r in new_rooms)
        async_add_entities(
            KarcherRoomOrderNumber(coordinator, room.room_id, room.name) for room in new_rooms
        )

    _async_add_room_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_room_entities))


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
        prefs = self.coordinator.room_preferences
        if not prefs:
            raise ServiceValidationError("Room preferences not loaded yet")

        current = next((p for p in prefs if p.room_id == self._room_id), None)
        if current is None:
            raise ServiceValidationError(f"Room {self._room_id} not in preference list")

        ordered = list(prefs)
        new_pos = max(0, min(new_pos, len(ordered) - 1))
        ordered.remove(current)
        ordered.insert(new_pos, current)

        await self.coordinator.async_set_room_order([p.room_id for p in ordered])
