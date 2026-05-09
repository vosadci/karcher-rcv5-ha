# SPDX-License-Identifier: MIT
"""Vacuum entity — StateVacuumEntity for the Kärcher RCV5."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.vacuum import StateVacuumEntity, VacuumEntityFeature  # type: ignore[attr-defined]
from homeassistant.components.vacuum.const import VacuumActivity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CLEANING_MODE_MOP
from .coordinator import KarcherCoordinator, VacuumState
from .entity import KarcherEntity
from .map_render import world_to_pixel

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

# Fan speed labels (doc/PROTOCOL.md §5, confirmed 2026-03-28); maps HA string → wind property value.
FAN_SPEED_SILENT = "Silent"
FAN_SPEED_STANDARD = "Standard"
FAN_SPEED_MEDIUM = "Medium"
FAN_SPEED_TURBO = "Turbo"

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
    async_add_entities: AddEntitiesCallback,
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
    )

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        device = coordinator.device
        self._attr_unique_id = f"{device.device_id}_vacuum"

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
                }

        image_size = coord.render_image_size
        layout = coord.render_layout

        def _w2px(pose: Any) -> dict[str, float] | None:
            if pose is None or layout is None or snapshot is None:
                return None
            grid = snapshot.grid
            px, py = world_to_pixel(
                pose.x,
                pose.y,
                layout,
                grid.width,
                grid.height,
                grid.resolution,
                grid.min_x,
                grid.min_y,
            )
            return {"x": px, "y": py}

        robot_px = _w2px(snapshot.robot if snapshot else None)
        if robot_px is not None and snapshot is not None and snapshot.robot is not None:
            robot_px["phi"] = snapshot.robot.phi

        return {
            "rooms": rooms_attr,
            "room_map": room_map,
            "map_image_size": {
                "width": image_size[0],
                "height": image_size[1],
                "cell_size": image_size[2],
            }
            if image_size
            else None,
            "robot_px": robot_px,
            "charger_px": _w2px(snapshot.charger if snapshot else None),
        }

    async def async_start(self) -> None:
        coordinator = self.coordinator
        state = coordinator.vacuum_state
        if state == VacuumState.PAUSED:
            # Resume from paused: empty room_ids signals "continue" (doc/PROTOCOL.md §5)
            room_ids: list[int] = []
        else:
            selected = coordinator.get_selected_room_id()
            if selected is not None:
                room_ids = [selected]
            else:
                room_ids = [r.room_id for r in coordinator.rooms]

        await coordinator.async_send_command(
            "set_room_clean",
            {"room_ids": room_ids, "ctrl_value": 1, "clean_type": 0},
        )

    async def async_pause(self) -> None:
        await self.coordinator.async_send_command(
            "set_room_clean",
            {"room_ids": [], "ctrl_value": 2, "clean_type": 0},
        )

    async def async_stop(self, **kwargs: Any) -> None:
        # stop_recharge cancels an in-progress dock return; no "stop during clean" path exists
        await self.coordinator.async_send_command("stop_recharge", {})

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
        await self.coordinator.async_send_command(command, p)

    async def _handle_app_segment_clean(self, params: dict[str, Any] | list[Any] | None) -> None:
        # HAMH calls vacuum.send_command("app_segment_clean", [room_id, ...])
        # when the user selects rooms in Apple Home via the ServiceArea cluster.
        if params and isinstance(params, list):
            room_ids = [int(r) for r in params if str(r).isdigit() or isinstance(r, int)]
        else:
            room_ids = [r.room_id for r in self.coordinator.rooms]
        if not room_ids:
            room_ids = [r.room_id for r in self.coordinator.rooms]
        await self.coordinator.async_send_command(
            "set_room_clean",
            {"room_ids": room_ids, "ctrl_value": 1, "clean_type": 0},
        )
