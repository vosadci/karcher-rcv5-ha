# SPDX-License-Identifier: MIT
"""Select entities — room, cleaning mode, water level."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import replace as _dataclass_replace
from typing import Any, Final

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._types import DeviceProperties, RoomPreference
from .const import (
    CLEANING_MODE_MOP,
    CLEANING_MODE_VACUUM,
    CLEANING_MODE_VACUUM_AND_MOP,
    POWER_TO_WIND,
    WIND_TO_POWER,
)
from .coordinator import KarcherCoordinator
from .entity import KarcherEntity, add_room_entities

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
    WATER_LOW_LABEL: 0,
    WATER_MEDIUM_LABEL: 1,
    WATER_HIGH_LABEL: 2,
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

    add_room_entities(
        coordinator,
        entry,
        async_add_entities,
        lambda room: [
            KarcherRoomModeSelect(coordinator, room.room_id, room.name),
            KarcherRoomPowerSelect(coordinator, room.room_id, room.name),
            KarcherRoomWaterSelect(coordinator, room.room_id, room.name),
            KarcherRoomRepeatSelect(coordinator, room.room_id, room.name),
        ],
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


@dataclass(frozen=True)
class _RoomPrefSelectDesc:
    """Per-entity differences between the room-preference selects.

    *suffix* drives the translation key (``room_{suffix}``), the unique_id, and
    the displayed name word; *field* is the RoomPreference attribute written.
    """

    suffix: str
    field: str
    options: list[str]
    to_value: dict[str, int]
    to_label: dict[int, str]
    error_noun: str


class _KarcherRoomPrefSelect(KarcherEntity, SelectEntity):
    """Per-room preference select, parameterised by a _RoomPrefSelectDesc.

    Concrete subclasses set ``_desc``; the label↔value mapping and the target
    RoomPreference field are the only per-entity differences.
    """

    _desc: _RoomPrefSelectDesc

    def __init__(self, coordinator: KarcherCoordinator, room_id: int, room_name: str) -> None:
        super().__init__(coordinator)
        self._room_id = room_id
        self._room_name = room_name
        desc = self._desc
        self._attr_translation_key = f"room_{desc.suffix}"
        self._attr_options = desc.options
        self._attr_unique_id = f"{coordinator.device.device_id}_room_{room_id}_{desc.suffix}"

    @property
    def name(self) -> str:
        return f"{self._live_room_name(self._room_id, self._room_name)} {self._desc.suffix}"

    @property
    def available(self) -> bool:
        return self._pref() is not None

    def _pref(self) -> RoomPreference | None:
        return self.coordinator.preference_for_id(self._room_id)

    @property
    def current_option(self) -> str | None:
        pref = self._pref()
        if pref is None:
            return None
        return self._desc.to_label.get(getattr(pref, self._desc.field))

    async def async_select_option(self, option: str) -> None:
        desc = self._desc
        value = desc.to_value.get(option)
        if value is None:
            raise ServiceValidationError(f"Unknown {desc.error_noun} {option!r}")
        pref = self._pref()
        if pref is None:
            raise ServiceValidationError("Room preference not loaded yet")
        changes: dict[str, Any] = {desc.field: value}
        await self.coordinator.async_set_room_preference(
            self._room_id, _dataclass_replace(pref, **changes)
        )


class KarcherRoomModeSelect(_KarcherRoomPrefSelect):
    """Per-room cleaning mode select."""

    _desc = _RoomPrefSelectDesc(
        suffix="mode",
        field="mode",
        options=_ROOM_MODE_LABELS,
        to_value=_CLEANING_MODE_TO_VALUE,
        to_label=_CLEANING_MODE_TO_LABEL,
        error_noun="cleaning mode",
    )


class KarcherRoomPowerSelect(_KarcherRoomPrefSelect):
    """Per-room suction power select."""

    _desc = _RoomPrefSelectDesc(
        suffix="power",
        field="wind",
        options=list(POWER_TO_WIND),
        to_value=POWER_TO_WIND,
        to_label=WIND_TO_POWER,
        error_noun="power level",
    )


class KarcherRoomRepeatSelect(_KarcherRoomPrefSelect):
    """Per-room repeat passes select."""

    _desc = _RoomPrefSelectDesc(
        suffix="repeat",
        field="repeat",
        options=_ROOM_REPEAT_LABELS,
        to_value=_REPEAT_TO_VALUE,
        to_label=_VALUE_TO_REPEAT,
        error_noun="repeat value",
    )


class KarcherRoomWaterSelect(_KarcherRoomPrefSelect):
    """Per-room water level select."""

    _desc = _RoomPrefSelectDesc(
        suffix="water",
        field="water",
        options=[WATER_LOW_LABEL, WATER_MEDIUM_LABEL, WATER_HIGH_LABEL],
        to_value=_WATER_LEVEL_TO_VALUE,
        to_label=_WATER_LEVEL_TO_LABEL,
        error_noun="water level",
    )
