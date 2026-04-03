"""HAMH (Home Assistant Matter Hub) bridge configuration helpers."""
from __future__ import annotations

import logging

import aiohttp

from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

HAMH_BRIDGE_NAME = "Kärcher RCV5"


async def configure_hamh_bridge(
    hamh_url: str,
    hamh_password: str | None,
    nickname: str,
) -> None:
    """Create or update the HAMH bridge for the given vacuum nickname.

    Raises HomeAssistantError on any failure so callers get a user-visible message.
    Can be called from the config flow (during setup) or from the button entity.
    """
    hamh_url = hamh_url.rstrip("/")
    slug = slugify(nickname)
    vacuum_entity_id = f"vacuum.{slug}"
    cleaning_mode_entity_id = f"select.{slug}_cleaning_mode"
    water_level_entity_id = f"select.{slug}_water_level"

    _LOGGER.debug(
        "Configuring HAMH bridge at %s for vacuum %s", hamh_url, vacuum_entity_id
    )

    auth = aiohttp.BasicAuth("admin", hamh_password) if hamh_password else None

    try:
        async with aiohttp.ClientSession(auth=auth) as session:
            bridge_id = await _find_or_create_bridge(session, hamh_url)
            await _set_entity_mapping(
                session,
                hamh_url,
                bridge_id,
                vacuum_entity_id,
                cleaning_mode_entity_id,
                water_level_entity_id,
            )
    except HomeAssistantError:
        raise
    except aiohttp.ClientConnectorError as err:
        raise HomeAssistantError(
            f"Cannot connect to HAMH at {hamh_url}. Check the URL and that HAMH is running."
        ) from err
    except Exception as err:
        raise HomeAssistantError(f"HAMH configuration failed: {err}") from err

    _LOGGER.info("HAMH bridge configured successfully (bridge name: %s)", HAMH_BRIDGE_NAME)


async def _find_or_create_bridge(
    session: aiohttp.ClientSession, hamh_url: str
) -> str:
    """Return the bridge ID, creating it if it doesn't exist."""
    async with session.get(f"{hamh_url}/api/matter/bridges") as resp:
        resp.raise_for_status()
        bridges = await resp.json()

    existing = next(
        (b for b in bridges if b.get("name") == HAMH_BRIDGE_NAME), None
    )

    if existing:
        bridge_id = existing["id"]
        _LOGGER.debug("Found existing HAMH bridge id=%s", bridge_id)

        async with session.put(
            f"{hamh_url}/api/matter/bridges/{bridge_id}", json=_bridge_payload()
        ) as resp:
            resp.raise_for_status()

        return bridge_id

    async with session.post(
        f"{hamh_url}/api/matter/bridges", json=_bridge_payload()
    ) as resp:
        resp.raise_for_status()
        created = await resp.json()

    bridge_id = created["id"]
    _LOGGER.debug("Created HAMH bridge id=%s", bridge_id)
    return bridge_id


async def _set_entity_mapping(
    session: aiohttp.ClientSession,
    hamh_url: str,
    bridge_id: str,
    vacuum_entity_id: str,
    cleaning_mode_entity_id: str,
    water_level_entity_id: str,
) -> None:
    """Set cleaningModeEntity and mopIntensityEntity on the vacuum entity mapping."""
    url = f"{hamh_url}/api/entity-mappings/{bridge_id}/{vacuum_entity_id}"
    payload = {
        "cleaningModeEntity": cleaning_mode_entity_id,
        "mopIntensityEntity": water_level_entity_id,
    }
    async with session.put(url, json=payload) as resp:
        if resp.status == 404:
            _LOGGER.warning(
                "HAMH entity mapping for %s returned 404 — "
                "bridge may still be starting. Try pressing the button again in a few seconds.",
                vacuum_entity_id,
            )
            raise HomeAssistantError(
                f"HAMH could not find entity {vacuum_entity_id}. "
                "The bridge may still be starting — wait a few seconds and try again."
            )
        resp.raise_for_status()
        _LOGGER.debug("Entity mapping set for %s", vacuum_entity_id)


def _bridge_payload() -> dict:
    return {
        "name": HAMH_BRIDGE_NAME,
        "port": 5541,
        "filter": {
            "include": [{"type": "domain", "value": "vacuum"}],
            "exclude": [],
        },
        "featureFlags": {
            "serverMode": True,
            "vacuumOnOff": True,
        },
    }
