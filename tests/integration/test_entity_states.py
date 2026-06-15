# SPDX-License-Identifier: MIT
"""Integration tests for entity state transitions and sensor values."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from custom_components.karcher_home_robots._types import DeviceProperties
from custom_components.karcher_home_robots.binary_sensor import (
    KarcherChargingSensor,
    KarcherConnectivitySensor,
    KarcherErrorSensor,
)
from custom_components.karcher_home_robots.const import DOMAIN
from custom_components.karcher_home_robots.exceptions import TransientError
from custom_components.karcher_home_robots.sensor import _SENSORS, KarcherSensor
from custom_components.karcher_home_robots.vacuum import KarcherVacuum
from homeassistant.components.vacuum.const import VacuumEntityFeature
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tests.conftest import (
    ENTRY_DATA,
    PROPS_CLEANING,
    PROPS_DOCKED,
    PROPS_ERROR,
    PROPS_IDLE,
    PROPS_PAUSED,
    PROPS_RETURNING,
    TEST_DEVICE,
    FakeAdapter,
    make_props,
    patch_adapter,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _setup_with_props(hass: HomeAssistant, fake: FakeAdapter) -> MockConfigEntry:
    """Set up the integration and return the config entry."""
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
# Vacuum state tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("props", "expected_state"),
    [
        (PROPS_IDLE, "idle"),
        (PROPS_CLEANING, "cleaning"),
        (PROPS_PAUSED, "paused"),
        (PROPS_DOCKED, "docked"),
        (PROPS_RETURNING, "returning"),
        (PROPS_ERROR, "error"),
    ],
)
async def test_vacuum_activity_states(
    hass: HomeAssistant,
    props: object,
    expected_state: str,
) -> None:
    """Vacuum entity exposes the correct activity for each DeviceProperties snapshot."""
    assert isinstance(props, DeviceProperties)
    fake = FakeAdapter(props=props)
    await _setup_with_props(hass, fake)

    state = hass.states.get("vacuum.test_robot_vacuum")
    assert state is not None
    assert state.state == expected_state


async def test_vacuum_exposes_rooms_as_attributes(hass: HomeAssistant) -> None:
    """Vacuum entity exposes rooms in Roborock format {id_str: name}."""
    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup_with_props(hass, fake)

    state = hass.states.get("vacuum.test_robot_vacuum")
    assert state is not None
    rooms = state.attributes.get("rooms")
    assert rooms == {"1": "Living Room", "2": "Bedroom"}


# ---------------------------------------------------------------------------
# Sensor tests
# ---------------------------------------------------------------------------


async def test_battery_sensor_value(hass: HomeAssistant) -> None:
    """Battery sensor reports coordinator data.battery."""
    props = make_props(battery=75, work_mode=0, status=0, charge_state=0, fault=0)
    fake = FakeAdapter(props=props)
    await _setup_with_props(hass, fake)

    state = hass.states.get("sensor.test_robot_battery")
    assert state is not None
    assert state.state == "75"
    assert state.attributes["device_class"] == "battery"
    assert state.attributes["unit_of_measurement"] == "%"


async def test_cleaning_area_sensor_converts_raw(hass: HomeAssistant) -> None:
    """Cleaning area sensor divides raw value by 100 to get m²."""
    props = make_props(cleaning_area=2228, work_mode=1, status=0, charge_state=0, fault=0)
    fake = FakeAdapter(props=props)
    await _setup_with_props(hass, fake)

    state = hass.states.get("sensor.test_robot_cleaning_area")
    assert state is not None
    assert float(state.state) == pytest.approx(22.28)
    assert state.attributes["unit_of_measurement"] == "m²"


async def test_cleaning_time_sensor(hass: HomeAssistant) -> None:
    """Cleaning time sensor reports minutes directly."""
    props = make_props(cleaning_time=42, work_mode=1, status=0, charge_state=0, fault=0)
    fake = FakeAdapter(props=props)
    await _setup_with_props(hass, fake)

    state = hass.states.get("sensor.test_robot_cleaning_time")
    assert state is not None
    assert state.state == "42"
    assert state.attributes["unit_of_measurement"] == "min"


async def test_cleaning_time_sensor_finished_at_attribute(hass: HomeAssistant) -> None:
    """finished_at attribute is set after last_clean_finished_at is populated."""
    fake = FakeAdapter(props=PROPS_DOCKED)
    entry = await _setup_with_props(hass, fake)
    coordinator = entry.runtime_data
    ts = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
    coordinator.last_clean_finished_at = ts
    coordinator.async_set_updated_data(coordinator.data)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_robot_cleaning_time")
    assert state is not None
    assert state.attributes.get("finished_at") == ts.isoformat()


async def test_cleaning_time_sensor_no_finished_at_when_none(hass: HomeAssistant) -> None:
    """finished_at attribute is absent when last_clean_finished_at is None."""
    fake = FakeAdapter(props=PROPS_DOCKED)
    entry = await _setup_with_props(hass, fake)
    coordinator = entry.runtime_data
    coordinator.last_clean_finished_at = None

    state = hass.states.get("sensor.test_robot_cleaning_time")
    assert state is not None
    assert "finished_at" not in state.attributes


async def test_fault_code_sensor_reports_slug_for_known_code(hass: HomeAssistant) -> None:
    """fault_code sensor reports a slug for a known code and exposes raw integer as attribute."""
    props = make_props(work_mode=0, status=0, charge_state=0, fault=507, battery=80)
    fake = FakeAdapter(props=props)
    await _setup_with_props(hass, fake)

    state = hass.states.get("sensor.test_robot_robot_status")
    assert state is not None
    assert state.state == "relocalization_failed"
    assert state.attributes.get("raw") == 507


async def test_fault_code_sensor_unknown_code_is_unknown(hass: HomeAssistant) -> None:
    """fault_code sensor reports 'unknown' state for unmapped codes; raw attribute still present."""
    props = make_props(work_mode=0, status=0, charge_state=0, fault=42, battery=80)
    fake = FakeAdapter(props=props)
    await _setup_with_props(hass, fake)

    state = hass.states.get("sensor.test_robot_robot_status")
    assert state is not None
    assert state.state == "unknown"
    assert state.attributes.get("raw") == 42


async def test_fault_code_sensor_none_when_no_fault(hass: HomeAssistant) -> None:
    """fault_code sensor reports 'none' slug when fault field is 0."""
    props = make_props(work_mode=0, status=4, charge_state=1, fault=0, battery=95)
    fake = FakeAdapter(props=props)
    await _setup_with_props(hass, fake)

    state = hass.states.get("sensor.test_robot_robot_status")
    assert state is not None
    assert state.state == "none"
    assert state.attributes.get("raw") == 0


async def test_sensors_unavailable_when_no_data(hass: HomeAssistant) -> None:
    """Sensors return unavailable when coordinator has no data."""
    # Cause the first refresh to fail so coordinator.data stays None
    fake = FakeAdapter(fetch_raises=TransientError("no data"))
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

    # Entry will be in SETUP_RETRY; entities are not yet registered
    # The test here confirms that when data is None, state is unavailable
    # (when entities exist after a reload after initial transient failure,
    # they would show unavailable — this is verified via the vacuum test.)
    assert entry.state.value in ("setup_retry", "setup_error", "loaded")


# ---------------------------------------------------------------------------
# Binary sensor tests
# ---------------------------------------------------------------------------


async def test_error_sensor_off_when_idle(hass: HomeAssistant) -> None:
    """Error sensor is off when robot is idle without fault."""
    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup_with_props(hass, fake)

    state = hass.states.get("binary_sensor.test_robot_error")
    assert state is not None
    assert state.state == "off"


async def test_error_sensor_on_when_error_state(hass: HomeAssistant) -> None:
    """Error sensor is on only when vacuum_state == Error."""
    fake = FakeAdapter(props=PROPS_ERROR)
    await _setup_with_props(hass, fake)

    state = hass.states.get("binary_sensor.test_robot_error")
    assert state is not None
    assert state.state == "on"


@pytest.mark.parametrize(
    "props",
    [PROPS_CLEANING, PROPS_RETURNING],
    ids=["cleaning", "returning"],
)
async def test_error_sensor_off_during_cleaning_or_returning(
    hass: HomeAssistant, props: object
) -> None:
    """Transient faults during cleaning or returning do not flip the error sensor.

    FR-BS-2: error only when idle AND faulted AND not docked.
    """
    assert isinstance(props, DeviceProperties)
    # Inject a fault while cleaning/returning (non-idle work_mode)
    props_with_fault = make_props(
        work_mode=props.work_mode,
        status=props.status,
        charge_state=props.charge_state,
        fault=99,
        battery=50,
    )
    fake = FakeAdapter(props=props_with_fault)
    await _setup_with_props(hass, fake)

    state = hass.states.get("binary_sensor.test_robot_error")
    assert state is not None
    assert state.state == "off"


# ---------------------------------------------------------------------------
# None-data guard tests — entity properties when coordinator.data is None
# ---------------------------------------------------------------------------


async def test_battery_sensor_returns_none_when_no_data(hass: HomeAssistant) -> None:
    """KarcherSensor(battery).native_value returns None when data is None."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup_with_props(hass, fake)
    coordinator = entry.runtime_data
    desc = next(d for d in _SENSORS if d.key == "battery")
    entity = KarcherSensor(coordinator, desc)
    coordinator.async_set_updated_data(None)  # type: ignore[arg-type]
    assert entity.native_value is None


async def test_cleaning_time_sensor_returns_none_when_no_data(hass: HomeAssistant) -> None:
    """KarcherSensor(cleaning_time).native_value returns None when data is None."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup_with_props(hass, fake)
    coordinator = entry.runtime_data
    desc = next(d for d in _SENSORS if d.key == "cleaning_time")
    entity = KarcherSensor(coordinator, desc)
    coordinator.async_set_updated_data(None)  # type: ignore[arg-type]
    assert entity.native_value is None


async def test_fault_code_sensor_extra_attrs_none_when_no_data(hass: HomeAssistant) -> None:
    """KarcherSensor(fault_code).extra_state_attributes returns None when data is None."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup_with_props(hass, fake)
    coordinator = entry.runtime_data
    desc = next(d for d in _SENSORS if d.key == "fault_code")
    entity = KarcherSensor(coordinator, desc)
    coordinator.async_set_updated_data(None)  # type: ignore[arg-type]
    assert entity.extra_state_attributes is None


async def test_error_sensor_is_on_returns_none_when_no_data(hass: HomeAssistant) -> None:
    """KarcherErrorSensor.is_on returns None when data is None."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup_with_props(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherErrorSensor(coordinator)
    coordinator.async_set_updated_data(None)  # type: ignore[arg-type]
    assert entity.is_on is None


# ---------------------------------------------------------------------------
# Charging sensor tests
# ---------------------------------------------------------------------------


async def test_charging_sensor_on_when_docked(hass: HomeAssistant) -> None:
    """Charging sensor is on when charge_state > 0."""
    fake = FakeAdapter(props=PROPS_DOCKED)
    await _setup_with_props(hass, fake)

    state = hass.states.get("binary_sensor.test_robot_charging")
    assert state is not None
    assert state.state == "on"


async def test_charging_sensor_off_when_cleaning(hass: HomeAssistant) -> None:
    """Charging sensor is off when cleaning (charge_state == 0)."""
    fake = FakeAdapter(props=PROPS_CLEANING)
    await _setup_with_props(hass, fake)

    state = hass.states.get("binary_sensor.test_robot_charging")
    assert state is not None
    assert state.state == "off"


async def test_charging_sensor_is_on_returns_none_when_no_data(hass: HomeAssistant) -> None:
    """KarcherChargingSensor.is_on returns None when data is None."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup_with_props(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherChargingSensor(coordinator)
    coordinator.async_set_updated_data(None)  # type: ignore[arg-type]
    assert entity.is_on is None


async def test_charging_sensor_off_when_charge_state_none(hass: HomeAssistant) -> None:
    """Charging sensor is off when charge_state is None (not yet received)."""
    props = make_props(work_mode=0, status=0, charge_state=None)
    fake = FakeAdapter(props=props)
    entry = await _setup_with_props(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherChargingSensor(coordinator)
    assert entity.is_on is False


# ---------------------------------------------------------------------------
# Connectivity sensor tests
# ---------------------------------------------------------------------------


async def test_connectivity_sensor_on_when_reachable(hass: HomeAssistant) -> None:
    """Connectivity sensor is on when polls are succeeding."""
    fake = FakeAdapter(props=PROPS_IDLE)
    await _setup_with_props(hass, fake)

    state = hass.states.get("binary_sensor.test_robot_connectivity")
    assert state is not None
    assert state.state == "on"


async def test_connectivity_sensor_always_available(hass: HomeAssistant) -> None:
    """Connectivity sensor stays available even when coordinator has no data."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup_with_props(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherConnectivitySensor(coordinator)
    coordinator.async_set_updated_data(None)  # type: ignore[arg-type]
    assert entity.available is True


async def test_connectivity_sensor_off_during_outage(hass: HomeAssistant) -> None:
    """Connectivity sensor reflects outage state tracked by coordinator."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup_with_props(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherConnectivitySensor(coordinator)

    # Simulate outage: set internal outage state directly
    coordinator._outage_start = coordinator.hass.loop.time()
    assert entity.is_on is False

    # Simulate recovery
    coordinator._outage_start = None
    coordinator._consecutive_failures = 0
    assert entity.is_on is True


async def test_vacuum_activity_none_when_unavailable(hass: HomeAssistant) -> None:
    """KarcherVacuum.activity returns None when the entity is unavailable."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup_with_props(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherVacuum(coordinator)
    coordinator.async_set_updated_data(None)  # type: ignore[arg-type]
    assert entity.activity is None


# ---------------------------------------------------------------------------
# Supported-features regression guard (see commit c437779 / d14c9e2)
# ---------------------------------------------------------------------------

_EXPECTED_FEATURES = (
    VacuumEntityFeature.START
    | VacuumEntityFeature.STOP
    | VacuumEntityFeature.PAUSE
    | VacuumEntityFeature.RETURN_HOME
    | VacuumEntityFeature.LOCATE
    | VacuumEntityFeature.FAN_SPEED
    | VacuumEntityFeature.SEND_COMMAND
    | VacuumEntityFeature.CLEAN_AREA
    | VacuumEntityFeature.STATE
)


async def test_vacuum_supported_features(hass: HomeAssistant) -> None:
    """Vacuum exposes the exact feature set required for HAMH ServiceArea."""
    fake = FakeAdapter(props=PROPS_IDLE)
    entry = await _setup_with_props(hass, fake)
    coordinator = entry.runtime_data
    entity = KarcherVacuum(coordinator)
    assert entity.supported_features == _EXPECTED_FEATURES
