# SPDX-License-Identifier: MIT
"""Kärcher Home Robots integration entry point.

Wires a KarcherAdapter + KarcherCoordinator per config entry and
forwards setup to each entity platform.

Covers: FR-A-1..FR-A-8 (entry lifecycle), FR-OF-1 (unavailability on
cloud outage), NFR-SC-1..3 (one adapter per entry, no shared state).
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError

from .adapter import AdapterConfig, KarcherAdapter
from .config_flow import CONF_COUNTRY, CONF_DEVICE_ID, CONF_EMAIL, CONF_PASSWORD
from .coordinator import KarcherCoordinator
from .exceptions import AuthError, PermanentError, TransientError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.VACUUM,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one Kärcher robot from a config entry.

    Creates the adapter, authenticates, constructs the coordinator,
    runs the first refresh, then forwards to each platform.
    """
    country = entry.data[CONF_COUNTRY]
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    device_id = entry.data[CONF_DEVICE_ID]

    adapter = KarcherAdapter(hass, AdapterConfig(country=country))

    try:
        await adapter.async_setup()
        await adapter.authenticate(email, password)
        devices = await adapter.get_devices()
    except AuthError as exc:
        await adapter.close()
        raise ConfigEntryAuthFailed(str(exc)) from exc
    except PermanentError as exc:
        await adapter.close()
        raise ConfigEntryError(str(exc)) from exc
    except TransientError as exc:
        await adapter.close()
        raise ConfigEntryError(str(exc)) from exc

    device = next((d for d in devices if d.device_id == device_id), None)
    if device is None:
        await adapter.close()
        raise ConfigEntryError(f"Device {device_id} not found on account")

    coordinator = KarcherCoordinator(hass, adapter, device)

    try:
        await coordinator.async_setup()
    except Exception:
        await adapter.close()
        raise

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload all platforms and shut down the coordinator + adapter."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: KarcherCoordinator = entry.runtime_data
        await coordinator.async_shutdown()
    return unloaded
