# SPDX-License-Identifier: MIT
"""Integration tests for the QoS 0 command-verification wait in async_send_command."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from custom_components.karcher_home_robots.const import DOMAIN
from custom_components.karcher_home_robots.coordinator import KarcherCoordinator
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import (
    ENTRY_DATA,
    PROPS_CLEANING,
    PROPS_IDLE,
    TEST_DEVICE,
    FakeAdapter,
    make_entry,
    make_props,
    patch_adapter,
)

_LOGGER_NAME = "custom_components.karcher_home_robots.coordinator"


async def _setup(hass: HomeAssistant, fake: FakeAdapter) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id=TEST_DEVICE.device_id,
        version=3,
    )
    entry.add_to_hass(hass)
    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


# ---------------------------------------------------------------------------
# (a) command -> push confirms the transition -> no WARNING
# ---------------------------------------------------------------------------


async def test_command_confirmed_by_push_logs_no_warning(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A push that changes work_mode after a command confirms it; no WARNING."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    with (
        patch("custom_components.karcher_home_robots.coordinator._COMMAND_VERIFY_TIMEOUT", 0.5),
        caplog.at_level(logging.WARNING, logger=_LOGGER_NAME),
    ):
        await coordinator.async_send_command("start_recharge", {})
        # The verify task is eager-started: by the time async_send_command
        # returns, its listener is already registered (registration happens
        # synchronously before the first await). Firing the push here lands
        # deterministically inside the wait window, not racing it.
        fake.fire_push(PROPS_CLEANING)
        await hass.async_block_till_done()

    assert "No work_mode change observed" not in caplog.text


# ---------------------------------------------------------------------------
# (b) command -> no transition observed -> WARNING (naming the service)
# ---------------------------------------------------------------------------


async def test_command_unconfirmed_logs_warning_with_service_name(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No matching push arrives before the timeout: a WARNING names the service."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    with (
        patch("custom_components.karcher_home_robots.coordinator._COMMAND_VERIFY_TIMEOUT", 0.05),
        caplog.at_level(logging.WARNING, logger=_LOGGER_NAME),
    ):
        await coordinator.async_send_command("stop_recharge", {})
        await hass.async_block_till_done()

    assert "No work_mode change observed" in caplog.text
    assert "stop_recharge" in caplog.text


async def test_command_unconfirmed_ignores_unrelated_update_same_work_mode(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A push that lands but leaves work_mode unchanged does not confirm the command."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    with (
        patch("custom_components.karcher_home_robots.coordinator._COMMAND_VERIFY_TIMEOUT", 0.05),
        caplog.at_level(logging.WARNING, logger=_LOGGER_NAME),
    ):
        await coordinator.async_send_command("stop_recharge", {})
        # Same work_mode as PROPS_IDLE, different battery — a real push, but
        # not evidence this command took effect.
        fake.fire_push(make_props(work_mode=0, status=0, charge_state=0, fault=0, battery=79))
        await hass.async_block_till_done()

    assert "No work_mode change observed" in caplog.text


# ---------------------------------------------------------------------------
# Coordinator-level edge cases (direct calls, no entity/service layer)
# ---------------------------------------------------------------------------


async def test_verify_command_effect_returns_immediately_if_already_changed(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If work_mode already differs by the time the verify task starts running,
    it returns without registering a listener or waiting — and logs nothing."""
    adapter = MagicMock()
    entry = make_entry()
    entry.add_to_hass(hass)
    coord = KarcherCoordinator(hass, adapter, TEST_DEVICE, config_entry=entry)
    coord.data = PROPS_CLEANING  # work_mode already != the captured "before" value

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        await coord._verify_command_effect("start_recharge", PROPS_IDLE.work_mode)

    assert "No work_mode change observed" not in caplog.text


async def test_send_command_captures_none_when_data_absent(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """async_send_command tolerates self.data being None (never polled/pushed yet)."""
    adapter = MagicMock()
    adapter.send_command = AsyncMock()
    entry = make_entry()
    entry.add_to_hass(hass)
    coord = KarcherCoordinator(hass, adapter, TEST_DEVICE, config_entry=entry)
    assert coord.data is None

    with (
        patch("custom_components.karcher_home_robots.coordinator._COMMAND_VERIFY_TIMEOUT", 0.05),
        caplog.at_level(logging.WARNING, logger=_LOGGER_NAME),
    ):
        await coord.async_send_command("stop_recharge", {})
        await hass.async_block_till_done()

    adapter.send_command.assert_awaited_once()
    assert "No work_mode change observed" in caplog.text
    assert "stop_recharge" in caplog.text


async def test_verify_task_is_tracked_and_cancelled_on_shutdown(hass: HomeAssistant) -> None:
    """The verify task is tracked in _push_tasks and cancelled by async_shutdown,
    not left orphaned (same lifecycle as _push_side_effects tasks)."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    with patch("custom_components.karcher_home_robots.coordinator._COMMAND_VERIFY_TIMEOUT", 30.0):
        await coordinator.async_send_command("stop_recharge", {})
        assert len(coordinator._push_tasks) == 1
        task = next(iter(coordinator._push_tasks))
        assert not task.done()

        await coordinator.async_shutdown()

        assert task.cancelled() or task.done()
        assert not coordinator._push_tasks


async def test_find_device_skips_verification(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """find_device (locate) never changes work_mode, so it's exempt from
    verification entirely — no task spawned, no false-positive WARNING."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    with (
        patch("custom_components.karcher_home_robots.coordinator._COMMAND_VERIFY_TIMEOUT", 0.05),
        caplog.at_level(logging.WARNING, logger=_LOGGER_NAME),
    ):
        await coordinator.async_send_command("find_device", {})
        await hass.async_block_till_done()

    assert not coordinator._push_tasks
    assert "No work_mode change observed" not in caplog.text


# ---------------------------------------------------------------------------
# Concurrency: two commands in flight, and overlapping preference fetches
# ---------------------------------------------------------------------------


async def test_two_commands_in_flight_verify_independently(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Two overlapping commands each get their own verification, and a push settles both.

    The verify tasks are detached and both read self.data through the coordinator's
    listener mechanism, so they share state without coordinating. A push landing
    between the two dispatches must satisfy whichever of them is still waiting
    rather than confirming one and stranding the other.
    """
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator: KarcherCoordinator = entry.runtime_data

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        await coordinator.async_send_command("set_room_clean", {"room_ids": [10]})
        await coordinator.async_send_command("set_mode", {"mode": 1})
        # One push moves work_mode for both waiters.
        coordinator._handle_push(PROPS_CLEANING)
        await hass.async_block_till_done()

    assert [service for service, _ in fake.commands_sent] == ["set_room_clean", "set_mode"]
    # Both verifications observed the change; neither timed out into a false warning.
    assert "No work_mode change observed" not in caplog.text
    # Both tasks completed and dropped their handles.
    assert not [task for task in coordinator._push_tasks if not task.done()]


async def test_overlapping_forced_preference_fetches_are_serialised(
    hass: HomeAssistant,
) -> None:
    """Two forced preference fetches never overlap on the adapter.

    force=True bypasses the throttle, so setup and a map change can both ask at
    once. The adapter dispatches replies through a dict keyed by MQTT topic, so two
    round-trips in flight for the same device would collide on that key and orphan
    one waiter. _pref_fetch_lock is what prevents it; this test fails without it.
    """
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator: KarcherCoordinator = entry.runtime_data
    coordinator._current_map_id = "506"

    concurrent = 0
    peak = 0
    released = asyncio.Event()

    async def _slow_get_preference(device: object, map_id: int) -> dict[str, object]:
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        try:
            await released.wait()
            return {"rooms": [], "prefer_on": 0}
        finally:
            concurrent -= 1

    fake.get_preference = _slow_get_preference  # type: ignore[method-assign]

    first = asyncio.create_task(coordinator._fetch_preference(force=True))
    second = asyncio.create_task(coordinator._fetch_preference(force=True))
    await asyncio.sleep(0)  # let both reach the adapter call, if they can
    released.set()
    await asyncio.gather(first, second)

    assert peak == 1, f"{peak} preference fetches were in flight at once"
