# SPDX-License-Identifier: MIT
"""Static vacuum entity loaded once from demo_attributes.json. Never updates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import voluptuous as vol
from homeassistant.components.vacuum import (
    PLATFORM_SCHEMA as VACUUM_PLATFORM_SCHEMA,
)
from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

CONF_FIXTURE_DIR = "fixture_dir"

PLATFORM_SCHEMA = VACUUM_PLATFORM_SCHEMA.extend({vol.Required(CONF_FIXTURE_DIR): cv.string})


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    fixture_dir = Path(config[CONF_FIXTURE_DIR])
    attributes = json.loads((fixture_dir / "demo_attributes.json").read_text())
    async_add_entities([DemoCardVacuum(attributes)])


class DemoCardVacuum(StateVacuumEntity):
    """Holds the fixture's attributes forever — no coordinator, no polling.

    Supports every action the card can invoke (start/pause/stop/locate/
    send_command/...) as a no-op, purely so clicking around the card for a
    screenshot doesn't raise "entity does not support action" errors.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Kärcher RCV5"
    _attr_unique_id = "karcher_demo_card_vacuum"
    _attr_platform = Platform.VACUUM
    _attr_supported_features = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.LOCATE
        | VacuumEntityFeature.FAN_SPEED
        | VacuumEntityFeature.SEND_COMMAND
        | VacuumEntityFeature.CLEAN_AREA
        | VacuumEntityFeature.STATE
    )
    _attr_activity = VacuumActivity.DOCKED
    _attr_fan_speed_list: ClassVar = ["silent", "standard", "medium", "turbo"]

    def __init__(self, attributes: dict[str, Any]) -> None:
        self._attributes = attributes

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attributes

    async def async_start(self) -> None:
        pass

    async def async_pause(self) -> None:
        pass

    async def async_stop(self, **kwargs: Any) -> None:
        pass

    async def async_return_to_base(self, **kwargs: Any) -> None:
        pass

    async def async_locate(self, **kwargs: Any) -> None:
        pass

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        pass

    async def async_send_command(
        self, command: str, params: dict[str, Any] | list[Any] | None = None, **kwargs: Any
    ) -> None:
        pass
