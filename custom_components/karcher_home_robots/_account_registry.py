# SPDX-License-Identifier: MIT
"""Shared KarcherAdapter registry — one adapter per cloud account.

Importing this from both __init__.py and config_flow.py is safe:
it has no dependency on either module and does not create circular imports.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .adapter import AdapterConfig, KarcherAdapter

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _normalize_email(email: str) -> str:
    """Canonicalise an email for use as the account key.

    The shared-adapter design keeps one cloud session per account; the dedup
    key must therefore be case-insensitive, or `User@x.com` and `user@x.com`
    would create two adapters for the same account and (if the cloud is
    single-session) invalidate each other's tokens. Email auth is effectively
    case-insensitive in practice, so the normalised form is also what is handed
    to login.
    """
    return email.strip().casefold()


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
    entry = _accounts(hass).get(_normalize_email(email))
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
    email = _normalize_email(email)
    async with _creation_lock(hass, email):
        accounts = _accounts(hass)

        if email in accounts:
            entry = accounts[email]
            # Reconcile credentials before taking the reuse path: the running
            # adapter logged in with whatever password created it, so an entry
            # carrying a refreshed password (post-reauth) must re-login here or
            # silent_reauth keeps using the stale one. Done before the refcount
            # bump so a failed re-login does not leak a reference.
            await entry.adapter.ensure_credentials(email, password)
            entry.refcount += 1
            _LOGGER.debug(
                "Reusing shared adapter for %s (refcount=%d)", _mask_email(email), entry.refcount
            )
            return entry.adapter

        adapter = KarcherAdapter(hass, AdapterConfig(region=region))
        try:
            await adapter.async_setup()
            await adapter.authenticate(email, password)
        except Exception:
            # async_setup() opened an aiohttp session; if authenticate (or setup)
            # fails the adapter is never registered, so close it here or the
            # session orphans — one leak per ConfigEntryNotReady retry while the
            # cloud is flaky at startup. Best-effort: must not mask the original.
            with contextlib.suppress(Exception):
                await adapter.close()
            raise

        accounts[email] = _AccountEntry(adapter=adapter, refcount=1)
        _LOGGER.debug("Created shared adapter for %s", _mask_email(email))
        return adapter


async def release_adapter(hass: HomeAssistant, email: str) -> None:
    """Decrement refcount for *email*; close and remove adapter when it reaches zero."""
    email = _normalize_email(email)
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
