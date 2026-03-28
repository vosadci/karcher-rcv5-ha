"""Kärcher Home Robots integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from karcher.exception import KarcherHomeException, KarcherHomeInvalidAuth

from .api import KarcherApi
from .const import (
    CONF_COUNTRY,
    CONF_DEVICE_ID,
    CONF_DEVICE_SN,
    CONF_EMAIL,
    CONF_PASSWORD,
    DOMAIN,
)
from .coordinator import KarcherCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["vacuum"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Kärcher from a config entry."""

    api = KarcherApi(entry.data[CONF_COUNTRY])

    try:
        await api.authenticate(entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
        devices = await api.get_devices()
    except KarcherHomeInvalidAuth as err:
        raise ConfigEntryAuthFailed("Credentials rejected by Kärcher cloud") from err
    except KarcherHomeException as err:
        raise ConfigEntryNotReady(f"Cannot connect to Kärcher cloud: {err}") from err

    device_id = entry.data[CONF_DEVICE_ID]
    device = next((d for d in devices if d.device_id == device_id), None)
    if device is None:
        raise ConfigEntryNotReady(
            f"Device {device_id} not found in account. "
            "It may have been removed or transferred."
        )

    coordinator = KarcherCoordinator(hass, api, device)

    # Wire the MQTT push callback into the coordinator.
    # The callback is invoked from the paho-mqtt thread, so we must
    # bridge back to the HA event loop via call_soon_threadsafe.
    def _on_push(props):
        hass.loop.call_soon_threadsafe(coordinator.handle_mqtt_push, props)

    # Subscribe in the executor (synchronous blocking call).
    await hass.async_add_executor_job(api.subscribe_device, device, _on_push)

    # Initial data fetch (also triggers the 30-s polling loop).
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: KarcherCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.api.close()
    return unload_ok
