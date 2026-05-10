# SPDX-License-Identifier: MIT
"""Kärcher Home Robots integration entry point."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady

from ._account_registry import get_or_create_adapter, release_adapter
from .config_flow import CONF_DEVICE_ID, CONF_REGION
from .const import DOMAIN
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

_STATIC_PATH = "/karcher_home_robots/static"
_WWW_DIR = Path(__file__).parent / "www"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    integration_data = hass.data.setdefault(DOMAIN, {})
    if not integration_data.get("static_registered") and hass.http is not None:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(_STATIC_PATH, str(_WWW_DIR), cache_headers=False)]
        )
        integration_data["static_registered"] = True

    region = entry.data[CONF_REGION]
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    device_id = entry.data[CONF_DEVICE_ID]

    try:
        adapter = await get_or_create_adapter(hass, email, password, region)
    except AuthError as exc:
        raise ConfigEntryAuthFailed(str(exc)) from exc
    except PermanentError as exc:
        raise ConfigEntryError(str(exc)) from exc
    except TransientError as exc:
        raise ConfigEntryNotReady(str(exc)) from exc

    try:
        snapshot = adapter.get_endpoint_snapshot()
        devices = await adapter.get_devices()
    except AuthError as exc:
        await release_adapter(hass, email)
        raise ConfigEntryAuthFailed(str(exc)) from exc
    except PermanentError as exc:
        await release_adapter(hass, email)
        raise ConfigEntryError(str(exc)) from exc
    except TransientError as exc:
        await release_adapter(hass, email)
        raise ConfigEntryNotReady(str(exc)) from exc

    # Persist endpoint snapshot so HA restart can reconnect without re-running region-discovery.
    if snapshot != entry.data.get("region_endpoint_snapshot"):
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "region_endpoint_snapshot": snapshot}
        )

    device = next((d for d in devices if d.device_id == device_id), None)
    if device is None:
        await release_adapter(hass, email)
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
        email = entry.data[CONF_EMAIL]
        await coordinator.async_shutdown()
        await release_adapter(hass, email)
    return unloaded
