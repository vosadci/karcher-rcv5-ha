# SPDX-License-Identifier: MIT
"""Static image entity serving demo_map.png. Never updates."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import voluptuous as vol
from homeassistant.components.image import PLATFORM_SCHEMA as IMAGE_PLATFORM_SCHEMA
from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

CONF_FIXTURE_DIR = "fixture_dir"

PLATFORM_SCHEMA = IMAGE_PLATFORM_SCHEMA.extend({vol.Required(CONF_FIXTURE_DIR): cv.string})


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    png_path = Path(config[CONF_FIXTURE_DIR]) / "demo_map.png"
    async_add_entities([DemoCardImage(hass, png_path)])


class DemoCardImage(ImageEntity):
    """Serves one fixed PNG forever — no coordinator, no polling."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Demo card map"
    _attr_unique_id = "karcher_demo_card_map"
    _attr_content_type = "image/png"

    def __init__(self, hass: HomeAssistant, png_path: Path) -> None:
        super().__init__(hass)
        self._png_bytes = png_path.read_bytes()
        self._updated_at: datetime = dt_util.utcnow()

    @property
    def image_last_updated(self) -> datetime | None:
        return self._updated_at

    async def async_image(self) -> bytes | None:
        return self._png_bytes
