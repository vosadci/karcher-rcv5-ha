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

# Redaction policy: a dict key is redacted when any of its underscore/non-alnum
# delimited tokens matches a single sensitive token, OR the whole key matches a
# sensitive compound phrase. Tokenising (rather than substring matching) catches
# compound keys (rest_base_url → "url") while avoiding false positives: "sn"
# must not match "snapshot", and "id" alone must not match room_id / color_id.
# Covers: credentials (password, secret, api_key, token, nonce),
#         device identifiers (device_id, client_id, sn, serial, mac),
#         user PII (email),
#         connection endpoints (url, broker, host).
_SENSITIVE_TOKENS = frozenset(
    {
        "password",
        "secret",
        "token",
        "nonce",
        "email",
        "sn",
        "serial",
        "mac",
        "url",
        "broker",
        "host",
    }
)

# Phrases matched against the whole tokenised key (joined with "_") — for
# identifiers where a bare token would over-redact (e.g. plain "id").
_SENSITIVE_PHRASES = frozenset({"device_id", "client_id", "api_key"})

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")

_REDACTED = "**REDACTED**"


def _is_sensitive_key(key: str) -> bool:
    tokens = [t for t in _TOKEN_SPLIT.split(key.lower()) if t]
    if any(t in _SENSITIVE_TOKENS for t in tokens):
        return True
    return "_".join(tokens) in _SENSITIVE_PHRASES


def _redact(value: Any) -> Any:
    """Recursively redact sensitive keys from a dict/list tree."""
    if isinstance(value, dict):
        return {k: (_REDACTED if _is_sensitive_key(k) else _redact(v)) for k, v in value.items()}
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
