# SPDX-License-Identifier: MIT
"""Per-model suction scale, end to end through the public surface.

Two robots are run through the same assertions: the RCV 5 (suction 0-3 on the
wire) and the RVF 7 Comfort (1-4). Everything a user can see or call — the fan
speed attribute, `set_fan_speed`, the per-room select, what is written to the
robot — must read the same label on both; only the number on the wire differs.
The RCV 5 rows are the guarantee that adding a model did not move the
maintainer's own robot.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from custom_components.karcher_home_robots.const import DOMAIN
from custom_components.karcher_home_robots.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.karcher_home_robots.select import (
    KarcherRoomPowerSelect,
    KarcherRoomWaterSelect,
    KarcherWaterLevelSelect,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import (
    ENTRY_DATA,
    TEST_DEVICE,
    TEST_ROOMS,
    FakeAdapter,
    make_props,
    patch_adapter,
)

RCV5 = TEST_DEVICE.product_id
RVF7_COMFORT = "1950097614355394560"
VACUUM = "vacuum.test_robot_vacuum"

# (product id, label, number on the wire)
LEVELS = [
    (RCV5, "silent", 0),
    (RCV5, "standard", 1),
    (RCV5, "medium", 2),
    (RCV5, "turbo", 3),
    (RVF7_COMFORT, "silent", 1),
    (RVF7_COMFORT, "standard", 2),
    (RVF7_COMFORT, "medium", 3),
    (RVF7_COMFORT, "turbo", 4),
]


def _props(wind: int | None):
    return make_props(
        work_mode=0, status=0, charge_state=0, fault=0, battery=80, mode=0, wind=wind,
        current_map_id="7",
    )  # fmt: skip


async def _setup(hass: HomeAssistant, fake: FakeAdapter) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, unique_id=TEST_DEVICE.device_id, version=3
    )
    entry.add_to_hass(hass)
    with patch_adapter(fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _fake(product_id: str, wind: int | None, **kwargs) -> FakeAdapter:
    return FakeAdapter(
        props=_props(wind), devices=[replace(TEST_DEVICE, product_id=product_id)], **kwargs
    )


@pytest.mark.parametrize(("product_id", "label", "raw"), LEVELS)
async def test_the_robots_number_reads_as_the_same_label_on_every_model(
    hass: HomeAssistant, product_id: str, label: str, raw: int
) -> None:
    await _setup(hass, _fake(product_id, raw))

    state = hass.states.get(VACUUM)
    assert state is not None
    assert state.attributes.get("fan_speed") == label


@pytest.mark.parametrize(("product_id", "label", "raw"), LEVELS)
async def test_set_fan_speed_sends_the_models_own_number(
    hass: HomeAssistant, product_id: str, label: str, raw: int
) -> None:
    fake = _fake(product_id, 1)
    await _setup(hass, fake)

    await hass.services.async_call(
        "vacuum", "set_fan_speed", {"entity_id": VACUUM, "fan_speed": label}, blocking=True
    )

    assert fake.properties_set == [{"wind": raw}]


async def test_rvf7_level_the_scale_does_not_describe_is_visible_and_recorded(
    hass: HomeAssistant,
) -> None:
    """RVF 7 raw 0 is "off" in the vendor app. It must neither read as silent
    (the RCV 5's 0) nor vanish."""
    entry = await _setup(hass, _fake(RVF7_COMFORT, 0))

    state = hass.states.get(VACUUM)
    assert state is not None
    assert state.attributes.get("fan_speed") == "level_0"
    assert entry.runtime_data.novel_values == {"wind": [0]}


async def test_rvf7_turbo_is_not_a_novel_value(hass: HomeAssistant) -> None:
    """The report that started this: wind 4 on an RVF 7 Comfort."""
    entry = await _setup(hass, _fake(RVF7_COMFORT, 4))

    assert entry.runtime_data.novel_values == {}


@pytest.mark.parametrize(
    ("product_id", "raw", "label"),
    [(RCV5, 3, "turbo"), (RVF7_COMFORT, 4, "turbo"), (RVF7_COMFORT, 1, "silent")],
)
async def test_a_pushed_level_is_translated_like_a_polled_one(
    hass: HomeAssistant, product_id: str, raw: int, label: str
) -> None:
    """MQTT push is the live path on a real robot; the poll path alone proves little."""
    entry = await _setup(hass, _fake(product_id, 1))

    entry.runtime_data._handle_push(_props(raw))
    await hass.async_block_till_done()

    state = hass.states.get(VACUUM)
    assert state is not None
    assert state.attributes.get("fan_speed") == label


async def test_a_pushed_unmapped_level_is_recorded_not_mistaken(hass: HomeAssistant) -> None:
    entry = await _setup(hass, _fake(RVF7_COMFORT, 1))

    entry.runtime_data._handle_push(_props(0))
    await hass.async_block_till_done()

    state = hass.states.get(VACUUM)
    assert state is not None
    assert state.attributes.get("fan_speed") == "level_0"
    assert entry.runtime_data.novel_values == {"wind": [0]}


@pytest.mark.parametrize(
    ("product_id", "row_wind", "novel"),
    [
        (RVF7_COMFORT, 0, {"wind": [0]}),
        (RVF7_COMFORT, 4, {}),
        (RCV5, 0, {}),
        (RCV5, 4, {"wind": [4]}),
    ],
)
async def test_a_preference_rows_unmapped_level_is_recorded(
    hass: HomeAssistant, product_id: str, row_wind: int, novel: dict[str, list[int]]
) -> None:
    raw_room = [1, "Kitchen", 0, 0, row_wind, 1, 0, 0, 0, 0, 0, 0]
    fake = _fake(product_id, 1, preference_result={"rooms": [raw_room], "prefer_on": 0})
    entry = await _setup(hass, fake)

    assert entry.runtime_data.novel_values == novel


@pytest.mark.parametrize(
    ("product_id", "row_wind", "power"),
    [
        (RCV5, 2, 2),
        (RCV5, 4, 4),  # outside the table, but what the attribute always showed
        (RVF7_COMFORT, 3, 2),
        (RVF7_COMFORT, 0, None),  # raw 0 must not read as "silent"
    ],
)
async def test_the_room_preferences_attribute_stays_on_the_card_scale(
    hass: HomeAssistant, product_id: str, row_wind: int, power: int | None
) -> None:
    """The card reads these ints directly, so they are the RCV 5 numbering for
    every model, and a level it cannot name is never one it could misread."""
    raw_room = [1, "Kitchen", 0, 0, row_wind, 1, 0, 0, 0, 0, 0, 0]
    fake = _fake(product_id, 1, preference_result={"rooms": [raw_room], "prefer_on": 0})
    await _setup(hass, fake)

    state = hass.states.get(VACUUM)
    assert state is not None
    assert state.attributes["room_preferences"]["1"]["power"] == power


async def test_rcv5_wind_four_is_still_novel(hass: HomeAssistant) -> None:
    entry = await _setup(hass, _fake(RCV5, 4))

    state = hass.states.get(VACUUM)
    assert state is not None
    assert state.attributes.get("fan_speed") == "level_4"
    assert entry.runtime_data.novel_values == {"wind": [4]}


@pytest.mark.parametrize(
    ("product_id", "standard_raw", "turbo_raw"), [(RCV5, 1, 3), (RVF7_COMFORT, 2, 4)]
)
async def test_room_preferences_are_translated_both_ways(
    hass: HomeAssistant, product_id: str, standard_raw: int, turbo_raw: int
) -> None:
    """Read: the robot's row shows as "standard". Write: choosing turbo sends the
    model's number for it, and the room nobody touched is written back as
    "standard" — not as whatever the RCV 5's neutral number happens to mean."""
    raw_room = [1, "Kitchen", 0, 0, standard_raw, 2, 0, 0, 0, 0, 0, 0]
    fake = _fake(product_id, 1, preference_result={"rooms": [raw_room], "prefer_on": 0})
    entry = await _setup(hass, fake)
    coordinator = entry.runtime_data
    assert len(TEST_ROOMS) == 2

    entity = KarcherRoomPowerSelect(coordinator, room_id=1, room_name="Kitchen")
    assert entity.current_option == "standard"

    await entity.async_select_option("turbo")

    _map_id, rows = fake.preferences_set[-1]
    by_room = {row[0]: row for row in rows}
    assert by_room[1][4] == turbo_raw
    assert by_room[2][4] == standard_raw


WATER_LEVELS = [
    (RCV5, "low", 0),
    (RCV5, "medium", 1),
    (RCV5, "high", 2),
    # No robot has reported an RVF 7 water value, so it follows the default scale. If
    # a water_levels row is ever added these three rows must change with it.
    (RVF7_COMFORT, "low", 0),
    (RVF7_COMFORT, "medium", 1),
    (RVF7_COMFORT, "high", 2),
]


def _water_props(water: int):
    return make_props(
        work_mode=0, status=0, charge_state=0, fault=0, battery=80, mode=1, water=water,
        current_map_id="7",
    )  # fmt: skip


@pytest.mark.parametrize(("product_id", "label", "raw"), WATER_LEVELS)
async def test_water_level_reads_and_writes_the_models_number(
    hass: HomeAssistant, product_id: str, label: str, raw: int
) -> None:
    fake = FakeAdapter(
        props=_water_props(raw), devices=[replace(TEST_DEVICE, product_id=product_id)]
    )
    entry = await _setup(hass, fake)
    entity = KarcherWaterLevelSelect(entry.runtime_data)

    assert entity.current_option == label

    await entity.async_select_option(label)

    assert fake.properties_set == [{"water": raw}]


@pytest.mark.parametrize(
    ("product_id", "medium_raw", "high_raw"), [(RCV5, 1, 2), (RVF7_COMFORT, 1, 2)]
)
async def test_room_water_is_translated_both_ways(
    hass: HomeAssistant, product_id: str, medium_raw: int, high_raw: int
) -> None:
    raw_room = [1, "Kitchen", 0, 0, 1, medium_raw, 0, 0, 0, 0, 0, 0]
    fake = _fake(product_id, 1, preference_result={"rooms": [raw_room], "prefer_on": 0})
    entry = await _setup(hass, fake)

    entity = KarcherRoomWaterSelect(entry.runtime_data, room_id=1, room_name="Kitchen")
    assert entity.current_option == "medium"

    await entity.async_select_option("high")

    _map_id, rows = fake.preferences_set[-1]
    by_room = {row[0]: row for row in rows}
    assert by_room[1][5] == high_raw
    assert by_room[2][5] == medium_raw


async def test_diagnostics_report_the_robots_own_number(hass: HomeAssistant) -> None:
    """Triage compares against the vendor app, so it needs the wire value."""
    entry = await _setup(hass, _fake(RVF7_COMFORT, 4))

    bundle = await async_get_config_entry_diagnostics(hass, entry)

    assert bundle["device_properties"]["wind"] == 4
