# SPDX-License-Identifier: MIT
"""Integration tests for the QoS 0 command-verification wait in async_send_command."""

from __future__ import annotations

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
