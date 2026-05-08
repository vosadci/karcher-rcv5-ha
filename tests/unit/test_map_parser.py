# SPDX-License-Identifier: MIT
"""Unit tests for map_parser.parse_map().

The dict format matches karcher-home's Map.data output:
- map_head fields are snake_case (size_x, size_y, min_x, min_y)
- map_data is a base64-encoded string (MessageToDict encodes bytes as base64)
"""

from __future__ import annotations

import base64

from custom_components.karcher_home_robots.map_parser import parse_map


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _minimal_raw(grid_bytes: bytes = b"\x00" * 3600) -> dict:
    return {
        "map_head": {
            "resolution": 0.05,
            "size_x": 120,
            "size_y": 120,
            "min_x": -3.0,
            "min_y": -3.0,
        },
        "map_data": _b64(grid_bytes),
        "history_pose": {"points": [{"x": 1.0, "y": 2.0}, {"x": 3.0, "y": 4.0}]},
        "current_pose": {"x": 0.5, "y": 0.6, "phi": 1.57},
        "charge_station": {"x": -1.0, "y": -1.0},
    }


def test_grid_dimensions() -> None:
    snap = parse_map(_minimal_raw(), cur_path=[])
    assert snap is not None
    assert snap.grid.width == 120
    assert snap.grid.height == 120


def test_grid_resolution_and_origin() -> None:
    snap = parse_map(_minimal_raw(), cur_path=[])
    assert snap is not None
    assert snap.grid.resolution == 0.05
    assert snap.grid.min_x == -3.0
    assert snap.grid.min_y == -3.0


def test_grid_bytes_decoded_from_base64() -> None:
    data = bytes(range(256)) * 14 + bytes(16)  # 3600 bytes
    snap = parse_map(_minimal_raw(data), cur_path=[])
    assert snap is not None
    assert snap.grid.data == data


def test_history_pose_parsed() -> None:
    snap = parse_map(_minimal_raw(), cur_path=[])
    assert snap is not None
    assert snap.path == [(1.0, 2.0), (3.0, 4.0)]


def test_current_pose_parsed() -> None:
    snap = parse_map(_minimal_raw(), cur_path=[])
    assert snap is not None
    assert snap.robot is not None
    assert snap.robot.x == 0.5
    assert snap.robot.y == 0.6
    assert abs(snap.robot.phi - 1.57) < 1e-9


def test_charge_station_parsed() -> None:
    snap = parse_map(_minimal_raw(), cur_path=[])
    assert snap is not None
    assert snap.charger is not None
    assert snap.charger.x == -1.0
    assert snap.charger.y == -1.0


def test_cur_path_forwarded() -> None:
    pts = [(0.1, 0.2), (0.3, 0.4)]
    snap = parse_map(_minimal_raw(), cur_path=pts)
    assert snap is not None
    assert snap.cur_path == pts


def test_missing_map_data_returns_none() -> None:
    raw = _minimal_raw()
    del raw["map_data"]
    snap = parse_map(raw, cur_path=[])
    assert snap is None


def test_missing_current_pose_is_none() -> None:
    raw = _minimal_raw()
    del raw["current_pose"]
    snap = parse_map(raw, cur_path=[])
    assert snap is not None
    assert snap.robot is None


def test_missing_charge_station_is_none() -> None:
    raw = _minimal_raw()
    del raw["charge_station"]
    snap = parse_map(raw, cur_path=[])
    assert snap is not None
    assert snap.charger is None


def test_empty_history_pose() -> None:
    raw = _minimal_raw()
    raw["history_pose"] = {}
    snap = parse_map(raw, cur_path=[])
    assert snap is not None
    assert snap.path == []


def test_malformed_history_pose_entries_skipped() -> None:
    raw = _minimal_raw()
    raw["history_pose"] = {"points": [{"x": 1.0, "y": 2.0}, {"bad": "entry"}, {"x": 3.0, "y": 4.0}]}
    snap = parse_map(raw, cur_path=[])
    assert snap is not None
    assert snap.path == [(1.0, 2.0), (3.0, 4.0)]


def test_map_data_as_raw_bytes() -> None:
    raw = _minimal_raw()
    raw["map_data"] = b"\x00" * 3600
    snap = parse_map(raw, cur_path=[])
    assert snap is not None
    assert len(snap.grid.data) == 3600


def test_exception_returns_none() -> None:
    snap = parse_map({"map_head": "bad"}, cur_path=[])
    assert snap is None


def test_objects_parsed() -> None:
    raw = _minimal_raw()
    raw["objects"] = [
        {"object_id": 1, "object_type_id": 1003, "object_name": "obj_1", "x": 1.0, "y": 2.0},
        {"object_id": 2, "object_type_id": 1005, "object_name": "obj_2", "x": 3.0, "y": 4.0},
    ]
    snap = parse_map(raw, cur_path=[])
    assert snap is not None
    assert len(snap.objects) == 2
    assert snap.objects[0].type_id == 1003
    assert snap.objects[0].x == 1.0
    assert snap.objects[1].type_id == 1005


def test_objects_missing_is_empty() -> None:
    snap = parse_map(_minimal_raw(), cur_path=[])
    assert snap is not None
    assert snap.objects == []


def test_objects_malformed_entries_skipped() -> None:
    raw = _minimal_raw()
    raw["objects"] = [
        {"object_id": 1, "object_type_id": 1003, "x": 1.0, "y": 2.0},
        {"bad": "entry"},
        {"object_id": 3, "object_type_id": 1005, "x": 3.0, "y": 4.0},
    ]
    snap = parse_map(raw, cur_path=[])
    assert snap is not None
    assert len(snap.objects) == 2


def test_camelcase_head_fields_fallback() -> None:
    raw = _minimal_raw()
    raw["map_head"] = {"resolution": 0.05, "sizeX": 60, "sizeY": 60, "minX": 1.0, "minY": 2.0}
    snap = parse_map(raw, cur_path=[])
    assert snap is not None
    assert snap.grid.width == 60
    assert snap.grid.height == 60
    assert snap.grid.min_x == 1.0
