# SPDX-License-Identifier: MIT
"""Kärcher Home Robots integration entry point."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall
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
_SERVICE_SET_ROOM_SELECTION = "set_room_selection"

_SET_ROOM_PREFERENCE_SCHEMA = vol.Schema(
    {
        vol.Required("room_order"): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    }
)

_SET_ROOM_SELECTION_SCHEMA = vol.Schema(
    {
        vol.Required("room_ids"): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    }
)


def _register_services(hass: HomeAssistant) -> None:
    """Register integration-level services (idempotent — safe to call per entry setup)."""
    if hass.services.has_service(DOMAIN, _SERVICE_SET_ROOM_PREFERENCE):
        return

    async def handle_set_room_preference(call: ServiceCall) -> None:
        room_order: list[int] = call.data["room_order"]
        room_order_set = set(room_order)
        for entry in hass.config_entries.async_entries(DOMAIN):
            coordinator: KarcherCoordinator | None = getattr(entry, "runtime_data", None)
            if coordinator is None:
                continue
            if not room_order_set.issubset({r.room_id for r in coordinator.rooms}):
                continue
            await coordinator.async_set_room_order(room_order)
            _LOGGER.debug("set_room_preference: sent order %s", room_order)
            break

    async def handle_set_room_selection(call: ServiceCall) -> None:
        room_ids: list[int] = call.data["room_ids"]
        room_ids_set = set(room_ids)
        for entry in hass.config_entries.async_entries(DOMAIN):
            coordinator: KarcherCoordinator | None = getattr(entry, "runtime_data", None)
            if coordinator is None:
                continue
            known = {r.room_id for r in coordinator.rooms}
            # Match the coordinator whose rooms contain the selection (empty = clear).
            if room_ids_set and not room_ids_set.issubset(known):
                continue
            coordinator.set_selected_room_ids(room_ids_set)
            _LOGGER.debug("set_room_selection: %s", sorted(room_ids_set))
            break

    hass.services.async_register(
        DOMAIN,
        _SERVICE_SET_ROOM_PREFERENCE,
        handle_set_room_preference,
        schema=_SET_ROOM_PREFERENCE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        _SERVICE_SET_ROOM_SELECTION,
        handle_set_room_selection,
        schema=_SET_ROOM_SELECTION_SCHEMA,
    )


async def _register_lovelace_resource(hass: HomeAssistant) -> None:
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None:
        return
    resource_col = lovelace_data.resources
    if not isinstance(resource_col, ResourceStorageCollection):
        return  # user has resource_mode: yaml — skip silently
    url = f"{_STATIC_PATH}/karcher-vacuum-card.js"
    for item in resource_col.async_items():
        if item.get("url", "").startswith(_STATIC_PATH):
            return  # already registered
    await resource_col.async_create_item({"res_type": "module", "url": url})
    _LOGGER.debug("Registered Lovelace resource: %s", url)


async def async_setup(hass: HomeAssistant, config: dict[str, object]) -> bool:
    async def _on_started(_event: Event) -> None:
        await _register_lovelace_resource(hass)

    if hass.is_running:
        await _register_lovelace_resource(hass)
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_started)
    return True


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
        if not hass.config_entries.async_entries(DOMAIN):
            hass.services.async_remove(DOMAIN, _SERVICE_SET_ROOM_PREFERENCE)
    return unloaded
