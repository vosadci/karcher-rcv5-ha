# SPDX-License-Identifier: MIT
"""Integration tests for entry setup and unload lifecycle.

Tests use a FakeAdapter injected via patch so no real network or MQTT
connections are made.

"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from custom_components.karcher_home_robots._account_registry import get_shared_adapter
from custom_components.karcher_home_robots.adapter import Device
from custom_components.karcher_home_robots.const import DOMAIN
from custom_components.karcher_home_robots.coordinator import KarcherCoordinator
from custom_components.karcher_home_robots.exceptions import (
    AuthError,
    NetworkError,
    PermanentError,
    TransientError,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import (
    ENTRY_DATA,
    TEST_ROOMS,
    FakeAdapter,
    make_entry,
    patch_adapter,
)

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_setup_entry_creates_coordinator(hass: HomeAssistant) -> None:
    """setup_entry stores a coordinator in entry.runtime_data."""
    fake = FakeAdapter()
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data, KarcherCoordinator)


async def test_setup_loads_rooms(hass: HomeAssistant) -> None:
    """setup_entry populates coordinator.rooms from the adapter."""
    fake = FakeAdapter(rooms=TEST_ROOMS)
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator: KarcherCoordinator = entry.runtime_data
    assert len(coordinator.rooms) == 2
    assert coordinator.rooms[0].name == "Living Room"
    assert coordinator.rooms[1].name == "Bedroom"


async def test_setup_auth_failure_raises_config_entry_auth_failed(
    hass: HomeAssistant,
) -> None:
    """Auth failure during setup surfaces as ConfigEntryAuthFailed."""
    fake = FakeAdapter(authenticate_raises=AuthError("bad creds"))
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


# ---------------------------------------------------------------------------
# Reconnect-from-snapshot (DC2)
# ---------------------------------------------------------------------------

_SNAPSHOT: dict[str, str | None] = {
    "rest_base_url": "https://eu.api.example.com",
    "mqtt_url": "mqtts://eu.mqtt.example.com:8883",
}


async def test_setup_seeds_from_snapshot_skipping_discovery(hass: HomeAssistant) -> None:
    """A stored snapshot seeds setup; discovery (async_setup with no snapshot) is never run."""
    # Discovery would fail (broker up, discovery endpoint down) — but it must not be reached.
    fake = FakeAdapter(setup_raises_without_snapshot=NetworkError("discovery endpoint down"))
    entry = make_entry(region_endpoint_snapshot=_SNAPSHOT)
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    # Setup was driven by the seeded snapshot, with no discovery fallback.
    assert fake.setup_snapshots == [_SNAPSHOT]
    # Write-back sees the same endpoints the adapter reports, so the good stored
    # snapshot is preserved (not clobbered).
    assert entry.data["region_endpoint_snapshot"] == _SNAPSHOT


async def test_setup_falls_back_to_discovery_on_transient(hass: HomeAssistant) -> None:
    """A stale snapshot that fails transiently retries once with live discovery."""
    fake = FakeAdapter(setup_raises_with_snapshot=NetworkError("stale endpoint"))
    entry = make_entry(region_endpoint_snapshot=_SNAPSHOT)
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    # Seeded attempt raised, then a single discovery retry (snapshot=None) succeeded.
    assert fake.setup_snapshots == [_SNAPSHOT, None]
    # The post-setup write-back re-persisted whatever endpoints discovery resolved.
    assert entry.data["region_endpoint_snapshot"] == fake.get_endpoint_snapshot()


async def test_get_or_create_falls_back_to_discovery_on_transient(hass: HomeAssistant) -> None:
    """get_or_create_adapter closes the seeded adapter and retries discovery on TransientError."""
    from unittest.mock import AsyncMock, MagicMock

    from custom_components.karcher_home_robots._account_registry import (
        get_or_create_adapter,
        release_adapter,
    )

    instances: list[MagicMock] = []

    def _make(*args: Any, **kwargs: Any) -> MagicMock:
        m = MagicMock()
        m.close = AsyncMock()
        m.authenticate = AsyncMock()
        m.ensure_credentials = AsyncMock()
        # First (seeded) adapter fails transiently; the discovery retry succeeds.
        m.async_setup = AsyncMock(side_effect=NetworkError("stale") if not instances else None)
        instances.append(m)
        return m

    with patch(
        "custom_components.karcher_home_robots._account_registry.KarcherAdapter",
        side_effect=_make,
    ):
        adapter = await get_or_create_adapter(
            hass, "u@e.com", "pw", "eu", endpoint_snapshot=_SNAPSHOT
        )

    assert len(instances) == 2
    assert adapter is instances[1]
    instances[0].async_setup.assert_awaited_once_with(endpoint_snapshot=_SNAPSHOT)
    instances[0].close.assert_awaited_once()
    instances[1].async_setup.assert_awaited_once_with(endpoint_snapshot=None)
    instances[1].authenticate.assert_awaited_once()
    await release_adapter(hass, "u@e.com")


async def test_get_or_create_no_fallback_without_snapshot(hass: HomeAssistant) -> None:
    """A TransientError with no snapshot propagates — there is nothing to fall back to."""
    from unittest.mock import AsyncMock, MagicMock

    from custom_components.karcher_home_robots._account_registry import get_or_create_adapter

    instances: list[MagicMock] = []

    def _make(*args: Any, **kwargs: Any) -> MagicMock:
        m = MagicMock()
        m.close = AsyncMock()
        m.authenticate = AsyncMock()
        m.async_setup = AsyncMock(side_effect=NetworkError("down"))
        instances.append(m)
        return m

    with (
        patch(
            "custom_components.karcher_home_robots._account_registry.KarcherAdapter",
            side_effect=_make,
        ),
        pytest.raises(NetworkError),
    ):
        await get_or_create_adapter(hass, "u@e.com", "pw", "eu", endpoint_snapshot=None)

    assert len(instances) == 1  # no discovery-retry adapter was constructed
    instances[0].close.assert_awaited_once()


async def test_get_or_create_auth_error_does_not_retry(hass: HomeAssistant) -> None:
    """An AuthError on the seeded attempt propagates immediately — no discovery retry."""
    from unittest.mock import AsyncMock, MagicMock

    from custom_components.karcher_home_robots._account_registry import get_or_create_adapter

    instances: list[MagicMock] = []

    def _make(*args: Any, **kwargs: Any) -> MagicMock:
        m = MagicMock()
        m.close = AsyncMock()
        m.async_setup = AsyncMock()
        m.authenticate = AsyncMock(side_effect=AuthError("bad password"))
        instances.append(m)
        return m

    with (
        patch(
            "custom_components.karcher_home_robots._account_registry.KarcherAdapter",
            side_effect=_make,
        ),
        pytest.raises(AuthError),
    ):
        await get_or_create_adapter(hass, "u@e.com", "pw", "eu", endpoint_snapshot=_SNAPSHOT)

    assert len(instances) == 1  # AuthError is not TransientError → no fallback
    instances[0].close.assert_awaited_once()


async def test_unload_entry_shuts_down_coordinator(hass: HomeAssistant) -> None:
    """Unloading the last entry for an account closes the shared adapter."""
    fake = FakeAdapter()
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        result = await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert entry.state is ConfigEntryState.NOT_LOADED
    # Adapter is shared — it closes when the refcount reaches zero (last entry).
    assert fake.closed is True
    # Unloading the last entry must remove the domain services (the entry is still
    # in async_entries() during unload, so a naive emptiness check would miss this).
    assert not hass.services.async_services().get(DOMAIN)


async def test_two_entries_independent(hass: HomeAssistant) -> None:
    """Two config entries for different accounts each get their own coordinator.

    Entries with the same email share one adapter; entries with different emails
    each get their own. Either way, coordinators are always independent objects.
    Here we use different emails so each entry gets its own FakeAdapter.
    """
    device_a = Device(
        device_id="dev-a",
        sn="SN-A",
        product_id="1540149850806333440",
        nickname="Robot A",
        mac="AA:BB:CC:DD:EE:FF",
        product_mode_code="CRL350",
    )
    device_b = Device(
        device_id="dev-b",
        sn="SN-B",
        product_id="1540149850806333440",
        nickname="Robot B",
        mac="AA:BB:CC:DD:EE:F0",
        product_mode_code="CRL350",
    )
    fake_a = FakeAdapter(devices=[device_a])
    fake_b = FakeAdapter(devices=[device_b])

    entry_a = MockConfigEntry(
        domain=DOMAIN,
        data={**ENTRY_DATA, "email": "account-a@example.com", "device_id": device_a.device_id},
        unique_id=device_a.device_id,
        version=3,
    )
    entry_b = MockConfigEntry(
        domain=DOMAIN,
        data={**ENTRY_DATA, "email": "account-b@example.com", "device_id": device_b.device_id},
        unique_id=device_b.device_id,
        version=3,
    )
    entry_a.add_to_hass(hass)
    entry_b.add_to_hass(hass)

    fakes = [fake_a, fake_b]
    call_idx: list[int] = [0]

    def _factory(*args: Any, **kwargs: Any) -> FakeAdapter:
        result = fakes[call_idx[0] % len(fakes)]
        call_idx[0] += 1
        return result

    with patch(
        "custom_components.karcher_home_robots._account_registry.KarcherAdapter",
        side_effect=_factory,
    ):
        # Setting up entry_a causes HA to schedule all entries in the domain;
        # block_till_done processes both.
        await hass.config_entries.async_setup(entry_a.entry_id)
        await hass.async_block_till_done()

    assert entry_a.state is ConfigEntryState.LOADED
    assert entry_b.state is ConfigEntryState.LOADED
    coord_a: KarcherCoordinator = entry_a.runtime_data
    coord_b: KarcherCoordinator = entry_b.runtime_data
    assert coord_a is not coord_b


async def test_same_account_two_robots_share_one_adapter(hass: HomeAssistant) -> None:
    """Two entries for the same account share one KarcherAdapter (only one login call)."""
    device_a = Device(
        device_id="dev-a",
        sn="SN-A",
        product_id="1540149850806333440",
        nickname="Robot A",
        mac="AA:BB:CC:DD:EE:FF",
        product_mode_code="CRL350",
    )
    device_b = Device(
        device_id="dev-b",
        sn="SN-B",
        product_id="1540149850806333440",
        nickname="Robot B",
        mac="AA:BB:CC:DD:EE:F0",
        product_mode_code="CRL350",
    )
    # Single FakeAdapter knows about both devices — simulates one cloud account.
    fake = FakeAdapter(devices=[device_a, device_b])

    entry_a = MockConfigEntry(
        domain=DOMAIN,
        data={**ENTRY_DATA, "device_id": device_a.device_id},
        unique_id=device_a.device_id,
        version=3,
    )
    entry_b = MockConfigEntry(
        domain=DOMAIN,
        data={**ENTRY_DATA, "device_id": device_b.device_id},
        unique_id=device_b.device_id,
        version=3,
    )
    entry_a.add_to_hass(hass)
    entry_b.add_to_hass(hass)

    adapter_instances: list[Any] = []

    def _factory(*args: Any, **kwargs: Any) -> FakeAdapter:
        adapter_instances.append(fake)
        return fake

    with patch(
        "custom_components.karcher_home_robots._account_registry.KarcherAdapter",
        side_effect=_factory,
    ):
        await hass.config_entries.async_setup(entry_a.entry_id)
        await hass.async_block_till_done()

    assert entry_a.state is ConfigEntryState.LOADED
    assert entry_b.state is ConfigEntryState.LOADED

    # Only one KarcherAdapter was constructed (second entry reused the shared one).
    assert len(adapter_instances) == 1

    # Unloading the first entry must NOT close the adapter (refcount still 1).
    result_a = await hass.config_entries.async_unload(entry_a.entry_id)
    await hass.async_block_till_done()
    assert result_a is True
    assert not fake.closed

    # Unloading the second (last) entry closes the shared adapter.
    result_b = await hass.config_entries.async_unload(entry_b.entry_id)
    await hass.async_block_till_done()
    assert result_b is True
    assert fake.closed


async def test_reuse_with_changed_password_relogs_in(hass: HomeAssistant) -> None:
    """A second entry carrying a refreshed password re-logs the shared adapter.

    Regression guard: the reuse path used to ignore the supplied password, so a
    reauth on a multi-robot account never reached the running adapter and silent
    reauth kept retrying the stale password.
    """
    from custom_components.karcher_home_robots._account_registry import (
        get_or_create_adapter,
        release_adapter,
    )

    fake = FakeAdapter()

    def _factory(*args: Any, **kwargs: Any) -> FakeAdapter:
        return fake

    with patch(
        "custom_components.karcher_home_robots._account_registry.KarcherAdapter",
        side_effect=_factory,
    ):
        await get_or_create_adapter(hass, "test@example.com", "old-pw", "eu")
        assert fake.login_count == 1
        assert fake.password == "old-pw"  # noqa: S105

        # Same password → reuse, no extra login.
        await get_or_create_adapter(hass, "test@example.com", "old-pw", "eu")
        assert fake.login_count == 1

        # Changed password → re-login on the shared adapter.
        await get_or_create_adapter(hass, "test@example.com", "new-pw", "eu")
        assert fake.login_count == 2
        assert fake.password == "new-pw"  # noqa: S105

    await release_adapter(hass, "test@example.com")
    await release_adapter(hass, "test@example.com")
    await release_adapter(hass, "test@example.com")


async def test_account_key_is_case_insensitive(hass: HomeAssistant) -> None:
    """Differently-cased emails for the same account share one adapter.

    Regression guard: the registry used to key on the raw email, so
    `User@Example.com` and `user@example.com` created two adapters for one
    cloud account, defeating the per-account dedup.
    """
    from custom_components.karcher_home_robots._account_registry import (
        get_or_create_adapter,
        get_shared_adapter,
        release_adapter,
    )

    instances: list[FakeAdapter] = []

    def _factory(*args: Any, **kwargs: Any) -> FakeAdapter:
        fake = FakeAdapter()
        instances.append(fake)
        return fake

    with patch(
        "custom_components.karcher_home_robots._account_registry.KarcherAdapter",
        side_effect=_factory,
    ):
        first = await get_or_create_adapter(hass, "User@Example.com", "secret", "eu")
        second = await get_or_create_adapter(hass, "user@example.com", "secret", "eu")

    assert first is second
    assert len(instances) == 1
    # Lookups normalise too — a different casing finds the same adapter.
    assert get_shared_adapter(hass, "USER@EXAMPLE.COM") is first

    await release_adapter(hass, "user@example.com")
    await release_adapter(hass, "User@Example.com")


async def test_get_or_create_adapter_concurrent_calls_create_one_adapter(
    hass: HomeAssistant,
) -> None:
    """Concurrent get_or_create_adapter calls for the same email create one adapter.

    The per-email lock serialises creation: the second coroutine waits for the
    first to finish authenticating, then takes the reuse path.

    Simulated by making FakeAdapter.authenticate() yield (sleep(0)) so the
    second coroutine enters get_or_create_adapter before the first has inserted
    the adapter into the registry.  Without the lock, both would call
    authenticate() and the second login would invalidate the first's session.
    """
    from custom_components.karcher_home_robots._account_registry import (
        get_or_create_adapter,
        release_adapter,
    )

    fake = FakeAdapter()
    authenticate_call_count: list[int] = [0]
    original_authenticate = fake.authenticate

    async def _slow_authenticate(email: str, password: str) -> None:
        authenticate_call_count[0] += 1
        await asyncio.sleep(0)  # yield to let the second coroutine reach the lock
        await original_authenticate(email, password)

    fake.authenticate = _slow_authenticate  # type: ignore[method-assign]

    adapter_instances: list[Any] = []

    def _factory(*args: Any, **kwargs: Any) -> FakeAdapter:
        adapter_instances.append(fake)
        return fake

    with patch(
        "custom_components.karcher_home_robots._account_registry.KarcherAdapter",
        side_effect=_factory,
    ):
        results = await asyncio.gather(
            get_or_create_adapter(hass, "test@example.com", "secret", "eu"),
            get_or_create_adapter(hass, "test@example.com", "secret", "eu"),
        )

    adapter_a, adapter_b = results
    assert adapter_a is adapter_b, "Both callers must receive the same adapter instance"
    assert len(adapter_instances) == 1, "KarcherAdapter must be constructed only once"
    assert authenticate_call_count[0] == 1, "authenticate() must be called only once"

    # Clean up refcount (both callers incremented it).
    await release_adapter(hass, "test@example.com")
    await release_adapter(hass, "test@example.com")


async def test_get_or_create_adapter_closes_on_auth_failure(hass: HomeAssistant) -> None:
    """A failed authenticate() closes the adapter instead of orphaning its session.

    Regression guard: get_or_create_adapter opens an aiohttp session in
    async_setup(); if authenticate() raises the adapter is never registered, so
    it must be closed here or the session leaks (one per ConfigEntryNotReady
    retry while the cloud is flaky at startup).
    """
    from custom_components.karcher_home_robots._account_registry import get_or_create_adapter

    fake = FakeAdapter(authenticate_raises=AuthError("bad password"))

    with (
        patch(
            "custom_components.karcher_home_robots._account_registry.KarcherAdapter",
            return_value=fake,
        ),
        pytest.raises(AuthError),
    ):
        await get_or_create_adapter(hass, "test@example.com", "secret", "eu")

    assert fake.closed, "adapter must be closed when authenticate fails"
    assert get_shared_adapter(hass, "test@example.com") is None, "no adapter must be registered"


async def test_device_not_on_account_fails_setup(hass: HomeAssistant) -> None:
    """If the stored device_id is not in the account device list, setup fails."""
    other_device = Device(
        device_id="other-device",
        sn="SN999",
        product_id="1540149850806333440",
        nickname="Other",
        mac="00:00:00:00:00:00",
        product_mode_code="CRL350",
    )
    fake = FakeAdapter(devices=[other_device])
    entry = make_entry()  # device_id = TEST_DEVICE.device_id, not "other-device"
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_fetch_transient_error_marks_unavailable(hass: HomeAssistant) -> None:
    """A TransientError from fetch_properties does not crash setup but marks unavailable."""
    fake = FakeAdapter(fetch_raises=TransientError("timeout"))
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        # async_config_entry_first_refresh raises UpdateFailed on TransientError
        # which puts the entry in SETUP_RETRY rather than LOADED
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state in (ConfigEntryState.SETUP_RETRY, ConfigEntryState.SETUP_ERROR)


async def test_failed_first_refresh_releases_adapter(hass: HomeAssistant) -> None:
    """A setup failure after adapter acquisition releases refcount and subscription.

    Regression guard: ConfigEntryNotReady from the first refresh (cloud down at
    HA start) leaked one adapter refcount per setup retry and left the failed
    attempt's MQTT subscription registered, so the shared adapter was never
    released or closed even after the entry was eventually unloaded.
    """
    fake = FakeAdapter(fetch_raises=TransientError("timeout"))
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state in (ConfigEntryState.SETUP_RETRY, ConfigEntryState.SETUP_ERROR)
    # The failed attempt must fully unwind: no shared adapter left in the
    # registry (refcount back to zero → closed), no dangling MQTT subscription.
    assert get_shared_adapter(hass, ENTRY_DATA["email"]) is None
    assert fake.subscribed is False
    assert fake.closed is True


async def test_setup_permanent_error_raises_config_entry_error(hass: HomeAssistant) -> None:
    """PermanentError during authenticate surfaces as ConfigEntryError (→ SETUP_ERROR)."""
    fake = FakeAdapter(authenticate_raises=PermanentError("device banned"))
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_transient_error_during_auth_raises_config_entry_not_ready(
    hass: HomeAssistant,
) -> None:
    """TransientError during authenticate surfaces as ConfigEntryNotReady (→ SETUP_RETRY)."""
    fake = FakeAdapter(authenticate_raises=TransientError("timeout"))
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state in (ConfigEntryState.SETUP_RETRY, ConfigEntryState.SETUP_ERROR)


async def test_setup_writes_endpoint_snapshot_to_entry(hass: HomeAssistant) -> None:
    """async_setup_entry persists the endpoint snapshot in entry.data."""
    fake = FakeAdapter()
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert "region_endpoint_snapshot" in entry.data
    assert entry.data["region_endpoint_snapshot"]["rest_base_url"] == "https://fake.example.com"


async def test_setup_skips_snapshot_update_when_already_current(hass: HomeAssistant) -> None:
    """No entry update when the stored snapshot already matches the fresh one."""
    snapshot = {"rest_base_url": "https://fake.example.com", "mqtt_url": None}
    fake = FakeAdapter()
    entry = make_entry(region_endpoint_snapshot=snapshot)
    entry.add_to_hass(hass)

    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    # Snapshot was pre-populated with the same value the adapter returns,
    # so async_update_entry should not have changed it.
    assert entry.data["region_endpoint_snapshot"] == snapshot
