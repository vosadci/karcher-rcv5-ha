# SPDX-License-Identifier: MIT
"""Kärcher Home Robots integration entry point."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

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
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.IMAGE,
]

_STATIC_PATH = "/karcher_home_robots/static"
_WWW_DIR = Path(__file__).parent / "www"


_SERVICE_SET_ROOM_PREFERENCE = "set_room_preference"

_SET_ROOM_PREFERENCE_SCHEMA = vol.Schema(
    {
        vol.Required("room_order"): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    }
)


def _register_services(hass: HomeAssistant) -> None:
    """Register integration-level services (idempotent — safe to call per entry setup)."""
    if hass.services.has_service(DOMAIN, _SERVICE_SET_ROOM_PREFERENCE):
        return

    async def handle_set_room_preference(call: ServiceCall) -> None:
        room_order: list[int] = call.data["room_order"]
        # Find the coordinator for the entry that has these rooms.
        # If multiple devices, the service applies to whichever entry contains all requested rooms.
        for entry in hass.config_entries.async_entries(DOMAIN):
            coordinator: KarcherCoordinator | None = getattr(entry, "runtime_data", None)
            if coordinator is None:
                continue
            map_id_str = coordinator._current_map_id
            if map_id_str is None:
                _LOGGER.warning("set_room_preference: no map_id available yet")
                continue
            map_id = int(map_id_str)
            rooms_by_id = {r.room_id: r for r in coordinator.rooms}
            if not rooms_by_id:
                _LOGGER.warning("set_room_preference: no rooms known yet")
                continue

            # Preserve existing per-room settings; only the order changes.
            prefs_by_id = {p.room_id: p for p in coordinator.room_preferences}
            room_preference: list[list[Any]] = []
            for rid in room_order:
                room = rooms_by_id.get(rid)
                name = room.name if room else ""
                pref = prefs_by_id.get(rid)
                if pref is not None:
                    room_preference.append(pref.to_raw())
                else:
                    room_preference.append([rid, name, 0, 0, 1, 2, 0, 0, 0, 0, 0, 0])

            await coordinator._adapter.set_preference(coordinator._device, map_id, room_preference)
            # Update local cache so the card reflects the new order immediately.
            coordinator.room_preferences = [
                p for rid in room_order if (p := prefs_by_id.get(rid)) is not None
            ]
            coordinator.async_update_listeners()
            _LOGGER.debug("set_room_preference: sent order %s to map %s", room_order, map_id)

    hass.services.async_register(
        DOMAIN,
        _SERVICE_SET_ROOM_PREFERENCE,
        handle_set_room_preference,
        schema=_SET_ROOM_PREFERENCE_SCHEMA,
    )


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

    _register_services(hass)

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
