# SPDX-License-Identifier: MIT
"""Static battery sensor for the demo card. Never updates."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.sensor import (
    PLATFORM_SCHEMA as SENSOR_PLATFORM_SCHEMA,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

CONF_BATTERY_LEVEL = "battery_level"

PLATFORM_SCHEMA = SENSOR_PLATFORM_SCHEMA.extend(
    {vol.Optional(CONF_BATTERY_LEVEL, default=100): cv.positive_int}
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    async_add_entities([DemoCardBattery(config[CONF_BATTERY_LEVEL])])


class DemoCardBattery(SensorEntity):
    """Card auto-derives `sensor.<vacuum_stem>_battery` — this provides it."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Battery"
    _attr_unique_id = "karcher_demo_card_battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    # Card auto-derivation keys off the entity_id stem, not the unique_id —
    # fix it explicitly so it lines up with vacuum.demo_card.
    entity_id = "sensor.demo_card_battery"

    def __init__(self, level: int) -> None:
        self._attr_native_value = level
