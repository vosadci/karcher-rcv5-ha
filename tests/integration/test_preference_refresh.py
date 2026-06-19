# SPDX-License-Identifier: MIT
"""Responsive preference refetch — custom_type push trigger, set_preference_type, throttle."""

from __future__ import annotations

from typing import Any

from custom_components.karcher_home_robots.const import DOMAIN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import ENTRY_DATA, TEST_DEVICE, FakeAdapter, make_props, patch_adapter


def _props(custom_type: int | None = None, **kw: Any) -> Any:
    return make_props(
        work_mode=0,
        status=0,
        charge_state=0,
        fault=0,
        battery=80,
        current_map_id="1",
        custom_type=custom_type,
        **kw,
    )


async def _setup(hass: HomeAssistant, fake: FakeAdapter) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, unique_id=TEST_DEVICE.device_id, version=3
    )
    entry.add_to_hass(hass)
    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _unthrottle(coordinator: Any) -> None:
    """Move the last-fetch stamp past the short min-interval so a trigger refetches."""
    coordinator._last_pref_fetch_ts = coordinator.hass.loop.time() - 10


async def test_custom_type_change_triggers_refetch(hass: HomeAssistant) -> None:
    fake = FakeAdapter(props=_props(custom_type=0))
    coordinator = (await _setup(hass, fake)).runtime_data

    fake.fire_push(_props(custom_type=0))  # baseline (first-seen, no refetch)
    await hass.async_block_till_done()

    _unthrottle(coordinator)
    before = fake.get_preference_calls
    fake.fire_push(_props(custom_type=1))  # Standard → Customise
    await hass.async_block_till_done()
    assert fake.get_preference_calls == before + 1


async def test_custom_type_first_seen_does_not_refetch(hass: HomeAssistant) -> None:
    fake = FakeAdapter(props=_props(custom_type=1))
    coordinator = (await _setup(hass, fake)).runtime_data

    _unthrottle(coordinator)
    before = fake.get_preference_calls
    fake.fire_push(_props(custom_type=1))  # first push: record baseline, no refetch
    await hass.async_block_till_done()
    assert fake.get_preference_calls == before


async def test_custom_type_unchanged_does_not_refetch(hass: HomeAssistant) -> None:
    fake = FakeAdapter(props=_props(custom_type=2))
    coordinator = (await _setup(hass, fake)).runtime_data

    fake.fire_push(_props(custom_type=2))  # baseline
    await hass.async_block_till_done()

    _unthrottle(coordinator)
    before = fake.get_preference_calls
    fake.fire_push(_props(custom_type=2))  # unchanged
    await hass.async_block_till_done()
    assert fake.get_preference_calls == before


async def test_refetch_throttled_within_min_interval(hass: HomeAssistant) -> None:
    fake = FakeAdapter(props=_props(custom_type=0))
    await _setup(hass, fake)

    fake.fire_push(_props(custom_type=0))  # baseline
    await hass.async_block_till_done()

    # Do NOT unthrottle: setup fetched < min-interval ago, so the change is dropped.
    before = fake.get_preference_calls
    fake.fire_push(_props(custom_type=1))
    await hass.async_block_till_done()
    assert fake.get_preference_calls == before


async def test_set_preference_type_customise_refetches(hass: HomeAssistant) -> None:
    fake = FakeAdapter(props=_props(custom_type=0))
    coordinator = (await _setup(hass, fake)).runtime_data

    _unthrottle(coordinator)
    before = fake.get_preference_calls
    await coordinator.async_set_preference_type(1)
    assert fake.get_preference_calls == before + 1


async def test_set_preference_type_standard_does_not_refetch(hass: HomeAssistant) -> None:
    fake = FakeAdapter(props=_props(custom_type=1))
    coordinator = (await _setup(hass, fake)).runtime_data

    _unthrottle(coordinator)
    before = fake.get_preference_calls
    await coordinator.async_set_preference_type(0)
    assert fake.get_preference_calls == before


async def test_refresh_preferences_service_refetches(hass: HomeAssistant) -> None:
    fake = FakeAdapter(props=_props(custom_type=0))
    coordinator = (await _setup(hass, fake)).runtime_data

    _unthrottle(coordinator)
    before = fake.get_preference_calls
    await hass.services.async_call(DOMAIN, "refresh_preferences", {}, blocking=True)
    assert fake.get_preference_calls == before + 1
