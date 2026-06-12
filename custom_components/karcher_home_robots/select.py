# SPDX-License-Identifier: MIT
"""Select entities — room, cleaning mode, water level."""

from __future__ import annotations

import logging
from dataclasses import replace as _dataclass_replace
from typing import Final

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._types import DeviceProperties, RoomPreference
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
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = entry.runtime_data
    async_add_entities(
        [
            KarcherRoomSelect(coordinator),
            KarcherCleaningModeSelect(coordinator),
            KarcherWaterLevelSelect(coordinator),
        ]
    )

    # Per-room entities are added dynamically: rooms may arrive after setup
    # (initial fetch failed and was retried, or a map change introduced new
    # rooms). The listener fires on every coordinator update and adds entities
    # only for room IDs not yet seen.
    known_room_ids: set[int] = set()

    def _async_add_room_entities() -> None:
        new_rooms = [r for r in coordinator.rooms if r.room_id not in known_room_ids]
        if not new_rooms:
            return
        known_room_ids.update(r.room_id for r in new_rooms)
        entities: list[SelectEntity] = []
        for room in new_rooms:
            entities.append(KarcherRoomModeSelect(coordinator, room.room_id, room.name))
            entities.append(KarcherRoomPowerSelect(coordinator, room.room_id, room.name))
            entities.append(KarcherRoomRepeatSelect(coordinator, room.room_id, room.name))
        async_add_entities(entities)

    _async_add_room_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_room_entities))


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
        # Intentionally bypasses super().available: rooms are cached locally and
        # the select only writes coordinator state (no adapter call), so it remains
        # usable even when the coordinator is temporarily unreachable.
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
                raise ServiceValidationError(f"Room {option!r} not found in room list")
            self.coordinator.set_selected_room_id(room_id)
        self.async_write_ha_state()


_TANK_STATE_SEATED = 3
_CLOTH_STATE_INSTALLED = 1


def _mop_attached(data: DeviceProperties | None) -> bool:
    """Return True when both the water tank and mop cloth are physically present.

    Mirrors PlanAddCleanPlanActivity.java RCV5 branch:
      tank_state == 3 && cloth_state == 1  →  all modes enabled
    When either field is None (not yet received), treat attachment as absent.
    """
    if data is None:
        return False
    return data.tank_state == _TANK_STATE_SEATED and data.cloth_state == _CLOTH_STATE_INSTALLED


_MOP_OPTIONS: list[str] = [CLEANING_MODE_VACUUM_AND_MOP_LABEL, CLEANING_MODE_MOP_LABEL]


class KarcherCleaningModeSelect(KarcherEntity, SelectEntity):
    """Cleaning-mode select: Vacuum / Vacuum & Mop / Mop.

    All three options are always present — HAMH snapshots SupportedModes once at
    startup, so dynamic filtering would trap users who restart with no mop attached.
    When the mop attachment is absent, mop-containing options are listed in the
    disabled_options extra attribute so the custom card can render them grayed out.
    The validation in async_select_option enforces the hardware constraint at call time.
    """

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
    def extra_state_attributes(self) -> dict[str, list[str]]:
        return {"disabled_options": [] if _mop_attached(self._data) else _MOP_OPTIONS}

    @property
    def current_option(self) -> str | None:
        data = self._data
        if data is None or data.mode is None:
            return None
        return _CLEANING_MODE_TO_LABEL.get(data.mode)

    async def async_select_option(self, option: str) -> None:
        value = _CLEANING_MODE_TO_VALUE.get(option)
        if value is None:
            raise ServiceValidationError(f"Unknown cleaning mode {option!r}")
        if not _mop_attached(self._data) and option in _MOP_OPTIONS:
            raise ServiceValidationError(
                f"Mop attachment not present; cannot select mode {option!r}"
            )
        await self.coordinator.async_set_property({"mode": value})


class KarcherWaterLevelSelect(KarcherEntity, SelectEntity):
    """Water-level select.

    Unavailable in Vacuum-only mode or without mop attachment.
    """

    _attr_translation_key = "water_level"
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
        return data.mode != CLEANING_MODE_VACUUM and _mop_attached(data)

    @property
    def current_option(self) -> str | None:
        data = self._data
        if data is None or data.water is None:
            return None
        return _WATER_LEVEL_TO_LABEL.get(data.water)

    async def async_select_option(self, option: str) -> None:
        value = _WATER_LEVEL_TO_VALUE.get(option)
        if value is None:
            raise ServiceValidationError(f"Unknown water level {option!r}")
        await self.coordinator.async_set_property({"water": value})


# ---------------------------------------------------------------------------
# Per-room preference selects
# ---------------------------------------------------------------------------

_ROOM_MODE_LABELS: Final[list[str]] = [
    CLEANING_MODE_VACUUM_LABEL,
    CLEANING_MODE_VACUUM_AND_MOP_LABEL,
    CLEANING_MODE_MOP_LABEL,
]

_POWER_SILENT_LABEL: Final = "silent"
_POWER_STANDARD_LABEL: Final = "standard"
_POWER_MEDIUM_LABEL: Final = "medium"
_POWER_TURBO_LABEL: Final = "turbo"
_ROOM_POWER_LABELS: Final[list[str]] = [
    _POWER_SILENT_LABEL,
    _POWER_STANDARD_LABEL,
    _POWER_MEDIUM_LABEL,
    _POWER_TURBO_LABEL,
]
_POWER_TO_WIND: dict[str, int] = {
    _POWER_SILENT_LABEL: 0,
    _POWER_STANDARD_LABEL: 1,
    _POWER_MEDIUM_LABEL: 2,
    _POWER_TURBO_LABEL: 3,
}
_WIND_TO_POWER: dict[int, str] = {v: k for k, v in _POWER_TO_WIND.items()}

_REPEAT_SINGLE_LABEL: Final = "single"
_REPEAT_DOUBLE_LABEL: Final = "double"
_ROOM_REPEAT_LABELS: Final[list[str]] = [
    _REPEAT_SINGLE_LABEL,
    _REPEAT_DOUBLE_LABEL,
]
_REPEAT_TO_VALUE: dict[str, int] = {
    _REPEAT_SINGLE_LABEL: 0,
    _REPEAT_DOUBLE_LABEL: 1,
}
_VALUE_TO_REPEAT: dict[int, str] = {v: k for k, v in _REPEAT_TO_VALUE.items()}


class _KarcherRoomPrefSelect(KarcherEntity, SelectEntity):
    """Base class for per-room preference select entities."""

    def __init__(
        self,
        coordinator: KarcherCoordinator,
        room_id: int,
        room_name: str,
        suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._room_id = room_id
        self._room_name = room_name
        device = coordinator.device
        self._attr_unique_id = f"{device.device_id}_room_{room_id}_{suffix}"

    @property
    def available(self) -> bool:
        return self._pref() is not None

    def _pref(self) -> RoomPreference | None:
        for p in self.coordinator.room_preferences:
            if p.room_id == self._room_id:
                return p
        return None


class KarcherRoomModeSelect(_KarcherRoomPrefSelect):
    """Per-room cleaning mode select."""

    _attr_translation_key = "room_mode"
    _attr_options: list[str] = _ROOM_MODE_LABELS

    def __init__(self, coordinator: KarcherCoordinator, room_id: int, room_name: str) -> None:
        super().__init__(coordinator, room_id, room_name, "mode")

    @property
    def name(self) -> str:
        return f"{self._room_name} mode"

    @property
    def current_option(self) -> str | None:
        pref = self._pref()
        if pref is None:
            return None
        return _CLEANING_MODE_TO_LABEL.get(pref.mode)

    async def async_select_option(self, option: str) -> None:
        value = _CLEANING_MODE_TO_VALUE.get(option)
        if value is None:
            raise ServiceValidationError(f"Unknown cleaning mode {option!r}")
        pref = self._pref()
        if pref is None:
            raise ServiceValidationError("Room preference not loaded yet")
        await self.coordinator.async_set_room_preference(
            self._room_id, _dataclass_replace(pref, mode=value)
        )


class KarcherRoomPowerSelect(_KarcherRoomPrefSelect):
    """Per-room suction power select."""

    _attr_translation_key = "room_power"
    _attr_options: list[str] = _ROOM_POWER_LABELS

    def __init__(self, coordinator: KarcherCoordinator, room_id: int, room_name: str) -> None:
        super().__init__(coordinator, room_id, room_name, "power")

    @property
    def name(self) -> str:
        return f"{self._room_name} power"

    @property
    def current_option(self) -> str | None:
        pref = self._pref()
        if pref is None:
            return None
        return _WIND_TO_POWER.get(pref.wind)

    async def async_select_option(self, option: str) -> None:
        value = _POWER_TO_WIND.get(option)
        if value is None:
            raise ServiceValidationError(f"Unknown power level {option!r}")
        pref = self._pref()
        if pref is None:
            raise ServiceValidationError("Room preference not loaded yet")
        await self.coordinator.async_set_room_preference(
            self._room_id, _dataclass_replace(pref, wind=value)
        )


class KarcherRoomRepeatSelect(_KarcherRoomPrefSelect):
    """Per-room repeat passes select."""

    _attr_translation_key = "room_repeat"
    _attr_options: list[str] = _ROOM_REPEAT_LABELS

    def __init__(self, coordinator: KarcherCoordinator, room_id: int, room_name: str) -> None:
        super().__init__(coordinator, room_id, room_name, "repeat")

    @property
    def name(self) -> str:
        return f"{self._room_name} repeat"

    @property
    def current_option(self) -> str | None:
        pref = self._pref()
        if pref is None:
            return None
        return _VALUE_TO_REPEAT.get(pref.repeat)

    async def async_select_option(self, option: str) -> None:
        value = _REPEAT_TO_VALUE.get(option)
        if value is None:
            raise ServiceValidationError(f"Unknown repeat value {option!r}")
        pref = self._pref()
        if pref is None:
            raise ServiceValidationError("Room preference not loaded yet")
        await self.coordinator.async_set_room_preference(
            self._room_id, _dataclass_replace(pref, repeat=value)
        )
