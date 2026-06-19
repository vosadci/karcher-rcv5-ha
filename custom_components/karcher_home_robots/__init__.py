# SPDX-License-Identifier: MIT
"""Kärcher Home Robots integration entry point."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from ._account_registry import get_or_create_adapter, release_adapter
from .config_flow import CONF_DEVICE_ID, CONF_REGION
from .const import DOMAIN
from .coordinator import KarcherCoordinator
from .exceptions import AuthError, PermanentError, TransientError

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

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

# Config-entry schema versions. Current must match KarcherConfigFlow.VERSION.
_ENTRY_VERSION_CURRENT = 3
_ENTRY_VERSION_V2 = 2


_SERVICE_SET_ROOM_PREFERENCE = "set_room_preference"
_SERVICE_SET_ROOM_SELECTION = "set_room_selection"
_SERVICE_REFRESH_PREFERENCES = "refresh_preferences"

_SET_ROOM_PREFERENCE_SCHEMA = vol.Schema(
    {
        vol.Required("room_order"): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional("device_id"): cv.string,
    }
)

_SET_ROOM_SELECTION_SCHEMA = vol.Schema(
    {
        vol.Required("room_ids"): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional("device_id"): cv.string,
    }
)

_REFRESH_PREFERENCES_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
    }
)


def _coordinator_for_call(
    hass: HomeAssistant, call: ServiceCall, room_ids: set[int]
) -> KarcherCoordinator:
    """Resolve the target coordinator for a service call.

    With device_id (HA device-registry id): that device's coordinator, always.
    Without: fall back to room-set matching, which is only unambiguous for a
    single robot — multiple matches raise so two robots with overlapping room
    IDs can never silently misroute a command.
    """
    loaded: list[tuple[ConfigEntry, KarcherCoordinator]] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        coordinator: KarcherCoordinator | None = getattr(entry, "runtime_data", None)
        if coordinator is not None:
            loaded.append((entry, coordinator))

    device_id: str | None = call.data.get("device_id")
    if device_id is not None:
        device = dr.async_get(hass).async_get(device_id)
        if device is None:
            raise ServiceValidationError(f"Unknown device_id {device_id!r}")
        for entry, coordinator in loaded:
            if entry.entry_id in device.config_entries:
                return coordinator
        raise ServiceValidationError(f"Device {device_id!r} is not a loaded Kärcher robot")

    matching = [
        coordinator
        for _, coordinator in loaded
        if not room_ids or room_ids.issubset({r.room_id for r in coordinator.rooms})
    ]
    if len(matching) == 1:
        return matching[0]
    if not matching:
        raise ServiceValidationError("No robot matches the given room ids")
    raise ServiceValidationError("Multiple robots match; pass device_id to disambiguate")


def _register_services(hass: HomeAssistant) -> None:
    """Register integration-level services (idempotent — safe to call per entry setup)."""
    if hass.services.has_service(DOMAIN, _SERVICE_SET_ROOM_PREFERENCE):
        return

    async def handle_set_room_preference(call: ServiceCall) -> None:
        room_order: list[int] = call.data["room_order"]
        coordinator = _coordinator_for_call(hass, call, set(room_order))
        await coordinator.async_set_room_order(room_order)
        _LOGGER.debug("set_room_preference: sent order %s", room_order)

    async def handle_set_room_selection(call: ServiceCall) -> None:
        room_ids: list[int] = call.data["room_ids"]
        coordinator = _coordinator_for_call(hass, call, set(room_ids))
        coordinator.set_selected_room_ids(set(room_ids))
        _LOGGER.debug("set_room_selection: %s", sorted(set(room_ids)))

    async def handle_refresh_preferences(call: ServiceCall) -> None:
        coordinator = _coordinator_for_call(hass, call, set())
        await coordinator.async_refresh_preferences()
        _LOGGER.debug("refresh_preferences: forced preference refetch")

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
    hass.services.async_register(
        DOMAIN,
        _SERVICE_REFRESH_PREFERENCES,
        handle_refresh_preferences,
        schema=_REFRESH_PREFERENCES_SCHEMA,
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


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a config entry created by an older version of this integration.

    v2 → v3: drop the redundant sn / product_id / nickname keys — they are
    re-derived from the cloud device list at every setup. v1 never shipped in
    a public release; v1 entries fail migration and must be re-added.
    """
    if entry.version > _ENTRY_VERSION_CURRENT:
        # Downgrade from a future version — refuse to guess.
        return False
    if entry.version == _ENTRY_VERSION_CURRENT:
        return True
    if entry.version == _ENTRY_VERSION_V2:
        new_data = {
            k: v for k, v in entry.data.items() if k not in ("sn", "product_id", "nickname")
        }
        hass.config_entries.async_update_entry(entry, data=new_data, version=_ENTRY_VERSION_CURRENT)
        _LOGGER.info("Migrated config entry %s from v2 to v3", entry.entry_id)
        return True
    _LOGGER.error(
        "Cannot migrate config entry %s from version %s; remove and re-add the integration",
        entry.entry_id,
        entry.version,
    )
    return False


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
    try:
        await coordinator.async_setup()
    except Exception:
        # The refcount taken by get_or_create_adapter above must be released on
        # ANY setup failure past this point, or each ConfigEntryNotReady retry
        # (first refresh fails while the cloud is down at HA start) increments
        # the refcount again and leaves the MQTT subscription from the failed
        # attempt registered — so the shared adapter is never released or
        # closed. Cleanup is best-effort: it must not mask the original error.
        with contextlib.suppress(Exception):
            await coordinator.async_shutdown()
        await release_adapter(hass, email)
        raise
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
            hass.services.async_remove(DOMAIN, _SERVICE_SET_ROOM_SELECTION)
            hass.services.async_remove(DOMAIN, _SERVICE_REFRESH_PREFERENCES)
    return unloaded
