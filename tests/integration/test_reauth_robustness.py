# SPDX-License-Identifier: MIT
"""Reauth robustness tests.

Covers: FR-A-8, FR-A-8a, FR-A-8b
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from custom_components.karcher_home_robots.adapter import AdapterConfig, KarcherAdapter
from custom_components.karcher_home_robots.coordinator import KarcherCoordinator
from custom_components.karcher_home_robots.exceptions import (
    AuthError,
    InvalidCredentials,
    TokenRejected,
    TransientError,
)
from homeassistant.exceptions import ConfigEntryAuthFailed
from karcher.exception import KarcherHomeException, KarcherHomeInvalidAuth
from tests.conftest import PROPS_IDLE, TEST_DEVICE


@pytest.fixture
def fake_hass_for_adapter() -> MagicMock:
    hass = MagicMock()

    async def async_add_executor_job(func: Any, *args: Any) -> Any:
        return func(*args)

    hass.async_add_executor_job = async_add_executor_job
    return hass


async def _make_adapter(fake_hass: MagicMock) -> KarcherAdapter:
    fake_client = MagicMock()
    fake_client._base_url = "https://eu.example.com"
    fake_client._mqtt_url = None
    fake_client.login = AsyncMock()
    adapter = KarcherAdapter(fake_hass, AdapterConfig(), lambda: fake_client)
    await adapter.async_setup()
    adapter._email = "user@example.com"
    adapter._password = "secret"  # noqa: S105
    return adapter


# ---------------------------------------------------------------------------
# silent_reauth: happy path
# ---------------------------------------------------------------------------


async def test_silent_reauth_succeeds_on_first_attempt(
    fake_hass_for_adapter: MagicMock,
) -> None:
    """silent_reauth calls _login and resets the counter on success.

    Covers: FR-A-8
    """
    adapter = await _make_adapter(fake_hass_for_adapter)
    adapter._client.login = AsyncMock()  # type: ignore[union-attr]

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await adapter.silent_reauth()

    assert adapter._reauth_attempts == 0  # reset after success


# ---------------------------------------------------------------------------
# silent_reauth: limit enforcement (FR-A-8a)
# ---------------------------------------------------------------------------


async def test_silent_reauth_raises_after_max_attempts(
    fake_hass_for_adapter: MagicMock,
) -> None:
    """After 3 attempts in a 5-min window, silent_reauth raises AuthError.

    Covers: FR-A-8a
    """
    adapter = await _make_adapter(fake_hass_for_adapter)
    # Simulate 3 previous attempts in the current window.
    adapter._reauth_attempts = 3
    adapter._reauth_window_start = asyncio.get_event_loop().time()

    with pytest.raises(AuthError, match="limit reached"):
        await adapter.silent_reauth()


async def test_silent_reauth_window_resets_after_expiry(
    fake_hass_for_adapter: MagicMock,
) -> None:
    """Attempt counter resets after the 5-minute window expires.

    Covers: FR-A-8a
    """
    adapter = await _make_adapter(fake_hass_for_adapter)
    adapter._client.login = AsyncMock()  # type: ignore[union-attr]
    # Simulate a window that started 400 s ago (expired).
    adapter._reauth_attempts = 3
    adapter._reauth_window_start = asyncio.get_event_loop().time() - 400.0

    with patch("asyncio.sleep", new_callable=AsyncMock):
        # Should not raise — old window is discarded.
        await adapter.silent_reauth()

    assert adapter._reauth_attempts == 0


# ---------------------------------------------------------------------------
# silent_reauth: wrong credentials → immediate AuthError (FR-A-8b)
# ---------------------------------------------------------------------------


async def test_silent_reauth_invalid_credentials_raises_immediately(
    fake_hass_for_adapter: MagicMock,
) -> None:
    """InvalidCredentials from _login propagates as AuthError without further retries.

    Covers: FR-A-8b
    """
    adapter = await _make_adapter(fake_hass_for_adapter)
    # KarcherHomeInvalidAuth() takes no arguments.
    adapter._client.login = AsyncMock(side_effect=KarcherHomeInvalidAuth())  # type: ignore[union-attr]

    with patch("asyncio.sleep", new_callable=AsyncMock), pytest.raises(InvalidCredentials):
        await adapter.silent_reauth()


# ---------------------------------------------------------------------------
# silent_reauth: transient login failure → TransientError (FR-A-8b)
# ---------------------------------------------------------------------------


async def test_silent_reauth_transient_login_raises_transient(
    fake_hass_for_adapter: MagicMock,
) -> None:
    """A non-auth ClientError from _login is re-raised as TransientError.

    Covers: FR-A-8b
    """
    adapter = await _make_adapter(fake_hass_for_adapter)
    # KarcherHomeException(code, message)
    adapter._client.login = AsyncMock(side_effect=KarcherHomeException(500, "network glitch"))  # type: ignore[union-attr]

    with patch("asyncio.sleep", new_callable=AsyncMock), pytest.raises(TransientError):
        await adapter.silent_reauth()


# ---------------------------------------------------------------------------
# Coordinator wires silent reauth on TokenRejected (FR-A-8)
# ---------------------------------------------------------------------------


async def test_coordinator_retries_after_token_rejected(hass: Any) -> None:
    """When fetch_properties raises TokenRejected, coordinator calls silent_reauth then retries.

    Covers: FR-A-8
    """
    adapter = MagicMock()
    # First call raises TokenRejected; second (after reauth) succeeds.
    adapter.fetch_properties = AsyncMock(side_effect=[TokenRejected("expired"), PROPS_IDLE])
    adapter.silent_reauth = AsyncMock(return_value=None)

    coord = KarcherCoordinator(hass, adapter, TEST_DEVICE)
    result = await coord._async_update_data()

    assert result == PROPS_IDLE
    adapter.silent_reauth.assert_awaited_once()


async def test_coordinator_raises_config_entry_auth_failed_after_reauth_limit(
    hass: Any,
) -> None:
    """ConfigEntryAuthFailed is raised if silent_reauth hits the attempt limit.

    Covers: FR-A-8a
    """
    adapter = MagicMock()
    adapter.fetch_properties = AsyncMock(side_effect=TokenRejected("expired"))
    adapter.silent_reauth = AsyncMock(side_effect=AuthError("limit reached"))

    coord = KarcherCoordinator(hass, adapter, TEST_DEVICE)
    with pytest.raises(ConfigEntryAuthFailed):
        await coord._async_update_data()
