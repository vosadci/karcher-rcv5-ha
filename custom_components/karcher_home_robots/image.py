# SPDX-License-Identifier: MIT
"""ImageEntity for the robot vacuum map."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import KarcherCoordinator
from .entity import KarcherEntity
from .map_render import render_map

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = entry.runtime_data
    async_add_entities([KarcherMapImage(coordinator)])


class KarcherMapImage(KarcherEntity, ImageEntity):
    """Robot vacuum map as a PNG image entity."""

    _attr_content_type = "image/png"
    _attr_translation_key = "map"

    def __init__(self, coordinator: KarcherCoordinator) -> None:
        KarcherEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, coordinator.hass)
        self._attr_unique_id = f"{coordinator.device.device_id}_map"

    @property
    def image_last_updated(self) -> datetime | None:
        return self.coordinator.image_last_updated

    async def async_image(self) -> bytes | None:
        snapshot = self.coordinator.map_snapshot
        if snapshot is None:
            return None
        try:
            return await self.hass.async_add_executor_job(render_map, snapshot)
        except Exception:
            _LOGGER.exception("render_map failed")
            return None
