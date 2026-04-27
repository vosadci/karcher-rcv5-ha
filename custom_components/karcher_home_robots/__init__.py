"""Kärcher Home Robots integration entry point.

Satisfies: FR-A-1 (integration loadable by HA), FR-A-2 (config entry
lifecycle). All functional behaviour is deferred to Phase 1.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry. Returns True unconditionally at Phase 0."""
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry. Returns True unconditionally at Phase 0."""
    return True
