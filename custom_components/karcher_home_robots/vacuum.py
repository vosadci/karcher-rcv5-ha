# SPDX-License-Identifier: MIT
"""Vacuum entity — StateVacuumEntity for the Kärcher RCV5.

Covers: FR-V-1..FR-V-12, FR-AH-1..FR-AH-3
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.vacuum import StateVacuumEntity, VacuumEntityFeature  # type: ignore[attr-defined]
from homeassistant.components.vacuum.const import VacuumActivity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CLEANING_MODE_MOP
from .coordinator import KarcherCoordinator, VacuumState
from .entity import KarcherEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

# Fan speed labels (doc/PROTOCOL.md §5, confirmed 2026-03-28).
# Maps HA fan-speed string → wind property value.
# FR-AH-3: Silent → Quiet, Standard/Medium → Auto, Turbo → Max for Matter.
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
    """Set up the vacuum entity from a config entry."""
    coordinator: KarcherCoordinator = entry.runtime_data
    async_add_entities([KarcherVacuum(coordinator)])


class KarcherVacuum(KarcherEntity, StateVacuumEntity):
    """Kärcher RCV5 vacuum entity.

    Rooms are exposed as state_attributes in Roborock format {id_str: name}
    for downstream Matter bridge compatibility (FR-AH-1).
    """

    _attr_translation_key = "vacuum"
    _attr_supported_features = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.LOCATE
        | VacuumEntityFeature.FAN_SPEED
        | VacuumEntityFeature.SEND_COMMAND
        | VacuumEntityFeature.STATE
    )
    _attr_fan_speed_list: list[str]

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        device = coordinator._device
        self._attr_unique_id = f"{device.device_id}_vacuum"
        self._attr_fan_speed_list = [
            FAN_SPEED_SILENT,
            FAN_SPEED_STANDARD,
            FAN_SPEED_MEDIUM,
            FAN_SPEED_TURBO,
        ]

    @property
    def activity(self) -> VacuumActivity | None:
        """Return the current vacuum activity derived from coordinator state."""
        if not self.available:
            return None
        return _VACUUM_STATE_MAP.get(self.coordinator.vacuum_state, VacuumActivity.IDLE)

    @property
    def fan_speed(self) -> str | None:
        """Return the current fan speed label, or None when Mop-only (FR-V-8)."""
        data = self._data
        if data is None or data.wind is None or data.mode == CLEANING_MODE_MOP:
            return None
        return _WIND_TO_FAN_SPEED.get(data.wind)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return rooms in Roborock-compatible format {id_str: name}.

        Covers: FR-V-11, FR-AH-1
        """
        return {"rooms": {str(r.room_id): r.name for r in self.coordinator.rooms}}

    # ------------------------------------------------------------------
    # Commands (FR-V-1..FR-V-7)
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        """Start or resume cleaning.

        Covers: FR-V-1, FR-V-2, FR-V-3
        """
        coordinator = self.coordinator
        state = coordinator.vacuum_state
        if state == VacuumState.PAUSED:
            # Resume from paused: pass empty room_ids (doc/PROTOCOL.md §5)
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
        """Pause the current clean (FR-V-4)."""
        await self.coordinator.async_send_command(
            "set_room_clean",
            {"room_ids": [], "ctrl_value": 2, "clean_type": 0},
        )

    async def async_stop(self, **kwargs: Any) -> None:
        """Stop / cancel dock return (FR-V-5).

        stop_recharge cancels an in-progress return; during cleaning the
        robot is left stationary (the app has no "stop during clean" path).
        """
        await self.coordinator.async_send_command("stop_recharge", {})

    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Send the robot to the charger (FR-V-6)."""
        await self.coordinator.async_send_command("start_recharge", {})

    async def async_locate(self, **kwargs: Any) -> None:
        """Emit an audible beep (FR-V-7)."""
        await self.coordinator.async_send_command("set_find_robot", {"find_robot": 1})

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set suction power (FR-V-8).

        Fan speed is sent as a prop.set command (doc/PROTOCOL.md §5).
        """
        wind = _FAN_SPEED_TO_WIND.get(fan_speed)
        if wind is None:
            _LOGGER.warning("Unknown fan speed %r; ignoring", fan_speed)
            return
        await self.coordinator.async_set_property({"wind": wind})

    async def async_send_command(
        self,
        command: str,
        params: dict[str, Any] | list[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Pass through a raw service_invoke command (FR-V-12).

        params may be a dict or a single-element list (Roborock-compat shim).
        """
        p: dict[str, Any] = {}
        if isinstance(params, dict):
            p = params
        elif isinstance(params, list) and len(params) == 1 and isinstance(params[0], dict):
            p = params[0]
        await self.coordinator.async_send_command(command, p)
