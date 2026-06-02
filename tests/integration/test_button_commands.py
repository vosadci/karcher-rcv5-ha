# SPDX-License-Identifier: MIT
"""Integration tests for consumable reset button dispatch."""

from __future__ import annotations

import pytest
from custom_components.karcher_home_robots.const import DOMAIN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import (
    ENTRY_DATA,
    PROPS_DOCKED,
    TEST_DEVICE,
    FakeAdapter,
    patch_adapter,
)


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


@pytest.mark.parametrize(
    "entity_id,expected_type",
    [
        ("button.test_robot_reset_main_brush", 1),
        ("button.test_robot_reset_side_brush", 2),
        ("button.test_robot_reset_filter", 3),
        ("button.test_robot_reset_mopping_pad", 4),
    ],
)
async def test_reset_button_sends_reset_consumable(
    hass: HomeAssistant, entity_id: str, expected_type: int
) -> None:
    fake = FakeAdapter(props=PROPS_DOCKED)
    await _setup(hass, fake)

    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)

    assert fake.commands_sent == [("reset_consumable", {"consumable": expected_type})]
