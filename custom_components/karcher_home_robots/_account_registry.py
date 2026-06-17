# SPDX-License-Identifier: MIT
"""Shared KarcherAdapter registry — one adapter per cloud account.

Importing this from both __init__.py and config_flow.py is safe:
it has no dependency on either module and does not create circular imports.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .adapter import AdapterConfig, KarcherAdapter

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _mask_email(email: str) -> str:
    """Mask an email for debug logs: keep first char + domain (j***@example.com)."""
    local, _, domain = email.partition("@")
    if not domain or not local:
        return "***"
    return f"{local[0]}***@{domain}"


@dataclass
class _AccountEntry:
    """Shared adapter + refcount for one cloud account (keyed by email)."""

    adapter: KarcherAdapter
    refcount: int = field(default=0)


def _integration_data(hass: HomeAssistant) -> dict[str, object]:
    result: dict[str, object] = hass.data.setdefault(DOMAIN, {})
    return result


def _accounts(hass: HomeAssistant) -> dict[str, _AccountEntry]:
    data = _integration_data(hass)
    result: dict[str, _AccountEntry] = data.setdefault("accounts", {})  # type: ignore[assignment]
    return result


def _creation_lock(hass: HomeAssistant, email: str) -> asyncio.Lock:
    """Return a per-email lock used to serialise concurrent adapter creation."""
    data = _integration_data(hass)
    locks: dict[str, asyncio.Lock] = data.setdefault("account_locks", {})  # type: ignore[assignment]
    if email not in locks:
        locks[email] = asyncio.Lock()
    return locks[email]


def get_shared_adapter(hass: HomeAssistant, email: str) -> KarcherAdapter | None:
    """Return the running shared adapter for *email*, or None if not yet created."""
    entry = _accounts(hass).get(email)
    return entry.adapter if entry is not None else None


async def get_or_create_adapter(
    hass: HomeAssistant,
    email: str,
    password: str,
    region: str,
) -> KarcherAdapter:
    """Return the shared KarcherAdapter for *email*, creating it on first call.

    Serialised per-email so concurrent async_setup_entry calls for the same
    account never race: the second caller waits for the first to finish
    authenticating, then takes the reuse path.

    Raises the same exceptions as KarcherAdapter.authenticate() so the caller
    can surface them as ConfigEntry errors.
    """
    async with _creation_lock(hass, email):
        accounts = _accounts(hass)

        if email in accounts:
            entry = accounts[email]
            entry.refcount += 1
            _LOGGER.debug(
                "Reusing shared adapter for %s (refcount=%d)", _mask_email(email), entry.refcount
            )
            return entry.adapter

        adapter = KarcherAdapter(hass, AdapterConfig(region=region))
        await adapter.async_setup()
        await adapter.authenticate(email, password)

        accounts[email] = _AccountEntry(adapter=adapter, refcount=1)
        _LOGGER.debug("Created shared adapter for %s", _mask_email(email))
        return adapter


async def release_adapter(hass: HomeAssistant, email: str) -> None:
    """Decrement refcount for *email*; close and remove adapter when it reaches zero."""
    accounts = _accounts(hass)

    if email not in accounts:
        return

    entry = accounts[email]
    entry.refcount -= 1
    _LOGGER.debug(
        "Released shared adapter for %s (refcount=%d)", _mask_email(email), entry.refcount
    )

    if entry.refcount <= 0:
        del accounts[email]
        await entry.adapter.close()
        _LOGGER.debug("Closed shared adapter for %s", _mask_email(email))
