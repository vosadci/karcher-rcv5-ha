# SPDX-License-Identifier: MIT
"""Constants for the Kärcher Home Robots integration."""

from __future__ import annotations

DOMAIN = "karcher_home_robots"

POLL_INTERVAL_SECONDS = 30

# work_mode values grouped by derived HA vacuum state.
# Source: doc/PROTOCOL.md §6, traffic capture 2026-03-28.
WORK_MODE_CLEANING: frozenset[int] = frozenset({1, 7, 25, 30, 36, 81})
WORK_MODE_GO_HOME: frozenset[int] = frozenset({5, 10, 11, 12, 21, 26, 32, 38, 47})
WORK_MODE_PAUSE: frozenset[int] = frozenset({4, 9, 27, 31, 37, 82})
WORK_MODE_IDLE: frozenset[int] = frozenset({0, 14, 23, 29, 35, 40, 85})

# work_mode values whose active task is an area (zone) clean, across its
# lifecycle: 30=cleaning, 31=paused, 32=returning, 35=idle. The robot encodes
# (clean-family, lifecycle) in work_mode; this is the zone family, matching the
# app's IotBase.getCleanMode == 6 (APK v1.4.32). Pause/resume of a zone clean
# must route through set_zone_clean, so the entity reads the live work_mode to
# decide — exactly as the app does — rather than tracking local state.
WORK_MODE_ZONE_CLEAN: frozenset[int] = frozenset({30, 31, 32, 35})

# Cleaning mode (prop.set "mode") values.
# Source: doc/PROTOCOL.md §5, traffic capture 2026-03-29.
CLEANING_MODE_VACUUM = 0
CLEANING_MODE_VACUUM_AND_MOP = 1
CLEANING_MODE_MOP = 2

# Fault code → translation slug mapping.
# Source: doc/PROTOCOL.md §6, RobotError.java + RobotFaultCode.java (APK v1.4.32, 2026-06-01).
FAULT_CODE_DESCRIPTIONS: dict[int, str] = {
    0: "none",
    100: "hw_driver",
    500: "lidar_timeout",
    501: "wheel_lifted",
    502: "low_battery_start",
    503: "dust_box_missing",
    504: "geomagnetic_fault",
    505: "start_from_dock_failed",
    506: "follow_ir_exception",
    507: "relocalization_failed",
    508: "slope_start_failed",
    509: "cliff_ir_fault",
    510: "bumper_fault",
    511: "return_to_dock_failed",
    512: "place_on_dock",
    513: "navigation_failed",
    514: "escape_stuck_failed",
    515: "dock_clip_exception",
    516: "battery_temperature_fault",
    517: "system_upgrading",
    518: "waiting_for_charge",
    519: "main_brush_stalled",
    520: "side_brush_stalled",
    521: "water_box_missing",
    522: "mop_missing",
    523: "dust_box_full",
    524: "power_switch_off",
    525: "water_tank_empty",
    526: "mop_dirty",
    527: "dust_box_full_alt",
    530: "battery_temp_abnormal",
    531: "battery_temp_normal",
    2000: "dust_box_full_2000",
    2001: "left_brush_blocked",
    2002: "right_brush_blocked",
    2003: "no_power_plan_disabled",
    2007: "cleaning_interrupted",
    2008: "cleaning_complete",
    2009: "scheduled_clean_complete",
    2010: "tof_abnormal",
    2100: "return_to_dock_interrupted",
    2101: "charging_interrupted",
    2102: "returning_to_dock",
    2103: "state_changing",
    2104: "user_return_to_dock",
    2105: "charging_complete",
    2106: "charging_wait_interrupted",
    2107: "scheduled_clean_in_progress",
    2108: "relocalizing",
    2109: "repeat_cleaning",
    2110: "self_checking",
    4002: "map_error",
}
