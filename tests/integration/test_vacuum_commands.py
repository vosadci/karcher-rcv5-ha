# SPDX-License-Identifier: MIT
"""Integration tests for vacuum command dispatching and push updates.

Covers: FR-V-1..FR-V-8, FR-V-12, FR-UP-1..FR-UP-5
"""

from __future__ import annotations

from custom_components.karcher_home_robots.const import DOMAIN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import (
    PROPS_CLEANING,
    PROPS_DOCKED,
    PROPS_IDLE,
    PROPS_PAUSED,
    TEST_DEVICE,
    make_props,
)
from tests.integration.test_init_lifecycle import _ENTRY_DATA, FakeAdapter, _patch_adapter


async def _setup(hass: HomeAssistant, fake: FakeAdapter) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=_ENTRY_DATA,
        unique_id=TEST_DEVICE.device_id,
        version=3,
    )
    entry.add_to_hass(hass)
    with _patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


# ---------------------------------------------------------------------------
# Command dispatch tests
# ---------------------------------------------------------------------------


async def test_start_sends_set_room_clean(hass: HomeAssistant) -> None:
    """async_start dispatches set_room_clean with all room ids.

    Covers: FR-V-1, FR-V-3
    """
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
    """async_start from paused state sends empty room_ids (resume).

    Covers: FR-V-2
    """
    fake = FakeAdapter(props=PROPS_PAUSED)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum", "start", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert len(fake.commands_sent) == 1
    _, params = fake.commands_sent[0]
    assert params["room_ids"] == []


async def test_pause_sends_set_room_clean_ctrl_2(hass: HomeAssistant) -> None:
    """async_pause dispatches set_room_clean with ctrl_value=2.

    Covers: FR-V-4
    """
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
    """async_stop dispatches stop_recharge.

    Covers: FR-V-5
    """
    fake = FakeAdapter(props=PROPS_CLEANING)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum", "stop", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert len(fake.commands_sent) == 1
    service, _ = fake.commands_sent[0]
    assert service == "stop_recharge"


async def test_return_to_base_sends_start_recharge(hass: HomeAssistant) -> None:
    """async_return_to_base dispatches start_recharge.

    Covers: FR-V-6
    """
    fake = FakeAdapter(props=PROPS_CLEANING)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum", "return_to_base", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert len(fake.commands_sent) == 1
    service, _ = fake.commands_sent[0]
    assert service == "start_recharge"


async def test_locate_sends_set_find_robot(hass: HomeAssistant) -> None:
    """async_locate dispatches set_find_robot with find_robot=1.

    Covers: FR-V-7
    """
    fake = FakeAdapter(props=PROPS_DOCKED)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum", "locate", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert len(fake.commands_sent) == 1
    service, params = fake.commands_sent[0]
    assert service == "set_find_robot"
    assert params["find_robot"] == 1


async def test_set_fan_speed_sends_prop_set(hass: HomeAssistant) -> None:
    """async_set_fan_speed sends prop.set with wind value.

    Covers: FR-V-8
    """
    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum",
        "set_fan_speed",
        {"entity_id": "vacuum.test_robot_vacuum", "fan_speed": "Turbo"},
        blocking=True,
    )

    assert len(fake.properties_set) == 1
    assert fake.properties_set[0] == {"wind": 3}


async def test_set_fan_speed_unknown_is_ignored(hass: HomeAssistant) -> None:
    """Unknown fan speed is silently dropped (warning logged, no command sent).

    Covers: FR-V-8 (graceful degradation)
    """
    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum",
        "set_fan_speed",
        {"entity_id": "vacuum.test_robot_vacuum", "fan_speed": "Ludicrous"},
        blocking=True,
    )

    assert fake.properties_set == []


async def test_send_command_passthrough(hass: HomeAssistant) -> None:
    """async_send_command passes raw command through to adapter.

    Covers: FR-V-12
    """
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
    """fan_speed attribute is derived from data.wind.

    Covers: FR-V-8
    """
    props = make_props(work_mode=1, status=0, charge_state=0, fault=0, battery=80, wind=2)
    fake = FakeAdapter(props=props)
    await _setup(hass, fake)

    state = hass.states.get("vacuum.test_robot_vacuum")
    assert state is not None
    assert state.attributes.get("fan_speed") == "Medium"


async def test_app_segment_clean_passthrough(hass: HomeAssistant) -> None:
    """app_segment_clean is forwarded to the adapter as-is (P3-4, FR-V-12)."""
    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum",
        "send_command",
        {
            "entity_id": "vacuum.test_robot_vacuum",
            "command": "app_segment_clean",
            "params": [{"room_ids": [1, 3]}],
        },
        blocking=True,
    )

    assert len(fake.commands_sent) == 1
    service, params = fake.commands_sent[0]
    assert service == "app_segment_clean"
    assert params == {"room_ids": [1, 3]}


async def test_send_command_with_non_matching_list_uses_empty_params(hass: HomeAssistant) -> None:
    """async_send_command with a list that does not match the single-dict shim uses empty params.

    Covers: FR-V-12 (fallback branch — vacuum.py line 188->190)
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
    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup(hass, fake)

    state = hass.states.get("vacuum.test_robot_vacuum")
    assert state is not None
    fan_speeds = state.attributes.get("fan_speed_list", [])
    # FR-AH-3: Silent→Quiet, Standard/Medium→Auto, Turbo→Max.
    # The four option strings must exist so downstream bridges can map them.
    assert "Silent" in fan_speeds
    assert "Standard" in fan_speeds
    assert "Medium" in fan_speeds
    assert "Turbo" in fan_speeds


# ---------------------------------------------------------------------------
# Push update tests (coordinator FR-UP-1..FR-UP-5)
# ---------------------------------------------------------------------------


async def test_push_update_changes_vacuum_state(hass: HomeAssistant) -> None:
    """A push from the adapter updates the vacuum entity state.

    Covers: FR-UP-1 (push delivery), FR-UP-2 (coordinator picks it up)
    """
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


async def test_stale_push_is_discarded(hass: HomeAssistant) -> None:
    """A push with a timestamp older than an already-applied update is dropped.

    Covers: FR-UP-5 (monotonic timestamp ordering)
    """
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data

    # Force a high timestamp via a normal push
    fake.fire_push(PROPS_CLEANING)
    await hass.async_block_till_done()
    assert hass.states.get("vacuum.test_robot_vacuum").state == "cleaning"  # type: ignore[union-attr]

    # Simulate a stale update by directly calling _apply_update with old ts
    past_ts = coordinator._last_update_ts - 1.0
    await coordinator._apply_update(PROPS_DOCKED, past_ts)
    await hass.async_block_till_done()

    # Should still be cleaning — stale update was discarded
    assert hass.states.get("vacuum.test_robot_vacuum").state == "cleaning"  # type: ignore[union-attr]
