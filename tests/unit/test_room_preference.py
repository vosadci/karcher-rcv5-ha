# SPDX-License-Identifier: MIT
"""Unit tests for the RoomPreference wire-format round-trip.

Array layout (APK GetPreferenceResp / CustomSortRoomActivity.java):
  [roomId, roomName, materialId, mode, wind, water, repeat, carpet,
   check, 0, 0, carpetAvoidance]
"""

from __future__ import annotations

from custom_components.karcher_home_robots._types import RoomPreference


def test_from_raw_parses_all_fields() -> None:
    row = [7, "Kitchen", 2, 1, 3, 2, 1, 1, 1, 0, 0, 1]
    pref = RoomPreference.from_raw(row)
    assert pref is not None
    assert pref.room_id == 7
    assert pref.room_name == "Kitchen"
    assert pref.material_id == 2
    assert pref.mode == 1
    assert pref.wind == 3
    assert pref.water == 2
    assert pref.repeat == 1
    assert pref.carpet == 1
    assert pref.check == 1
    assert pref.carpet_avoidance == 1


def test_round_trip_preserves_material_and_carpet() -> None:
    """Regression guard: to_raw used to hard-code materialId and carpet to 0,
    so any single-room edit zeroed those fields for every room on the robot."""
    row = [7, "Kitchen", 2, 1, 3, 2, 1, 1, 1, 0, 0, 1]
    pref = RoomPreference.from_raw(row)
    assert pref is not None
    assert pref.to_raw() == row


def test_from_raw_nine_element_reply_defaults() -> None:
    """The robot replies with 9-element arrays; trailing fields default."""
    row = [3, "Hall", 0, 0, 1, 2, 0, 0, 0]
    pref = RoomPreference.from_raw(row)
    assert pref is not None
    assert pref.carpet_avoidance == 0
    assert pref.to_raw() == [3, "Hall", 0, 0, 1, 2, 0, 0, 0, 0, 0, 0]


def test_from_raw_rejects_short_and_malformed_rows() -> None:
    assert RoomPreference.from_raw([1, "x", 0]) is None
    assert RoomPreference.from_raw("not a list") is None  # type: ignore[arg-type]
    assert RoomPreference.from_raw([None, "x", 0, 0, 0, 0, 0, 0, 0]) is None
