# SPDX-License-Identifier: MIT
"""Integration tests for the AI recognition and carpet-setting switches.

These are backed by the `privacy` sub-property (`prop.set {"privacy": {<field>: 0|1}}`,
doc/APP_FEATURES.md "Carpet Settings"), APK-verified against CarpetSettingVM.java /
PrivacySecurityVM.java (2026-09-22).
"""

from __future__ import annotations

from custom_components.karcher_home_robots.const import DOMAIN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import (
    ENTRY_DATA,
    PROPS_IDLE,
    TEST_DEVICE,
    FakeAdapter,
    make_props,
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


async def test_switches_reflect_device_state(hass: HomeAssistant) -> None:
    """Each switch's state mirrors its privacy field when the value is known."""
    props = make_props(
        work_mode=0,
        status=0,
        charge_state=0,
        fault=0,
        battery=80,
        ai_recognize=1,
        carpet_turbo=0,
        carpet_avoid=1,
        carpet_show=0,
    )
    fake = FakeAdapter(props=props)
    await _setup(hass, fake)

    assert hass.states.get("switch.test_robot_ai_recognition").state == "on"
    assert hass.states.get("switch.test_robot_carpet_boost_mode").state == "off"
    assert hass.states.get("switch.test_robot_carpet_avoidance_mode").state == "on"
    assert hass.states.get("switch.test_robot_carpet_display").state == "off"


async def test_switches_unknown_when_field_absent(hass: HomeAssistant) -> None:
    """PROPS_IDLE carries no privacy data — switches report unknown, not off."""
    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup(hass, fake)

    assert hass.states.get("switch.test_robot_ai_recognition").state == "unknown"
    assert hass.states.get("switch.test_robot_carpet_boost_mode").state == "unknown"
    assert hass.states.get("switch.test_robot_carpet_avoidance_mode").state == "unknown"
    assert hass.states.get("switch.test_robot_carpet_display").state == "unknown"


async def test_ai_recognition_exposes_detected_types(hass: HomeAssistant) -> None:
    """The AI recognition switch lists the object types the app documents as detectable."""
    props = make_props(work_mode=0, status=0, charge_state=0, fault=0, battery=80, ai_recognize=1)
    fake = FakeAdapter(props=props)
    await _setup(hass, fake)

    state = hass.states.get("switch.test_robot_ai_recognition")
    assert state.attributes["detected_types"] == (
        "Shoes",
        "Socks",
        "Wires",
        "Bar chairs",
        "Weight scales",
    )


async def test_turn_on_off_send_privacy_prop_set(hass: HomeAssistant) -> None:
    """Toggling each switch sends the matching {"privacy": {<field>: 0|1}} payload."""
    props = make_props(
        work_mode=0,
        status=0,
        charge_state=0,
        fault=0,
        battery=80,
        ai_recognize=0,
        carpet_turbo=1,
        carpet_avoid=0,
        carpet_show=1,
    )
    fake = FakeAdapter(props=props)
    await _setup(hass, fake)

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.test_robot_ai_recognition"},
        blocking=True,
    )
    assert fake.properties_set[-1] == {"privacy": {"ai_recognize": 1}}

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.test_robot_carpet_boost_mode"},
        blocking=True,
    )
    assert fake.properties_set[-1] == {"privacy": {"carpet_turbo": 0}}

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.test_robot_carpet_avoidance_mode"},
        blocking=True,
    )
    assert fake.properties_set[-1] == {"privacy": {"carpet_avoid": 1}}

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.test_robot_carpet_display"},
        blocking=True,
    )
    assert fake.properties_set[-1] == {"privacy": {"carpet_show": 0}}
