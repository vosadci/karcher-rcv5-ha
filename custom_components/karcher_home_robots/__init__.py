# SPDX-License-Identifier: MIT
"""Kärcher Home Robots integration entry point."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady

from .adapter import AdapterConfig, KarcherAdapter
from .config_flow import CONF_DEVICE_ID, CONF_EMAIL, CONF_PASSWORD, CONF_REGION
from .coordinator import KarcherCoordinator
from .exceptions import AuthError, PermanentError, TransientError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.VACUUM,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.IMAGE,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    region = entry.data[CONF_REGION]
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    device_id = entry.data[CONF_DEVICE_ID]

    adapter = KarcherAdapter(hass, AdapterConfig(region=region))

    try:
        await adapter.async_setup()
        await adapter.authenticate(email, password)
        snapshot = adapter.get_endpoint_snapshot()
        devices = await adapter.get_devices()
    except AuthError as exc:
        await adapter.close()
        raise ConfigEntryAuthFailed(str(exc)) from exc
    except PermanentError as exc:
        await adapter.close()
        raise ConfigEntryError(str(exc)) from exc
    except TransientError as exc:
        await adapter.close()
        raise ConfigEntryNotReady(str(exc)) from exc

    # Persist endpoint snapshot so HA restart can reconnect without re-running region-discovery.
    if snapshot != entry.data.get("region_endpoint_snapshot"):
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "region_endpoint_snapshot": snapshot}
        )

    device = next((d for d in devices if d.device_id == device_id), None)
    if device is None:
        await adapter.close()
        raise ConfigEntryError(f"Device {device_id} not found on account")

    coordinator = KarcherCoordinator(hass, adapter, device, config_entry=entry)
    await coordinator.async_setup()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: KarcherCoordinator = entry.runtime_data
        await coordinator.async_shutdown()
    return unloaded
