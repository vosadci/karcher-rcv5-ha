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
    PROPS_RETURNING,
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


async def test_start_paused_sets_resume_intent(hass: HomeAssistant) -> None:
    """vacuum.start while paused is a Resume: it sets the coordinator's resume
    intent so the upcoming cleaning transition keeps the in-progress path."""
    fake = FakeAdapter(props=PROPS_PAUSED)
    entry = await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum", "start", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert entry.runtime_data._resume_intent is True


async def test_start_from_idle_clears_resume_intent(hass: HomeAssistant) -> None:
    """vacuum.start from a non-paused state is a fresh clean: resume intent stays
    False so the cleaning transition clears any stale path."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    entry.runtime_data._resume_intent = True  # stale value from an earlier resume

    await hass.services.async_call(
        "vacuum", "start", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert entry.runtime_data._resume_intent is False


async def test_clean_segments_clears_resume_intent(hass: HomeAssistant) -> None:
    """A room-segment dispatch (card Stop→new-rooms while paused) is always a fresh
    clean: it forces resume intent False so the old path is cleared."""
    fake = FakeAdapter(props=PROPS_PAUSED, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    entry.runtime_data._resume_intent = True
    entity = KarcherVacuum(entry.runtime_data)

    await entity.async_clean_segments(["1"])

    assert entry.runtime_data._resume_intent is False


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


async def test_stop_while_returning_sends_stop_recharge(hass: HomeAssistant) -> None:
    """async_stop during RETURNING dispatches stop_recharge."""
    fake = FakeAdapter(props=PROPS_RETURNING)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum", "stop", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert len(fake.commands_sent) == 1
    service, _ = fake.commands_sent[0]
    assert service == "stop_recharge"


async def test_stop_while_cleaning_sends_ctrl_value_0(hass: HomeAssistant) -> None:
    """async_stop during CLEANING dispatches the true stop-to-idle (ctrl_value=0)."""
    fake = FakeAdapter(props=PROPS_CLEANING)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum", "stop", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert len(fake.commands_sent) == 1
    service, params = fake.commands_sent[0]
    assert service == "set_room_clean"
    assert params["ctrl_value"] == 0
    assert params["room_ids"] == []


async def test_stop_while_paused_sends_ctrl_value_0(hass: HomeAssistant) -> None:
    """async_stop during PAUSED also issues the stop-to-idle so a paused clean can be
    ended (not just resumed) — ctrl_value=0, not a no-op."""
    fake = FakeAdapter(props=PROPS_PAUSED)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum", "stop", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert len(fake.commands_sent) == 1
    service, params = fake.commands_sent[0]
    assert service == "set_room_clean"
    assert params["ctrl_value"] == 0


async def test_stop_during_zone_clean_sends_zone_ctrl_value_0(hass: HomeAssistant) -> None:
    """async_stop during an area (zone) clean routes through set_zone_clean ctrl_value=0."""
    # work_mode 30 is the zone-clean CLEANING family member (active_clean_is_zone).
    fake = FakeAdapter(props=make_props(work_mode=30, status=0, charge_state=0))
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum", "stop", {"entity_id": "vacuum.test_robot_vacuum"}, blocking=True
    )

    assert len(fake.commands_sent) == 1
    service, params = fake.commands_sent[0]
    assert service == "set_zone_clean"
    assert params["ctrl_value"] == 0


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


async def test_fan_speed_attribute_reflects_wind(hass: HomeAssistant) -> None:
    """fan_speed attribute is derived from data.wind."""
    props = make_props(work_mode=1, status=0, charge_state=0, fault=0, battery=80, wind=2)
    fake = FakeAdapter(props=props)
    await _setup(hass, fake)

    state = hass.states.get("vacuum.test_robot_vacuum")
    assert state is not None
    assert state.attributes.get("fan_speed") == "medium"


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
# CLEAN_AREA — async_get_segments / async_clean_segments
# ---------------------------------------------------------------------------


async def test_async_get_segments_returns_one_per_room(hass: HomeAssistant) -> None:
    """async_get_segments returns one Segment per coordinator room."""
    from homeassistant.components.vacuum import Segment

    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherVacuum(coordinator)

    segments = await entity.async_get_segments()

    assert len(segments) == len(TEST_ROOMS)
    by_id = {s.id: s for s in segments}
    for room in TEST_ROOMS:
        seg = by_id[str(room.room_id)]
        assert isinstance(seg, Segment)
        assert seg.name == room.name


async def test_async_clean_segments_sends_set_room_clean(hass: HomeAssistant) -> None:
    """async_clean_segments dispatches set_room_clean with the given room IDs."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherVacuum(coordinator)

    await entity.async_clean_segments(["1"])

    assert len(fake.commands_sent) == 1
    service, params = fake.commands_sent[0]
    assert service == "set_room_clean"
    assert params["ctrl_value"] == 1
    assert params["room_ids"] == [1]


async def test_async_clean_segments_empty_falls_back_to_all_rooms(
    hass: HomeAssistant,
) -> None:
    """async_clean_segments with no valid IDs falls back to all coordinator rooms."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherVacuum(coordinator)

    await entity.async_clean_segments([])

    assert len(fake.commands_sent) == 1
    _, params = fake.commands_sent[0]
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


# ---------------------------------------------------------------------------
# async_send_command — non-app_segment_clean paths
# ---------------------------------------------------------------------------


async def test_send_command_dict_params_dispatches_to_coordinator(
    hass: HomeAssistant,
) -> None:
    """async_send_command with dict params forwards them to the coordinator."""
    from unittest.mock import AsyncMock

    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherVacuum(coordinator)

    coordinator.async_send_command = AsyncMock()  # type: ignore[method-assign]
    await entity.async_send_command("custom_cmd", {"key": "value"})

    coordinator.async_send_command.assert_awaited_once_with("custom_cmd", {"key": "value"})


async def test_send_command_list_of_dict_params_unwraps(hass: HomeAssistant) -> None:
    """async_send_command with a single-element list of dict unwraps to the inner dict."""
    from unittest.mock import AsyncMock

    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherVacuum(coordinator)

    coordinator.async_send_command = AsyncMock()  # type: ignore[method-assign]
    await entity.async_send_command("custom_cmd", [{"key": "value"}])

    coordinator.async_send_command.assert_awaited_once_with("custom_cmd", {"key": "value"})


async def test_send_command_none_params_sends_empty_dict(hass: HomeAssistant) -> None:
    """async_send_command with no params sends an empty dict to the coordinator."""
    from unittest.mock import AsyncMock

    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherVacuum(coordinator)

    coordinator.async_send_command = AsyncMock()  # type: ignore[method-assign]
    await entity.async_send_command("custom_cmd", None)

    coordinator.async_send_command.assert_awaited_once_with("custom_cmd", {})


# ---------------------------------------------------------------------------
# _handle_app_segment_clean paths
# ---------------------------------------------------------------------------


async def test_app_segment_clean_with_room_ids(hass: HomeAssistant) -> None:
    """app_segment_clean with a list of room IDs sends those IDs."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherVacuum(coordinator)

    await entity.async_send_command("app_segment_clean", [1, 2])

    assert len(fake.commands_sent) == 1
    service, params = fake.commands_sent[0]
    assert service == "set_room_clean"
    assert set(params["room_ids"]) == {1, 2}


async def test_app_segment_clean_no_params_falls_back_to_all_rooms(
    hass: HomeAssistant,
) -> None:
    """app_segment_clean with None params falls back to all coordinator rooms."""
    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherVacuum(coordinator)

    await entity.async_send_command("app_segment_clean", None)

    assert len(fake.commands_sent) == 1
    _, params = fake.commands_sent[0]
    assert set(params["room_ids"]) == {r.room_id for r in TEST_ROOMS}


# ---------------------------------------------------------------------------
# _handle_coordinator_update — segment-change detection
# ---------------------------------------------------------------------------


async def test_handle_coordinator_update_segment_mismatch_raises_issue(
    hass: HomeAssistant,
) -> None:
    """_handle_coordinator_update fires async_create_segments_issue when IDs diverge."""
    from unittest.mock import patch

    from homeassistant.components.vacuum import Segment

    fake = FakeAdapter(props=PROPS_IDLE, rooms=TEST_ROOMS)
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherVacuum(coordinator)

    stale_segments = [Segment(id="99", name="Old Room")]
    with (
        patch.object(
            type(entity),
            "last_seen_segments",
            new_callable=lambda: property(lambda self: stale_segments),
        ),
        patch.object(entity, "async_create_segments_issue") as mock_issue,
        # Prevent super()._handle_coordinator_update() from calling async_write_ha_state
        # on an entity that is not registered with hass.
        patch(
            "homeassistant.helpers.update_coordinator.CoordinatorEntity._handle_coordinator_update"
        ),
    ):
        entity._handle_coordinator_update()
        mock_issue.assert_called_once()
