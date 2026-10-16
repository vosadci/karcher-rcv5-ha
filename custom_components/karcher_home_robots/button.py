# SPDX-License-Identifier: MIT
"""Button entities — consumable reset and manual drive."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DIRECTION_BACKWARD,
    DIRECTION_FORWARD,
    DIRECTION_LEFT,
    DIRECTION_RIGHT,
)
from .coordinator import KarcherCoordinator
from .entity import KarcherEntity
from .state import VacuumState

PARALLEL_UPDATES = 1


@dataclass(frozen=True)
class KarcherButtonEntityDescription(ButtonEntityDescription):
    consumable_type: int = 0


@dataclass(frozen=True, kw_only=True)
class KarcherDirectionButtonEntityDescription(ButtonEntityDescription):
    """Description for a manual-drive button."""

    direction: int


_BUTTONS: tuple[KarcherButtonEntityDescription, ...] = (
    KarcherButtonEntityDescription(
        key="reset_main_brush",
        translation_key="reset_main_brush",
        entity_category=EntityCategory.DIAGNOSTIC,
        consumable_type=1,
    ),
    KarcherButtonEntityDescription(
        key="reset_side_brush",
        translation_key="reset_side_brush",
        entity_category=EntityCategory.DIAGNOSTIC,
        consumable_type=2,
    ),
    KarcherButtonEntityDescription(
        key="reset_hypa",
        translation_key="reset_hypa",
        entity_category=EntityCategory.DIAGNOSTIC,
        consumable_type=3,
    ),
    KarcherButtonEntityDescription(
        key="reset_mop_life",
        translation_key="reset_mop_life",
        entity_category=EntityCategory.DIAGNOSTIC,
        consumable_type=4,
    ),
)


_DIRECTION_BUTTONS: tuple[KarcherDirectionButtonEntityDescription, ...] = (
    KarcherDirectionButtonEntityDescription(
        key="drive_forward",
        translation_key="drive_forward",
        entity_registry_enabled_default=False,
        direction=DIRECTION_FORWARD,
    ),
    KarcherDirectionButtonEntityDescription(
        key="drive_backward",
        translation_key="drive_backward",
        entity_registry_enabled_default=False,
        direction=DIRECTION_BACKWARD,
    ),
    KarcherDirectionButtonEntityDescription(
        key="drive_left",
        translation_key="drive_left",
        entity_registry_enabled_default=False,
        direction=DIRECTION_LEFT,
    ),
    KarcherDirectionButtonEntityDescription(
        key="drive_right",
        translation_key="drive_right",
        entity_registry_enabled_default=False,
        direction=DIRECTION_RIGHT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = entry.runtime_data
    async_add_entities(KarcherButton(coordinator, desc) for desc in _BUTTONS)
    async_add_entities([KarcherEmptyStationButton(coordinator)])
    async_add_entities(KarcherDirectionButton(coordinator, desc) for desc in _DIRECTION_BUTTONS)


class KarcherButton(KarcherEntity, ButtonEntity):
    entity_description: KarcherButtonEntityDescription

    def __init__(
        self,
        coordinator: KarcherCoordinator,
        description: KarcherButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device.device_id}_{description.key}"

    async def async_press(self) -> None:
        await self.coordinator.async_reset_consumable(self.entity_description.consumable_type)


class KarcherEmptyStationButton(KarcherEntity, ButtonEntity):
    """Manually trigger a Suction Station empty cycle.

    Guarded on availability (not a raised exception on press) — matches the
    rest of this integration's "can't do this right now" convention. Docked +
    station-attached is required; the emptying binary sensor tracks the cycle.
    """

    _attr_translation_key = "empty_station"

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_id}_empty_station"

    @property
    def available(self) -> bool:
        data = self._data
        if not super().available or data is None:
            return False
        docked = self.coordinator.vacuum_state is VacuumState.DOCKED
        return docked and (data.charge_station_type or 0) != 0

    async def async_press(self) -> None:
        await self.coordinator.async_send_command(
            "start_station_act", {"station_act": 3, "ctrl_value": 1}
        )


class KarcherDirectionButton(KarcherEntity, ButtonEntity):
    """Nudge the robot one step in a fixed direction.

    One press == one publish == one short movement; the robot does not latch a
    heading, so holding a course means pressing repeatedly (the app's D-pad
    repeats the publish while the arrow is held).

    Disabled by default: it moves the robot, and the direction values are
    verified on the RCV 5 only. The first nudge during a clean cancels it (the
    robot goes straight to manual drive, never paused), so it cannot be resumed.

    Deliberately not gated on `VacuumState` — manual drive is how a user
    recovers a robot that is stuck, wedged, or parked somewhere awkward, which
    are exactly the states a stricter guard would lock them out of.
    """

    entity_description: KarcherDirectionButtonEntityDescription

    def __init__(
        self,
        coordinator: KarcherCoordinator,
        description: KarcherDirectionButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device.device_id}_{description.key}"

    async def async_press(self) -> None:
        await self.coordinator.async_send_command(
            "set_direction", {"direction": self.entity_description.direction}
        )
