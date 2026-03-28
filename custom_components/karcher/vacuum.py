"""Kärcher vacuum entity."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.vacuum import (
    STATE_CLEANING,
    STATE_DOCKED,
    STATE_ERROR,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_RETURNING,
    StateVacuumEntity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from karcher.identifiers import VacuumState

from .const import CMD_GO_HOME, CMD_PAUSE, CMD_START, CMD_STOP, DOMAIN
from .coordinator import KarcherCoordinator, derive_vacuum_state
from .entity import KarcherEntity

_LOGGER = logging.getLogger(__name__)

VACUUM_STATE_MAP: dict[VacuumState, str] = {
    VacuumState.Cleaning: STATE_CLEANING,
    VacuumState.Returning: STATE_RETURNING,
    VacuumState.Idle: STATE_IDLE,
    VacuumState.Docked: STATE_DOCKED,
    VacuumState.Paused: STATE_PAUSED,
    VacuumState.Error: STATE_ERROR,
    VacuumState.Unknown: STATE_IDLE,
}

SUPPORTED_FEATURES = (
    VacuumEntityFeature.START
    | VacuumEntityFeature.PAUSE
    | VacuumEntityFeature.STOP
    | VacuumEntityFeature.RETURN_HOME
    | VacuumEntityFeature.BATTERY
    | VacuumEntityFeature.STATE
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
    def state(self) -> str | None:
        if self.coordinator.data is None:
            return None
        vacuum_state = derive_vacuum_state(self.coordinator.data)
        return VACUUM_STATE_MAP.get(vacuum_state, STATE_IDLE)

    @property
    def battery_level(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.quantity or None

    @property
    def fan_speed(self) -> str | None:
        """Return current suction level as a string."""
        if self.coordinator.data is None:
            return None
        return str(self.coordinator.data.wind)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        props = self.coordinator.data
        if props is None:
            return {}
        return {
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

    async def async_start(self) -> None:
        await self.coordinator.api.async_send_command(
            self.coordinator.device, CMD_START["service"], CMD_START["params"]
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
