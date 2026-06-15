# SPDX-License-Identifier: MIT
"""Vacuum entity — StateVacuumEntity for the Kärcher RCV5."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from homeassistant.components.vacuum import Segment, StateVacuumEntity
from homeassistant.components.vacuum.const import VacuumActivity
from homeassistant.components.vacuum.const import VacuumEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import EventEntityRegistryUpdatedData
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CLEANING_MODE_MOP
from .coordinator import KarcherCoordinator, VacuumState
from .entity import KarcherEntity
from .map_render import world_to_pixel


_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

# Lifecycle fault codes shown as a status label in the card (APK: cp_locating / fault_title_2108).
# Overrides the generic activity string when present.
_STATUS_LABEL: dict[int, str] = {
    2108: "Locating",
}

# Fan speed translation keys (doc/PROTOCOL.md §5, confirmed 2026-03-28).
# Lowercase keys match strings.json entity.vacuum.vacuum.state_attributes.fan_speed.state.
FAN_SPEED_SILENT = "silent"
FAN_SPEED_STANDARD = "standard"
FAN_SPEED_MEDIUM = "medium"
FAN_SPEED_TURBO = "turbo"

_FAN_SPEED_TO_WIND: dict[str, int] = {
    FAN_SPEED_SILENT: 0,
    FAN_SPEED_STANDARD: 1,
    FAN_SPEED_MEDIUM: 2,
    FAN_SPEED_TURBO: 3,
}
_WIND_TO_FAN_SPEED: dict[int, str] = {v: k for k, v in _FAN_SPEED_TO_WIND.items()}

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
        {"room_map", "cur_path_px", "robot_px", "charger_px", "map_image_size"}
    )

    # Emit one path point per this many raw points — limits attribute size while
    # preserving path shape at the card's display resolution.
    _CUR_PATH_STEP = 3

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
        pref_tks = {"room_mode", "room_power", "room_repeat", "room_custom", "room_order"}
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

    async def async_clean_segments(self, segment_ids: list[str], **kwargs: Any) -> None:
        """Clean the given room segments (called by vacuum.clean_area service)."""
        room_ids = [int(sid) for sid in segment_ids if sid.isdigit()]
        if not room_ids:
            room_ids = self.coordinator.consume_clean_room_ids()
        await self.coordinator.async_send_command(
            "set_room_clean",
            {"room_ids": room_ids, "ctrl_value": 1, "clean_type": 0},
        )
        self.coordinator.set_active_clean_rooms(room_ids)

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
        return [FAN_SPEED_SILENT, FAN_SPEED_STANDARD, FAN_SPEED_MEDIUM, FAN_SPEED_TURBO]

    @property
    def fan_speed(self) -> str | None:
        data = self._data
        if data is None or data.wind is None or data.mode == CLEANING_MODE_MOP:
            return None
        return _WIND_TO_FAN_SPEED.get(data.wind)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:  # noqa: PLR0912, PLR0915
        coord = self.coordinator
        snapshot = coord.map_snapshot
        # {id_str: name} — Roborock-compatible format expected by HAMH Matter bridge.
        rooms_attr = {str(r.room_id): r.name for r in coord.rooms}

        room_map: dict[str, Any] = {}
        if snapshot is not None:
            info_by_id = {r.room_id: r for r in snapshot.rooms}
            room_id_grid = coord._room_id_grid
            res = snapshot.grid.resolution
            cell_area = res * res  # m² per grid cell
            for r in coord.rooms:
                rid = str(r.room_id)
                info = info_by_id.get(r.room_id)
                area_m2: float | None = None
                if room_id_grid is not None:
                    cell_count = int(np.count_nonzero(room_id_grid == r.room_id))
                    if cell_count > 0:
                        area_m2 = round(cell_count * cell_area, 1)
                room_map[rid] = {
                    "name": r.name,
                    "color_id": info.color_id if info else 0,
                    "cells": coord.room_cell_map.get(r.room_id, []),
                    "area_m2": area_m2,
                }

        image_size = coord.render_image_size
        layout = coord.render_layout

        def _w2px(wx: float, wy: float) -> dict[str, float] | None:
            if layout is None or snapshot is None:
                return None
            grid = snapshot.grid
            px, py = world_to_pixel(
                wx,
                wy,
                layout,
                grid.width,
                grid.height,
                grid.resolution,
                grid.min_x,
                grid.min_y,
            )
            return {"x": px, "y": py}

        robot_px: dict[str, float] | None = None
        if coord.current_robot_pose is not None:
            rx, ry, rphi = coord.current_robot_pose
            robot_px = _w2px(rx, ry)
            if robot_px is not None:
                robot_px["phi"] = rphi
        elif snapshot is not None and snapshot.robot is not None:
            robot_px = _w2px(snapshot.robot.x, snapshot.robot.y)
            if robot_px is not None:
                robot_px["phi"] = snapshot.robot.phi

        charger_px: dict[str, float] | None = None
        if snapshot is not None and snapshot.charger is not None:
            charger_px = _w2px(snapshot.charger.x, snapshot.charger.y)

        # Decimate cur_path and convert to flat [x0,y0,x1,y1,...] pixel list.
        cur_path_px: list[int] = []
        raw_path = coord._cur_path
        if raw_path and layout is not None and snapshot is not None:
            step = self._CUR_PATH_STEP
            for i in range(0, len(raw_path), step):
                wx, wy, _phi, _flag = raw_path[i]
                pt = _w2px(wx, wy)
                if pt is not None:
                    cur_path_px.extend([int(pt["x"]), int(pt["y"])])
            # Always include the last point so the path tip is current.
            if len(raw_path) % step != 0:
                wx, wy, _phi, _flag = raw_path[-1]
                pt = _w2px(wx, wy)
                if pt is not None:
                    cur_path_px.extend([int(pt["x"]), int(pt["y"])])

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
            "robot_px": robot_px,
            "charger_px": charger_px,
            "cur_path_px": cur_path_px,
            "status_label": _STATUS_LABEL.get(coord.data.fault)
            if coord.data and coord.data.fault is not None
            else None,
        }

    async def async_start(self) -> None:
        coordinator = self.coordinator
        state = coordinator.vacuum_state
        if state == VacuumState.PAUSED:
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
        await self.coordinator.async_send_command(
            "set_room_clean",
            {"room_ids": [], "ctrl_value": 2, "clean_type": 0},
        )

    async def async_stop(self, **kwargs: Any) -> None:
        state = self.coordinator.vacuum_state
        if state == VacuumState.RETURNING:
            # stop_recharge cancels an in-progress dock return (doc/PROTOCOL.md §5).
            await self.coordinator.async_send_command("stop_recharge", {})
        elif state == VacuumState.CLEANING:
            # No true stop-in-place command exists; pause is the closest available action.
            await self.coordinator.async_send_command(
                "set_room_clean",
                {"room_ids": [], "ctrl_value": 2, "clean_type": 0},
            )
        # PAUSED / DOCKED / IDLE / ERROR: no command — sending set_room_clean to a
        # non-active robot has undefined firmware behaviour; do nothing.

    async def async_return_to_base(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command("start_recharge", {})

    async def async_locate(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command("find_device", {})

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        data = self._data
        if data is not None and data.mode == CLEANING_MODE_MOP:
            raise ServiceValidationError("Fan speed is unavailable in Mop-only mode")
        wind = _FAN_SPEED_TO_WIND.get(fan_speed)
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
            room_ids = [int(r) for r in params if str(r).isdigit() or isinstance(r, int)]
        else:
            room_ids = []
        if not room_ids:
            room_ids = self.coordinator.consume_clean_room_ids()
        await self.coordinator.async_send_command(
            "set_room_clean",
            {"room_ids": room_ids, "ctrl_value": 1, "clean_type": 0},
        )
        self.coordinator.set_active_clean_rooms(room_ids)
