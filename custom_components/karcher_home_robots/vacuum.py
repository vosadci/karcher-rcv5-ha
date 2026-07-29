# SPDX-License-Identifier: MIT
"""Vacuum entity — StateVacuumEntity for the Kärcher RCV5."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from homeassistant.components.vacuum import Segment, StateVacuumEntity
from homeassistant.components.vacuum.const import VacuumActivity, VacuumEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.entity_registry import EventEntityRegistryUpdatedData

from .const import CLEANING_MODE_MOP, POWER_TO_WIND, WIND_TO_POWER
from .coordinator import KarcherCoordinator
from .entity import KarcherEntity
from .state import VacuumState

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

# Lifecycle fault codes shown as a status label in the card (APK: cp_locating /
# fault_title_2108). Overrides the generic activity string when present.
#
# Deliberately narrow: only codes that fire during an otherwise-uninformative
# activity belong here. 2108 is safe because it only co-occurs with IDLE work_mode
# (the device-verified case). The rest of the 21xx range (2100-2107, 2109, 2110)
# was tried here and reverted — those codes persist throughout RETURNING/DOCKED
# (e.g. 2102/2104 during the whole go-home leg, 2105 once charging finishes), so
# overriding the activity text with them replaces a correct "Returning"/"Docked"
# label with a misleading charge-substate one. Device-verified 2026-06-24.
# Value is a slug the Lovelace card localizes (card TRANSLATIONS / STATUS_SLUG_LABELS),
# not display text — keep it lowercase and stable.
_STATUS_LABEL: dict[int, str] = {
    2108: "locating",
}

# Fan speed labels ↔ wind values live in const.POWER_TO_WIND (shared with the
# per-room power select); doc/PROTOCOL.md §5, confirmed 2026-03-28.

# app_zone_clean rect_px = [x0, y0, x1, y1] — two opposite corners.
_RECT_PX_LEN = 4

_VACUUM_STATE_MAP: dict[VacuumState, VacuumActivity] = {
    VacuumState.CLEANING: VacuumActivity.CLEANING,
    VacuumState.PAUSED: VacuumActivity.PAUSED,
    VacuumState.RETURNING: VacuumActivity.RETURNING,
    VacuumState.DOCKED: VacuumActivity.DOCKED,
    VacuumState.IDLE: VacuumActivity.IDLE,
    VacuumState.ERROR: VacuumActivity.ERROR,
    VacuumState.UNKNOWN: VacuumActivity.IDLE,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = entry.runtime_data
    async_add_entities([KarcherVacuum(coordinator)])


class KarcherVacuum(KarcherEntity, StateVacuumEntity):
    """Kärcher RCV5 vacuum entity."""

    _attr_translation_key = "vacuum"
    _attr_supported_features = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.LOCATE
        | VacuumEntityFeature.FAN_SPEED
        | VacuumEntityFeature.SEND_COMMAND
        | VacuumEntityFeature.CLEAN_AREA
        # required: HAMH reads supported_features to choose the ServiceArea path;
        # without STATE, Apple Home sends one selectAreas per room tap instead of batching.
        | VacuumEntityFeature.STATE
    )

    # Map attributes are large and change every path push — exclude from recorder.
    _unrecorded_attributes = frozenset(
        {
            "room_map",
            "cur_path_px",
            "robot_px",
            "charger_px",
            "object_px",
            "map_image_size",
            "map_legend",
        }
    )

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        device = coordinator.device
        self._attr_unique_id = f"{device.device_id}_vacuum"
        # Cached translation_key → {room_id_str → entity_id} lookup; rebuilding
        # scans the entity registry and extra_state_attributes is evaluated on
        # every state write (each path push while cleaning).
        self._pref_entity_map_cache: dict[str, dict[str, str]] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._handle_entity_registry_updated
            )
        )

    @callback
    def _handle_entity_registry_updated(
        self, _event: Event[EventEntityRegistryUpdatedData]
    ) -> None:
        self._pref_entity_map_cache = None

    def _pref_entity_map(self) -> dict[str, dict[str, str]]:
        """Return the per-room preference entity lookup, rebuilding on demand.

        Only cached once this entity has a registry entry (device_id known);
        invalidated by any entity-registry update event.
        """
        if self._pref_entity_map_cache is not None:
            return self._pref_entity_map_cache
        result: dict[str, dict[str, str]] = {}
        device_id = self.registry_entry.device_id if self.registry_entry else None
        if not device_id:
            return result  # not registered yet — do not cache the empty map
        ent_reg = er.async_get(self.hass)
        pref_tks = {
            "room_mode",
            "room_power",
            "room_water",
            "room_repeat",
            "room_custom",
            "room_order",
        }
        for entry in er.async_entries_for_device(ent_reg, device_id):
            tk = entry.translation_key or ""
            if tk not in pref_tks:
                continue
            # unique_id pattern: {device_id}_room_{room_id}_{suffix}
            uid = entry.unique_id or ""
            parts = uid.rsplit("_room_", 1)
            if len(parts) == 2:  # noqa: PLR2004
                rid = parts[1].rsplit("_", 1)[0]  # strip suffix
                result.setdefault(tk, {})[rid] = entry.entity_id
        self._pref_entity_map_cache = result
        return result

    def _handle_coordinator_update(self) -> None:
        """Check for segment changes whenever coordinator data refreshes."""
        last_seen = self.last_seen_segments  # None until user maps areas in HA UI
        if last_seen is not None:
            last_ids = {s.id for s in last_seen}
            current_ids = {str(r.room_id) for r in self.coordinator.rooms}
            if last_ids != current_ids:
                self.async_create_segments_issue()
        super()._handle_coordinator_update()

    async def async_get_segments(self) -> list[Segment]:
        """Return the list of cleanable room segments."""
        return [Segment(id=str(r.room_id), name=r.name) for r in self.coordinator.rooms]

    def _known_room_ids(self, room_ids: Iterable[int]) -> list[int]:
        """Filter *room_ids* down to ones the coordinator currently knows about."""
        known = {r.room_id for r in self.coordinator.rooms}
        return [rid for rid in room_ids if rid in known]

    async def _dispatch_room_clean(self, room_ids: list[int]) -> None:
        # A room-segment dispatch is always a fresh clean (vacuum.clean_area, HAMH
        # room select, or the card's Stop→new-rooms flow while paused) — never a
        # Resume; clear the previous path on the upcoming cleaning transition.
        self.coordinator.set_resume_intent(False)
        await self.coordinator.async_send_command(
            "set_room_clean",
            {"room_ids": room_ids, "ctrl_value": 1, "clean_type": 0},
        )
        self.coordinator.set_active_clean_rooms(room_ids)

    async def async_clean_segments(self, segment_ids: list[str], **kwargs: Any) -> None:
        """Clean the given room segments (called by vacuum.clean_area service)."""
        room_ids = self._known_room_ids(int(sid) for sid in segment_ids if sid.isdigit())
        if not room_ids:
            room_ids = self.coordinator.consume_clean_room_ids()
        await self._dispatch_room_clean(room_ids)

    @property
    def activity(self) -> VacuumActivity | None:
        if not self.available:
            return None
        return _VACUUM_STATE_MAP.get(self.coordinator.vacuum_state, VacuumActivity.IDLE)

    @property
    def fan_speed_list(self) -> list[str]:
        data = self._data
        if data is not None and data.mode == CLEANING_MODE_MOP:
            return []
        return list(POWER_TO_WIND)

    @property
    def fan_speed(self) -> str | None:
        data = self._data
        if data is None or data.wind is None or data.mode == CLEANING_MODE_MOP:
            return None
        return WIND_TO_POWER.get(data.wind)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        coord = self.coordinator
        snapshot = coord.map_snapshot
        # {id_str: name} — Roborock-compatible format expected by HAMH Matter bridge.
        rooms_attr = {str(r.room_id): r.name for r in coord.rooms}

        room_map: dict[str, Any] = {}
        if snapshot is not None:
            info_by_id = {r.room_id: r for r in snapshot.rooms}
            for r in coord.rooms:
                rid = str(r.room_id)
                info = info_by_id.get(r.room_id)
                room_map[rid] = {
                    "name": r.name,
                    "color_id": info.color_id if info else 0,
                    "cells": coord.room_cell_map.get(r.room_id, []),
                    "area_m2": coord.room_areas_m2.get(r.room_id),
                }

        image_size = coord.render_image_size

        # Per-room preference data with entity_ids for the card (cached lookup).
        pref_entity_map = self._pref_entity_map()

        room_prefs: dict[str, Any] = {}
        for i, pref in enumerate(coord.room_preferences):
            rid = str(pref.room_id)
            room_prefs[rid] = {
                "order": i + 1,
                "mode": pref.mode,
                "power": pref.wind,
                "repeat": pref.repeat,
                "custom": pref.check == 1,
                "water": pref.water,
                "entities": {
                    "mode": pref_entity_map.get("room_mode", {}).get(rid),
                    "power": pref_entity_map.get("room_power", {}).get(rid),
                    "water": pref_entity_map.get("room_water", {}).get(rid),
                    "repeat": pref_entity_map.get("room_repeat", {}).get(rid),
                    "custom": pref_entity_map.get("room_custom", {}).get(rid),
                    "order": pref_entity_map.get("room_order", {}).get(rid),
                },
            }

        return {
            "rooms": rooms_attr,
            "room_map": room_map,
            "room_preferences": room_prefs,
            "prefer_mode": coord.prefer_mode,
            "map_image_size": {
                "width": image_size[0],
                "height": image_size[1],
                "cell_size": image_size[2],
            }
            if image_size
            else None,
            "robot_px": coord.robot_px,
            "charger_px": coord.charger_px,
            "object_px": coord.object_px,
            "cur_path_px": coord.cur_path_px,
            "active_clean_room_ids": coord.active_clean_room_ids,
            "active_clean_zone_px": coord.active_clean_zone_px,
            "map_legend": coord.map_legend,
            "status_label": _STATUS_LABEL.get(coord.data.fault)
            if coord.data and coord.data.fault is not None
            else None,
        }

    async def async_start(self) -> None:
        coordinator = self.coordinator
        state = coordinator.vacuum_state
        # vacuum.start while paused is a Resume (continue the in-progress clean and
        # its path); from any other state it's a fresh clean (clear the old path).
        coordinator.set_resume_intent(state == VacuumState.PAUSED)
        if state == VacuumState.PAUSED:
            # Resume routes by clean type, like the app's controlClean(1): a paused
            # area clean resumes via set_zone_clean, not set_room_clean.
            if coordinator.active_clean_is_zone:
                await coordinator.async_send_command("set_zone_clean", {"ctrl_value": 1})
                return
            # Resume from paused: empty room_ids signals "continue" (doc/PROTOCOL.md §5)
            room_ids: list[int] = []
        else:
            # One-shot consumption: vacuum.start must stay whole-home for
            # external callers (HAMH dispatches Apple Home's "clean all rooms"
            # as a parameterless vacuum.start). A persistent selection here
            # turned every Apple Home full clean into a single-room clean.
            room_ids = coordinator.consume_clean_room_ids()

        await coordinator.async_send_command(
            "set_room_clean",
            {"room_ids": room_ids, "ctrl_value": 1, "clean_type": 0},
        )
        if room_ids:
            coordinator.set_active_clean_rooms(room_ids)

    async def async_pause(self) -> None:
        # Route by clean type, like the app's controlClean(2): an area clean
        # pauses via set_zone_clean, not set_room_clean.
        if self.coordinator.active_clean_is_zone:
            await self.coordinator.async_send_command("set_zone_clean", {"ctrl_value": 2})
            return
        await self.coordinator.async_send_command(
            "set_room_clean",
            {"room_ids": [], "ctrl_value": 2, "clean_type": 0},
        )

    async def async_stop(self, **kwargs: Any) -> None:
        state = self.coordinator.vacuum_state
        if state == VacuumState.RETURNING:
            # stop_recharge cancels an in-progress dock return (doc/PROTOCOL.md §5).
            await self.coordinator.async_send_command("stop_recharge", {})
        elif state in (VacuumState.CLEANING, VacuumState.PAUSED):
            # True stop-to-idle (distinct from pause): ctrl_value=0 cancels the
            # active clean and the robot transitions to an idle work_mode.
            # Device-verified on RCV5 2026-06-23; ctrl_value {0=stop, 1=start/
            # resume, 2=pause}. See doc/PROTOCOL.md §5. (Zone stop via
            # set_zone_clean ctrl_value=0 is inferred by symmetry, not separately
            # captured — the card's Stop-intent flag covers it if ever ignored.)
            if self.coordinator.active_clean_is_zone:
                await self.coordinator.async_send_command("set_zone_clean", {"ctrl_value": 0})
            else:
                await self.coordinator.async_send_command(
                    "set_room_clean",
                    {"room_ids": [], "ctrl_value": 0, "clean_type": 0},
                )
        # DOCKED / IDLE / ERROR: no command — already stopped, nothing to cancel.

    async def async_return_to_base(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command("start_recharge", {})

    async def async_locate(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command("find_device", {})

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        data = self._data
        if data is not None and data.mode == CLEANING_MODE_MOP:
            raise ServiceValidationError("Fan speed is unavailable in Mop-only mode")
        wind = POWER_TO_WIND.get(fan_speed)
        if wind is None:
            raise ServiceValidationError(f"Unknown fan speed {fan_speed!r}")
        await self.coordinator.async_set_property({"wind": wind})

    async def async_send_command(
        self,
        command: str,
        params: dict[str, Any] | list[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if command == "app_segment_clean":
            await self._handle_app_segment_clean(params)
            return
        if command == "app_zone_clean":
            await self._handle_app_zone_clean(params)
            return
        # params may be a dict or a single-element list (Roborock-compat shim)
        p: dict[str, Any] = {}
        if isinstance(params, dict):
            p = params
        elif isinstance(params, list) and len(params) == 1 and isinstance(params[0], dict):
            p = params[0]
        if command == "set_preference_type":
            prefer_type = int(p.get("prefer_type", 0))
            await self.coordinator.async_set_preference_type(prefer_type)
            return
        await self.coordinator.async_send_command(command, p)

    async def _handle_app_segment_clean(self, params: dict[str, Any] | list[Any] | None) -> None:
        # HAMH calls vacuum.send_command("app_segment_clean", [room_id, ...])
        # when the user selects rooms in Apple Home via the ServiceArea cluster.
        # Caller-supplied order is preserved; default fallback uses the coordinator's
        # preference-aware resolution so the order matches the user-arranged list.
        if params and isinstance(params, list):
            room_ids = self._known_room_ids(
                int(r) for r in params if str(r).isdigit() or isinstance(r, int)
            )
        else:
            room_ids = []
        if not room_ids:
            room_ids = self.coordinator.consume_clean_room_ids()
        await self._dispatch_room_clean(room_ids)

    async def _handle_app_zone_clean(self, params: dict[str, Any] | list[Any] | None) -> None:
        # Card sends rect_px = [x0, y0, x1, y1] (two opposite corners in rendered-image
        # pixels). The coordinator converts to world metres and issues the two-step
        # set_zone_points / set_zone_clean sequence.
        if isinstance(params, list) and len(params) == 1 and isinstance(params[0], dict):
            params = params[0]
        if not isinstance(params, dict):
            raise ServiceValidationError("app_zone_clean requires a rect_px parameter")
        rect = params.get("rect_px")
        if not isinstance(rect, (list, tuple)) or len(rect) != _RECT_PX_LEN:
            raise ServiceValidationError("rect_px must be [x0, y0, x1, y1]")
        x0, y0, x1, y1 = (float(v) for v in rect)
        await self.coordinator.async_zone_clean((x0, y0, x1, y1))
