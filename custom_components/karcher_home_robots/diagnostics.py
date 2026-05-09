# SPDX-License-Identifier: MIT
"""Diagnostics endpoint — redacted config entry dump.

Covers: FR-D-1, FR-D-2
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .adapter import KARCHER_HOME_VERSION
from .coordinator import KarcherCoordinator

# Redaction policy: any dict key whose name contains one of these words
# (whole-word match, case-insensitive) has its value replaced with
# _REDACTED before the diagnostics bundle is returned to the user.
# Covers: credentials (password, secret, api_key, token, nonce),
#         device identifiers (device_id, sn, serial, mac),
#         user PII (email),
#         connection endpoints (mqtt_url, broker, client_id).
_REDACT = re.compile(
    r"(?i)\b(password|secret|api_key|token|nonce|email"
    r"|device_id|sn|serial|mac"
    r"|mqtt_url|broker|client_id)\b",
)

_REDACTED = "**REDACTED**"


def _redact(value: Any) -> Any:
    """Recursively redact sensitive keys from a dict/list tree."""
    if isinstance(value, dict):
        return {k: (_REDACTED if _REDACT.search(k) else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return a redacted diagnostic bundle for this config entry.

    Covers: FR-D-1
    The bundle includes config-entry data (redacted), last-known device
    properties, room list, coordinator state, and library version.
    """
    coordinator: KarcherCoordinator = entry.runtime_data

    data = _redact(dict(entry.data))

    props = coordinator.data
    props_dict: dict[str, Any] | None = None
    if props is not None:
        props_dict = {
            "battery": props.battery,
            "cleaning_area": props.cleaning_area,
            "cleaning_time": props.cleaning_time,
            "work_mode": props.work_mode,
            "status": props.status,
            "charge_state": props.charge_state,
            "fault": props.fault,
            "wind": props.wind,
            "water": props.water,
            "mode": props.mode,
            "current_map_id": props.current_map_id,
        }

    rooms = [{"room_id": r.room_id, "name": r.name} for r in coordinator.rooms]

    return {
        "entry_data": data,
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "vacuum_state": coordinator.vacuum_state.value,
            "selected_room_id": coordinator.get_selected_room_id(),
        },
        "device_properties": props_dict,
        "rooms": rooms,
        "karcher_home_version": KARCHER_HOME_VERSION,
    }
