# SPDX-License-Identifier: MIT
"""Switch entities — per-room custom settings toggle; AI recognition and carpet settings."""

from __future__ import annotations

from dataclasses import replace as _dataclass_replace
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._types import DeviceProperties, RoomPreference
from .coordinator import KarcherCoordinator
from .entity import KarcherEntity, add_room_entities

PARALLEL_UPDATES = 1

# Object types the app's AI recognition introduce screen lists as detectable
# (APK-verified, AiRecognitionIntroduceActivity.getList(), 1.4.32). Static —
# not per-type toggles; the app itself only exposes one master switch.
_AI_DETECTED_TYPES = ("Shoes", "Socks", "Wires", "Bar chairs", "Weight scales")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = entry.runtime_data
    async_add_entities(
        [
            KarcherAiRecognitionSwitch(coordinator),
            KarcherCarpetBoostSwitch(coordinator),
            KarcherCarpetAvoidanceSwitch(coordinator),
            KarcherCarpetDisplaySwitch(coordinator),
        ]
    )
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


class _KarcherPrivacySwitch(KarcherEntity, SwitchEntity):
    """Base for switches backed by a `privacy` sub-property (`prop.set
    {"privacy": {<field>: 0|1}}`, APK-verified CarpetSettingVM.java /
    PrivacySecurityVM.java, 2026-09-22). *_privacy_field* is the wire key;
    *_value_fn* reads the matching DeviceProperties attribute.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _privacy_field: str
    _value_fn: staticmethod[[DeviceProperties], int | None]

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_{self._privacy_field}"

    @property
    def is_on(self) -> bool | None:
        data = self._data
        value = self._value_fn(data) if data is not None else None
        if value is None:
            return None
        return value == 1

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._set(1)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._set(0)

    async def _set(self, value: int) -> None:
        await self.coordinator.async_set_property({"privacy": {self._privacy_field: value}})


class KarcherAiRecognitionSwitch(_KarcherPrivacySwitch):
    """AI object recognition (camera-based; on-device only, doc/INVESTIGATION.md §Camera)."""

    _attr_translation_key = "ai_recognition"
    _privacy_field = "ai_recognize"
    _value_fn = staticmethod(lambda d: d.ai_recognize)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"detected_types": _AI_DETECTED_TYPES}


class KarcherCarpetBoostSwitch(_KarcherPrivacySwitch):
    """Suction boost when the robot detects it's on carpet."""

    _attr_translation_key = "carpet_boost"
    _privacy_field = "carpet_turbo"
    _value_fn = staticmethod(lambda d: d.carpet_turbo)


class KarcherCarpetAvoidanceSwitch(_KarcherPrivacySwitch):
    """Avoid carpet areas (relevant during mopping)."""

    _attr_translation_key = "carpet_avoidance"
    _privacy_field = "carpet_avoid"
    _value_fn = staticmethod(lambda d: d.carpet_avoid)


class KarcherCarpetDisplaySwitch(_KarcherPrivacySwitch):
    """Show detected carpet outlines on the map."""

    _attr_translation_key = "carpet_display"
    _privacy_field = "carpet_show"
    _value_fn = staticmethod(lambda d: d.carpet_show)
