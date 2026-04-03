"""Kärcher button entities."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_HAMH_PASSWORD, CONF_HAMH_URL, DOMAIN
from .coordinator import KarcherCoordinator
from .entity import KarcherEntity
from .hamh import configure_hamh_bridge

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KarcherCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([KarcherConfigureHamhButton(coordinator, entry)])


class KarcherConfigureHamhButton(KarcherEntity, ButtonEntity):
    """Button that creates / updates the HAMH bridge for this vacuum."""

    _attr_name = "Configure HAMH Bridge"
    _attr_icon = "mdi:home-assistant"
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: KarcherCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{coordinator.device.device_id}_configure_hamh"

    async def async_press(self) -> None:
        """Create or update the HAMH bridge via REST API."""
        hamh_url = self._entry.options.get(CONF_HAMH_URL, "").rstrip("/")
        if not hamh_url:
            raise HomeAssistantError(
                "HAMH URL not configured. Open the Kärcher integration options and enter your HAMH URL."
            )

        hamh_password = self._entry.options.get(CONF_HAMH_PASSWORD, "") or None

        await configure_hamh_bridge(
            hamh_url,
            hamh_password,
            self.coordinator.device.nickname,
        )
