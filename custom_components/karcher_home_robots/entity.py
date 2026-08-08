# SPDX-License-Identifier: MIT
"""Shared entity base — device_info, coordinator binding, availability."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._types import DeviceProperties
from .const import DOMAIN
from .coordinator import KarcherCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .adapter import Room


def add_room_entities(
    coordinator: KarcherCoordinator,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[Room], Iterable[Entity]],
) -> None:
    """Add per-room entities dynamically as rooms appear on the coordinator.

    Rooms may arrive after setup (retried initial fetch or a map change). The
    listener fires on every coordinator update and adds entities only for room
    IDs not seen yet. *factory* builds the entities for one room.
    """
    known_room_ids: set[int] = set()

    def _add() -> None:
        new_rooms = [r for r in coordinator.rooms if r.room_id not in known_room_ids]
        if not new_rooms:
            return
        known_room_ids.update(r.room_id for r in new_rooms)
        entities: list[Entity] = []
        for room in new_rooms:
            entities.extend(factory(room))
        async_add_entities(entities)

    _add()
    entry.async_on_unload(coordinator.async_add_listener(_add))


class KarcherEntity(CoordinatorEntity[KarcherCoordinator]):
    """Base entity for all Kärcher Home Robots platform entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def device_info(self) -> DeviceInfo:
        device = self.coordinator.device
        return DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            name=device.nickname or device.sn,
            manufacturer="Kärcher",
            model=device.model or "RCV 5",
            serial_number=device.sn,
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    def _live_room_name(self, room_id: int, fallback: str) -> str:
        """Current name for *room_id*, so per-room entities follow robot renames.

        Falls back to the construction-time name if the room is momentarily
        absent from the coordinator's room list (name must never be None).
        """
        return self.coordinator.room_name_for_id(room_id) or fallback

    @property
    def _data(self) -> DeviceProperties | None:
        # DataUpdateCoordinator stubs .data as non-Optional, but it is None
        # before the first successful refresh. Re-typed here so subclass None
        # checks are not flagged as unreachable by mypy.
        data: DeviceProperties | None = self.coordinator.data
        return data
