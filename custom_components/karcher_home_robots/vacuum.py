"""Kärcher vacuum entity."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from karcher.identifiers import VacuumState

from .const import (
    CLEANING_MODE_MAP,
    CMD_GO_HOME,
    CMD_PAUSE,
    CMD_START,
    CMD_STOP,
    DOMAIN,
    FAN_SPEED_LIST,
    FAN_SPEED_MAP,
    FAN_SPEED_REVERSE,
)
from .coordinator import KarcherCoordinator, derive_vacuum_state
from .entity import KarcherEntity

_MODE_MOP = CLEANING_MODE_MAP["Mop"]

_LOGGER = logging.getLogger(__name__)

VACUUM_STATE_MAP: dict[VacuumState, VacuumActivity] = {
    VacuumState.Cleaning: VacuumActivity.CLEANING,
    VacuumState.Returning: VacuumActivity.RETURNING,
    VacuumState.Idle: VacuumActivity.IDLE,
    VacuumState.Docked: VacuumActivity.DOCKED,
    VacuumState.Paused: VacuumActivity.PAUSED,
    VacuumState.Error: VacuumActivity.ERROR,
    VacuumState.Unknown: VacuumActivity.IDLE,
}

SUPPORTED_FEATURES = (
    VacuumEntityFeature.START
    | VacuumEntityFeature.PAUSE
    | VacuumEntityFeature.STOP
    | VacuumEntityFeature.RETURN_HOME
    | VacuumEntityFeature.STATE
    | VacuumEntityFeature.FAN_SPEED
    | VacuumEntityFeature.SEND_COMMAND
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([KarcherVacuum(coordinator)])


class KarcherVacuum(KarcherEntity, StateVacuumEntity):
    """Representation of a Kärcher robot vacuum."""

    _attr_supported_features = SUPPORTED_FEATURES
    _attr_name = None  # uses device name directly

    @property
    def activity(self) -> VacuumActivity | None:
        if self.coordinator.data is None:
            return None
        vacuum_state = derive_vacuum_state(self.coordinator.data)
        return VACUUM_STATE_MAP.get(vacuum_state, VacuumActivity.IDLE)

    @property
    def fan_speed_list(self) -> list[str]:
        if self.coordinator.data is not None and self.coordinator.data.mode == _MODE_MOP:
            return []
        return FAN_SPEED_LIST

    @property
    def fan_speed(self) -> str | None:
        """Return current suction level as a human-readable string."""
        if self.coordinator.data is None:
            return None
        if self.coordinator.data.mode == _MODE_MOP:
            return None
        return FAN_SPEED_REVERSE.get(self.coordinator.data.wind)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        props = self.coordinator.data
        if props is None:
            return {}
        attrs: dict[str, Any] = {
            "cleaning_time": props.cleaning_time,
            "cleaning_area": props.cleaning_area,
            "mode": props.mode,
            "work_mode": props.work_mode,
            "charge_state": props.charge_state,
            "fault": props.fault,
            "water": props.water,
            "wind": props.wind,
            "current_map_id": props.current_map_id,
        }
        # Expose rooms in Roborock-compatible format {"id": "name", ...}.
        # HA Matter Hub detects this format and bridges ServiceArea cluster
        # to Apple Home, calling vacuum.send_command(app_segment_clean, [id])
        # when the user selects a room.
        if self.coordinator.rooms:
            attrs["rooms"] = {
                str(r["id"]): r["name"] for r in self.coordinator.rooms
            }
        return attrs

    async def async_start(self) -> None:
        # When resuming from paused, send empty room_ids — the firmware
        # continues the current job. Sending room_ids starts a new clean.
        if derive_vacuum_state(self.coordinator.data) == VacuumState.Paused:
            room_ids = []
        elif self.coordinator.selected_room_id is not None:
            room_ids = [self.coordinator.selected_room_id]
        else:
            # Pass all room IDs explicitly — empty list causes the firmware to
            # clean one room semi-randomly rather than all rooms.
            room_ids = [r["id"] for r in self.coordinator.rooms]
        await self.coordinator.api.async_send_command(
            self.coordinator.device,
            CMD_START["service"],
            {**CMD_START["params"], "room_ids": room_ids},
        )
        await self.coordinator.async_request_refresh()

    async def async_pause(self) -> None:
        await self.coordinator.api.async_send_command(
            self.coordinator.device, CMD_PAUSE["service"], CMD_PAUSE["params"]
        )

    async def async_stop(self, **kwargs: Any) -> None:
        await self.coordinator.api.async_send_command(
            self.coordinator.device, CMD_STOP["service"], CMD_STOP["params"]
        )

    async def async_return_to_base(self, **kwargs: Any) -> None:
        await self.coordinator.api.async_send_command(
            self.coordinator.device, CMD_GO_HOME["service"], CMD_GO_HOME["params"]
        )

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        if self.coordinator.data is not None and self.coordinator.data.mode == _MODE_MOP:
            _LOGGER.warning("Fan speed not applicable in Mop mode")
            return
        wind = FAN_SPEED_MAP.get(fan_speed)
        if wind is None:
            _LOGGER.warning("Unknown fan speed: %s", fan_speed)
            return
        await self.coordinator.api.async_set_property(
            self.coordinator.device, {"wind": wind}
        )
        await self.coordinator.async_request_refresh()

    async def async_send_command(
        self, command: str, params: dict[str, Any] | list | None = None, **kwargs: Any
    ) -> None:
        """Handle vacuum.send_command service calls.

        HA Matter Hub calls this with command='app_segment_clean', params=[room_id]
        when the user selects a room in Apple Home via the ServiceArea cluster.
        """
        if command == "app_segment_clean":
            if params:
                room_ids = params if isinstance(params, list) else [params]
            else:
                # Empty or missing params = "All Rooms" from Apple Home.
                # Pass all known room IDs explicitly — empty list causes the
                # firmware to pick one room semi-randomly.
                room_ids = [r["id"] for r in self.coordinator.rooms]
            await self.coordinator.api.async_send_command(
                self.coordinator.device,
                CMD_START["service"],
                {"room_ids": room_ids, "ctrl_value": 1, "clean_type": 0},
            )
            await self.coordinator.async_request_refresh()
