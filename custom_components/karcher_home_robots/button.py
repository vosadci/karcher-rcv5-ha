# SPDX-License-Identifier: MIT
"""Button entities — consumable reset."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import KarcherCoordinator
from .entity import KarcherEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True)
class KarcherButtonEntityDescription(ButtonEntityDescription):
    consumable_type: int = 0


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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = entry.runtime_data
    async_add_entities(KarcherButton(coordinator, desc) for desc in _BUTTONS)


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
