# SPDX-License-Identifier: MIT
"""Kärcher Home Robots integration entry point.

Wires a KarcherAdapter + KarcherCoordinator per config entry and
forwards setup to each entity platform.

Covers: FR-A-1..FR-A-8 (entry lifecycle), FR-OF-1 (unavailability on
cloud outage), NFR-SC-1..3 (one adapter per entry, no shared state),
FR-MG-2..FR-MG-5a (config entry migration).
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.issue_registry import IssueSeverity

from .adapter import AdapterConfig, KarcherAdapter
from .config_flow import CONF_DEVICE_ID, CONF_EMAIL, CONF_PASSWORD, CONF_REGION
from .const import DOMAIN
from .coordinator import KarcherCoordinator
from .exceptions import AuthError, PermanentError, TransientError

_LOGGER = logging.getLogger(__name__)

# Canonical entity_type suffixes; frozen for unique_id stability (FR-MG-1).
_CANONICAL_ENTITY_TYPES: frozenset[str] = frozenset(
    {
        "vacuum",
        "battery",
        "cleaning_area",
        "cleaning_time",
        "error",
        "room",
        "cleaning_mode",
        "water_level",
    }
)

PLATFORMS: list[Platform] = [
    Platform.VACUUM,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one Kärcher robot from a config entry.

    Creates the adapter, authenticates, constructs the coordinator,
    runs the first refresh, then forwards to each platform.
    """
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

    # Persist endpoint snapshot so HA restart can reconnect without
    # re-running region-discovery REST (FR-RG-2, FR-RG-3).
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
    """Unload all platforms and shut down the coordinator + adapter."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: KarcherCoordinator = entry.runtime_data
        await coordinator.async_shutdown()
    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry from an older version.

    v1 → v2: add region_endpoint_snapshot placeholder; re-key any
    entity-registry entries whose unique_id does not match the canonical
    {device_id}_{entity_type} form (FR-MG-2, FR-MG-3).

    On any exception: log at ERROR, create a repair issue (FR-MG-5,
    FR-MG-5a), and return False.

    Covers: FR-MG-2, FR-MG-3, FR-MG-5, FR-MG-5a
    """
    from_version = entry.version
    try:
        if from_version == 1:
            await _migrate_v1_to_v2(hass, entry)
        else:
            _LOGGER.error(
                "Unknown migration source version %s for entry %s",
                from_version,
                entry.entry_id,
            )
            return False
    except Exception:
        _LOGGER.exception(
            "Migration from v%s to v2 failed for entry %s",
            from_version,
            entry.entry_id,
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"migration_failed_v{from_version}_v2_{entry.entry_id}",
            is_fixable=False,
            is_persistent=True,
            severity=IssueSeverity.ERROR,
            translation_key=f"migration_failed_v{from_version}_v2",
            translation_placeholders={"entry_id": entry.entry_id},
        )
        return False

    _LOGGER.info(
        "Migrated entry %s from version %s to 2",
        entry.entry_id,
        from_version,
    )
    return True


async def _migrate_v1_to_v2(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Perform the v1 → v2 data-shape migration (FR-MG-2, FR-MG-3)."""
    device_id: str = entry.data.get(CONF_DEVICE_ID, "")

    # Add region_endpoint_snapshot placeholder (populated on next setup).
    new_data = {**entry.data}
    if "region_endpoint_snapshot" not in new_data:
        new_data["region_endpoint_snapshot"] = {}

    hass.config_entries.async_update_entry(entry, data=new_data, version=2)

    # Re-key entity-registry entries to canonical unique_id form (FR-MG-3).
    ent_reg = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        uid = entity_entry.unique_id
        # Already canonical: "{device_id}_{entity_type}"
        if uid.startswith(f"{device_id}_"):
            suffix = uid[len(device_id) + 1 :]
            if suffix in _CANONICAL_ENTITY_TYPES:
                continue
        # Attempt to derive canonical form by matching a known entity_type suffix.
        new_uid: str | None = None
        for entity_type in _CANONICAL_ENTITY_TYPES:
            if uid.endswith(f"_{entity_type}") or uid == entity_type:
                new_uid = f"{device_id}_{entity_type}"
                break
        if new_uid is not None and new_uid != uid:
            _LOGGER.debug(
                "Re-keying entity %s unique_id %r → %r",
                entity_entry.entity_id,
                uid,
                new_uid,
            )
            ent_reg.async_update_entity(entity_entry.entity_id, new_unique_id=new_uid)
        else:
            _LOGGER.debug(
                "Cannot map entity %s unique_id %r to canonical form; leaving unchanged",
                entity_entry.entity_id,
                uid,
            )
