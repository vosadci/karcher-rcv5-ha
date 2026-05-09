# SPDX-License-Identifier: MIT
"""Integration tests for vacuum command dispatching and push updates."""

from __future__ import annotations

from custom_components.karcher_home_robots.const import DOMAIN
from custom_components.karcher_home_robots.vacuum import KarcherVacuum
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import (
    ENTRY_DATA,
    PROPS_CLEANING,
    PROPS_DOCKED,
    PROPS_IDLE,
    PROPS_PAUSED,
    TEST_DEVICE,
    TEST_ROOMS,
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


# ---------------------------------------------------------------------------
# Command dispatch tests
# ---------------------------------------------------------------------------


async def test_start_sends_set_room_clean(hass: HomeAssistant) -> None:
    """async_start dispatches set_room_clean with all room ids."""
    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum", "start", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert len(fake.commands_sent) == 1
    service, params = fake.commands_sent[0]
    assert service == "set_room_clean"
    assert params["ctrl_value"] == 1
    assert params["room_ids"] == [1, 2]  # TEST_ROOMS ids


async def test_start_paused_resumes_with_empty_rooms(hass: HomeAssistant) -> None:
    """async_start from paused state sends empty room_ids (resume)."""
    fake = FakeAdapter(props=PROPS_PAUSED)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum", "start", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert len(fake.commands_sent) == 1
    _, params = fake.commands_sent[0]
    assert params["room_ids"] == []


async def test_pause_sends_set_room_clean_ctrl_2(hass: HomeAssistant) -> None:
    """async_pause dispatches set_room_clean with ctrl_value=2."""
    fake = FakeAdapter(props=PROPS_CLEANING)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum", "pause", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert len(fake.commands_sent) == 1
    service, params = fake.commands_sent[0]
    assert service == "set_room_clean"
    assert params["ctrl_value"] == 2


async def test_stop_sends_stop_recharge(hass: HomeAssistant) -> None:
    """async_stop dispatches stop_recharge."""
    fake = FakeAdapter(props=PROPS_CLEANING)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum", "stop", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert len(fake.commands_sent) == 1
    service, _ = fake.commands_sent[0]
    assert service == "stop_recharge"


async def test_return_to_base_sends_start_recharge(hass: HomeAssistant) -> None:
    """async_return_to_base dispatches start_recharge."""
    fake = FakeAdapter(props=PROPS_CLEANING)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum", "return_to_base", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert len(fake.commands_sent) == 1
    service, _ = fake.commands_sent[0]
    assert service == "start_recharge"


async def test_locate_sends_find_device(hass: HomeAssistant) -> None:
    """async_locate dispatches find_device with empty params (APK: SettingsVM.java:911)."""
    fake = FakeAdapter(props=PROPS_DOCKED)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum", "locate", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert len(fake.commands_sent) == 1
    service, params = fake.commands_sent[0]
    assert service == "find_device"
    assert params == {}


async def test_set_fan_speed_sends_prop_set(hass: HomeAssistant) -> None:
    """async_set_fan_speed sends prop.set with wind value."""
    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum",
        "set_fan_speed",
        {"entity_id": "vacuum.test_robot_vacuum", "fan_speed": "turbo"},
        blocking=True,
    )

    assert len(fake.properties_set) == 1
    assert fake.properties_set[0] == {"wind": 3}


async def test_set_fan_speed_unknown_raises(hass: HomeAssistant) -> None:
    """Unknown fan speed raises ServiceValidationError."""
    import pytest
    from homeassistant.exceptions import ServiceValidationError

    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup(hass, fake)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "vacuum",
            "set_fan_speed",
            {"entity_id": "vacuum.test_robot_vacuum", "fan_speed": "Ludicrous"},
            blocking=True,
        )

    assert fake.properties_set == []


async def test_send_command_passthrough(hass: HomeAssistant) -> None:
    """async_send_command passes raw command through to adapter."""
    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum",
        "send_command",
        {
            "entity_id": "vacuum.test_robot_vacuum",
            "command": "my_custom_cmd",
            "params": {"key": "value"},
        },
        blocking=True,
    )

    assert len(fake.commands_sent) == 1
    service, params = fake.commands_sent[0]
    assert service == "my_custom_cmd"
    assert params == {"key": "value"}


async def test_fan_speed_attribute_reflects_wind(hass: HomeAssistant) -> None:
    """fan_speed attribute is derived from data.wind."""
    props = make_props(work_mode=1, status=0, charge_state=0, fault=0, battery=80, wind=2)
    fake = FakeAdapter(props=props)
    await _setup(hass, fake)

    state = hass.states.get("vacuum.test_robot_vacuum")
    assert state is not None
    assert state.attributes.get("fan_speed") == "medium"


async def test_app_segment_clean_passthrough(hass: HomeAssistant) -> None:
    """app_segment_clean from HAMH is translated to set_room_clean (FR-V-12)."""
    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum",
        "send_command",
        {
            "entity_id": "vacuum.test_robot_vacuum",
            "command": "app_segment_clean",
            "params": [1, 3],
        },
        blocking=True,
    )

    assert len(fake.commands_sent) == 1
    service, params = fake.commands_sent[0]
    assert service == "set_room_clean"
    assert params["ctrl_value"] == 1
    assert params["room_ids"] == [1, 3]


async def test_send_command_with_non_matching_list_uses_empty_params(hass: HomeAssistant) -> None:
    """async_send_command with a list that does not match the single-dict shim uses empty params.

    vacuum.py line 188->190 (fallback branch)
    """
    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum",
        "send_command",
        {
            "entity_id": "vacuum.test_robot_vacuum",
            "command": "raw_cmd",
            "params": [],  # empty list → neither dict nor single-element list → p = {}
        },
        blocking=True,
    )

    assert len(fake.commands_sent) == 1
    service, params = fake.commands_sent[0]
    assert service == "raw_cmd"
    assert params == {}


async def test_fan_speed_list_matches_matter_rvc_modes(hass: HomeAssistant) -> None:
    """Fan speed options cover the four Matter RvcCleanMode labels (FR-AH-3)."""
    props = make_props(work_mode=0, status=0, charge_state=0, fault=0, battery=80, mode=0)
    fake = FakeAdapter(props=props)
    await _setup(hass, fake)

    state = hass.states.get("vacuum.test_robot_vacuum")
    assert state is not None
    fan_speeds = state.attributes.get("fan_speed_list", [])
    # FR-AH-3: Silent→Quiet, Standard/Medium→Auto, Turbo→Max.
    # The four option strings must exist so downstream bridges can map them.
    assert "silent" in fan_speeds
    assert "standard" in fan_speeds
    assert "medium" in fan_speeds
    assert "turbo" in fan_speeds


async def test_fan_speed_list_empty_in_mop_mode(hass: HomeAssistant) -> None:
    """fan_speed_list is empty in Mop-only mode (no suction, so no speed options)."""
    props = make_props(work_mode=0, status=0, charge_state=0, fault=0, battery=80, mode=2, wind=2)
    fake = FakeAdapter(props=props)
    await _setup(hass, fake)

    state = hass.states.get("vacuum.test_robot_vacuum")
    assert state is not None
    assert state.attributes.get("fan_speed_list") == []


async def test_set_fan_speed_raises_in_mop_mode(hass: HomeAssistant) -> None:
    """async_set_fan_speed raises ServiceValidationError when mode is Mop-only."""
    import pytest
    from homeassistant.exceptions import ServiceValidationError

    props = make_props(work_mode=0, status=0, charge_state=0, fault=0, battery=80, mode=2, wind=2)
    fake = FakeAdapter(props=props)
    await _setup(hass, fake)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "vacuum",
            "set_fan_speed",
            {"entity_id": "vacuum.test_robot_vacuum", "fan_speed": "turbo"},
            blocking=True,
        )
    assert fake.properties_set == []


# ---------------------------------------------------------------------------
# Push update tests (coordinator FR-UP-1..FR-UP-5)
# ---------------------------------------------------------------------------


async def test_send_command_unwraps_single_element_list_params(hass: HomeAssistant) -> None:
    """async_send_command unwraps a single-element list containing a dict (Roborock shim).

    Covers: vacuum.py line 213
    """
    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum",
        "send_command",
        {
            "entity_id": "vacuum.test_robot_vacuum",
            "command": "raw_cmd",
            "params": [{"key": "val"}],
        },
        blocking=True,
    )

    assert len(fake.commands_sent) == 1
    service, params = fake.commands_sent[0]
    assert service == "raw_cmd"
    assert params == {"key": "val"}


async def test_app_segment_clean_none_params_uses_all_rooms(hass: HomeAssistant) -> None:
    """_handle_app_segment_clean with None params falls back to all coordinator rooms.

    Covers: vacuum.py line 222
    """
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherVacuum(coordinator)

    await entity._handle_app_segment_clean(None)

    assert len(fake.commands_sent) == 1
    service, params = fake.commands_sent[0]
    assert service == "set_room_clean"
    assert set(params["room_ids"]) == {r.room_id for r in TEST_ROOMS}


async def test_app_segment_clean_non_digit_params_falls_back_to_all_rooms(
    hass: HomeAssistant,
) -> None:
    """_handle_app_segment_clean with all-non-digit params falls back to all rooms.

    Covers: vacuum.py line 224
    """
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherVacuum(coordinator)

    await entity._handle_app_segment_clean(["x", "y", "z"])

    assert len(fake.commands_sent) == 1
    service, params = fake.commands_sent[0]
    assert service == "set_room_clean"
    assert set(params["room_ids"]) == {r.room_id for r in TEST_ROOMS}


async def test_push_update_changes_vacuum_state(hass: HomeAssistant) -> None:
    """A push from the adapter updates the vacuum entity state."""
    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup(hass, fake)

    state_before = hass.states.get("vacuum.test_robot_vacuum")
    assert state_before is not None
    assert state_before.state == "idle"

    fake.fire_push(PROPS_CLEANING)
    await hass.async_block_till_done()

    state_after = hass.states.get("vacuum.test_robot_vacuum")
    assert state_after is not None
    assert state_after.state == "cleaning"
