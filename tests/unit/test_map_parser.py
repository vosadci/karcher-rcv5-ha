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
    snap = parse_map(_minimal_raw())
    assert snap is not None
    assert snap.grid.width == 120
    assert snap.grid.height == 120


def test_oversized_grid_dimensions_rejected() -> None:
    raw = _minimal_raw()
    raw["map_head"]["size_x"] = 100000
    assert parse_map(raw) is None


def test_zero_grid_dimensions_rejected() -> None:
    raw = _minimal_raw()
    raw["map_head"]["size_y"] = 0
    assert parse_map(raw) is None


def test_oversized_cell_count_rejected() -> None:
    # Each dimension is within the per-side cap but the product blows the cell
    # budget (~1M) — the renderer would allocate a huge supersampled buffer.
    raw = _minimal_raw()
    raw["map_head"]["size_x"] = 3000
    raw["map_head"]["size_y"] = 3000
    assert parse_map(raw) is None


def test_grid_resolution_and_origin() -> None:
    snap = parse_map(_minimal_raw())
    assert snap is not None
    assert snap.grid.resolution == 0.05
    assert snap.grid.min_x == -3.0
    assert snap.grid.min_y == -3.0


def test_grid_bytes_decoded_from_base64() -> None:
    data = bytes(range(256)) * 14 + bytes(16)  # 3600 bytes
    snap = parse_map(_minimal_raw(data))
    assert snap is not None
    assert snap.grid.data == data


def test_history_pose_parsed() -> None:
    snap = parse_map(_minimal_raw())
    assert snap is not None
    assert snap.path == [(1.0, 2.0), (3.0, 4.0)]


def test_current_pose_parsed() -> None:
    snap = parse_map(_minimal_raw())
    assert snap is not None
    assert snap.robot is not None
    assert snap.robot.x == 0.5
    assert snap.robot.y == 0.6
    assert abs(snap.robot.phi - 1.57) < 1e-9


def test_charge_station_parsed() -> None:
    snap = parse_map(_minimal_raw())
    assert snap is not None
    assert snap.charger is not None
    assert snap.charger.x == -1.0
    assert snap.charger.y == -1.0


def test_charge_station_phi_parsed() -> None:
    """charge_station.phi is the charger's own heading — needed to derive the
    docked robot's displayed pose (see coordinator._project_overlays)."""
    raw = _minimal_raw()
    raw["charge_station"] = {"x": -1.0, "y": -1.0, "phi": 1.5}
    snap = parse_map(raw)
    assert snap is not None
    assert snap.charger is not None
    assert snap.charger.phi == 1.5


def test_charge_station_phi_defaults_to_zero_when_absent() -> None:
    snap = parse_map(_minimal_raw())
    assert snap is not None
    assert snap.charger is not None
    assert snap.charger.phi == 0.0


def test_missing_map_data_returns_none() -> None:
    raw = _minimal_raw()
    del raw["map_data"]
    snap = parse_map(raw)
    assert snap is None


def test_missing_current_pose_is_none() -> None:
    raw = _minimal_raw()
    del raw["current_pose"]
    snap = parse_map(raw)
    assert snap is not None
    assert snap.robot is None


def test_missing_charge_station_is_none() -> None:
    raw = _minimal_raw()
    del raw["charge_station"]
    snap = parse_map(raw)
    assert snap is not None
    assert snap.charger is None


def test_empty_history_pose() -> None:
    raw = _minimal_raw()
    raw["history_pose"] = {}
    snap = parse_map(raw)
    assert snap is not None
    assert snap.path == []


def test_malformed_history_pose_entries_skipped() -> None:
    raw = _minimal_raw()
    raw["history_pose"] = {"points": [{"x": 1.0, "y": 2.0}, {"bad": "entry"}, {"x": 3.0, "y": 4.0}]}
    snap = parse_map(raw)
    assert snap is not None
    assert snap.path == [(1.0, 2.0), (3.0, 4.0)]


def test_map_data_as_raw_bytes() -> None:
    raw = _minimal_raw()
    raw["map_data"] = b"\x00" * 3600
    snap = parse_map(raw)
    assert snap is not None
    assert len(snap.grid.data) == 3600


def test_exception_returns_none() -> None:
    snap = parse_map({"map_head": "bad"})
    assert snap is None


def test_objects_parsed() -> None:
    raw = _minimal_raw()
    raw["objects"] = [
        {"object_id": 1, "object_type_id": 1003, "object_name": "obj_1", "x": 1.0, "y": 2.0},
        {"object_id": 2, "object_type_id": 1005, "object_name": "obj_2", "x": 3.0, "y": 4.0},
    ]
    snap = parse_map(raw)
    assert snap is not None
    assert len(snap.objects) == 2
    assert snap.objects[0].type_id == 1003
    assert snap.objects[0].x == 1.0
    assert snap.objects[1].type_id == 1005


def test_objects_missing_is_empty() -> None:
    snap = parse_map(_minimal_raw())
    assert snap is not None
    assert snap.objects == []


def test_objects_malformed_entries_skipped() -> None:
    raw = _minimal_raw()
    raw["objects"] = [
        {"object_id": 1, "object_type_id": 1003, "x": 1.0, "y": 2.0},
        {"bad": "entry"},
        {"object_id": 3, "object_type_id": 1005, "x": 3.0, "y": 4.0},
    ]
    snap = parse_map(raw)
    assert snap is not None
    assert len(snap.objects) == 2


def test_camelcase_head_fields_fallback() -> None:
    raw = _minimal_raw()
    raw["map_head"] = {"resolution": 0.05, "sizeX": 60, "sizeY": 60, "minX": 1.0, "minY": 2.0}
    snap = parse_map(raw)
    assert snap is not None
    assert snap.grid.width == 60
    assert snap.grid.height == 60
    assert snap.grid.min_x == 1.0


# ---------------------------------------------------------------------------
# _parse_history_pose — non-list points branch (line 91)
# ---------------------------------------------------------------------------


def test_history_pose_non_list_points_returns_empty() -> None:
    raw = _minimal_raw()
    raw["history_pose"] = {"points": "not-a-list"}
    snap = parse_map(raw)
    assert snap is not None
    assert snap.path == []


# ---------------------------------------------------------------------------
# _parse_current_pose — malformed dict (lines 104-105)
# ---------------------------------------------------------------------------


def test_malformed_current_pose_returns_none() -> None:
    raw = _minimal_raw()
    raw["current_pose"] = {"x": "not-a-number", "y": 0.0}
    snap = parse_map(raw)
    assert snap is not None
    assert snap.robot is None


# ---------------------------------------------------------------------------
# _parse_charge_station — malformed dict (lines 113-114)
# ---------------------------------------------------------------------------


def test_malformed_charge_station_returns_none() -> None:
    raw = _minimal_raw()
    raw["charge_station"] = {"x": None, "y": 0.0}
    snap = parse_map(raw)
    assert snap is not None
    assert snap.charger is None


# ---------------------------------------------------------------------------
# _parse_room_data_info (lines 134-151) — entirely uncovered
# ---------------------------------------------------------------------------


def test_room_data_info_parsed() -> None:
    raw = _minimal_raw()
    raw["room_data_info"] = [
        {
            "room_id": 1,
            "room_name": "Living Room",
            "color_id": 3,
            "room_name_post": {"x": 1.5, "y": 2.5},
            "meterial_id": 0,
        },
        {
            "room_id": 2,
            "room_name": "Bedroom",
            "color_id": 5,
            "room_name_post": {"x": 3.0, "y": 4.0},
            "meterial_id": 1,
        },
    ]
    snap = parse_map(raw)
    assert snap is not None
    assert len(snap.rooms) == 2
    r0 = snap.rooms[0]
    assert r0.room_id == 1
    assert r0.name == "Living Room"
    assert r0.color_id == 3
    assert r0.label_x == 1.5
    assert r0.label_y == 2.5
    assert r0.is_carpet is False
    assert snap.rooms[1].is_carpet is True  # meterial_id == 1


def test_room_data_info_non_list_returns_empty() -> None:
    raw = _minimal_raw()
    raw["room_data_info"] = "not-a-list"
    snap = parse_map(raw)
    assert snap is not None
    assert snap.rooms == []


def test_room_data_info_malformed_entry_skipped() -> None:
    raw = _minimal_raw()
    raw["room_data_info"] = [
        {"room_id": 1, "room_name": "Good Room", "color_id": 2},
        {"bad": "entry"},
    ]
    snap = parse_map(raw)
    assert snap is not None
    assert len(snap.rooms) == 1


def test_room_data_info_missing_is_empty() -> None:
    snap = parse_map(_minimal_raw())
    assert snap is not None
    assert snap.rooms == []


# ---------------------------------------------------------------------------
# _parse_room_chain (lines 154-189) — entirely uncovered
# ---------------------------------------------------------------------------


def test_room_chain_wall_and_separator_points() -> None:
    raw = _minimal_raw()
    raw["room_chain"] = [
        {
            "room_id": 1,
            "points": [
                {"x": 0, "y": 0, "value": -1},
                {"x": 1, "y": 0, "value": -1},
                {"x": 0, "y": 1, "value": 1},
            ],
        }
    ]
    snap = parse_map(raw)
    assert snap is not None
    assert len(snap.room_chains) == 1
    chain = snap.room_chains[0]
    assert chain.room_id == 1
    assert len(chain.points) == 2
    assert len(chain.separator_points) == 1


def test_room_chain_coordinate_transform() -> None:
    # min_x=-3.0, min_y=-3.0, resolution=0.05 (from _minimal_raw map_head)
    raw = _minimal_raw()
    raw["room_chain"] = [{"room_id": 2, "points": [{"x": 10, "y": 20, "value": -1}]}]
    snap = parse_map(raw)
    assert snap is not None
    chain = snap.room_chains[0]
    assert abs(chain.points[0][0] - (-3.0 + 10 * 0.05)) < 1e-9
    assert abs(chain.points[0][1] - (-3.0 + 20 * 0.05)) < 1e-9


def test_room_chain_non_list_returns_empty() -> None:
    raw = _minimal_raw()
    raw["room_chain"] = "not-a-list"
    snap = parse_map(raw)
    assert snap is not None
    assert snap.room_chains == []


def test_room_chain_malformed_entry_skipped() -> None:
    raw = _minimal_raw()
    raw["room_chain"] = [
        {"bad": "no-room-id"},
        {"room_id": 5, "points": [{"x": 0, "y": 0, "value": -1}]},
    ]
    snap = parse_map(raw)
    assert snap is not None
    assert len(snap.room_chains) == 1
    assert snap.room_chains[0].room_id == 5


def test_room_chain_empty_points_produces_no_chain() -> None:
    raw = _minimal_raw()
    raw["room_chain"] = [{"room_id": 3, "points": []}]
    snap = parse_map(raw)
    assert snap is not None
    assert snap.room_chains == []


def test_room_chain_missing_is_empty() -> None:
    snap = parse_map(_minimal_raw())
    assert snap is not None
    assert snap.room_chains == []


# ---------------------------------------------------------------------------
# _parse_furniture_info — area carpets (doc/MAP_DATA.md §6.4 mechanism 2)
# ---------------------------------------------------------------------------


def test_furniture_info_carpet_parsed() -> None:
    raw = _minimal_raw()
    raw["furniture_info"] = [
        {
            "id": 3,
            "type_id": 1550,
            "points": [
                {"x": -2.0, "y": -2.0},
                {"x": -1.0, "y": -2.0},
                {"x": -1.0, "y": -1.2},
                {"x": -2.0, "y": -1.2},
            ],
        },
    ]
    snap = parse_map(raw)
    assert snap is not None
    assert len(snap.carpets) == 1
    carpet = snap.carpets[0]
    assert carpet.carpet_id == 3
    assert carpet.points == [(-2.0, -2.0), (-1.0, -2.0), (-1.0, -1.2), (-2.0, -1.2)]


def test_furniture_info_non_carpet_types_filtered() -> None:
    """Only type_id 1550 (carpet) is kept; other furniture types are ignored."""
    raw = _minimal_raw()
    raw["furniture_info"] = [
        {"id": 1, "type_id": 1513, "points": [{"x": 0.0, "y": 0.0}]},  # bed
        {"id": 2, "type_id": 1550, "points": [{"x": 1.0, "y": 1.0}]},
    ]
    snap = parse_map(raw)
    assert snap is not None
    assert len(snap.carpets) == 1
    assert snap.carpets[0].carpet_id == 2


def test_furniture_info_omitted_zero_fields_default() -> None:
    """MessageToDict omits zero-valued proto fields; id/x/y default to 0."""
    raw = _minimal_raw()
    raw["furniture_info"] = [{"type_id": 1550, "points": [{"x": 1.5}, {"y": -2.0}]}]
    snap = parse_map(raw)
    assert snap is not None
    assert len(snap.carpets) == 1
    assert snap.carpets[0].carpet_id == 0
    assert snap.carpets[0].points == [(1.5, 0.0), (0.0, -2.0)]


def test_furniture_info_missing_is_empty() -> None:
    snap = parse_map(_minimal_raw())
    assert snap is not None
    assert snap.carpets == []


def test_furniture_info_non_list_returns_empty() -> None:
    raw = _minimal_raw()
    raw["furniture_info"] = "not-a-list"
    snap = parse_map(raw)
    assert snap is not None
    assert snap.carpets == []


def test_furniture_info_malformed_entries_skipped() -> None:
    raw = _minimal_raw()
    raw["furniture_info"] = [
        "not-a-dict",
        {"id": 1, "type_id": "not-an-int", "points": [{"x": 0.0, "y": 0.0}]},
        {"id": 2, "type_id": 1550, "points": ["bad", {"x": 1.0, "y": 2.0}]},
        {"id": 3, "type_id": 1550, "points": []},  # no points → skipped
        {"id": 4, "type_id": 1550},  # points absent → skipped
    ]
    snap = parse_map(raw)
    assert snap is not None
    assert len(snap.carpets) == 1
    assert snap.carpets[0].carpet_id == 2
    assert snap.carpets[0].points == [(1.0, 2.0)]


def test_virtual_walls_nogo_and_nomop_parsed() -> None:
    raw = _minimal_raw()
    raw["virtual_walls"] = [
        {
            "type": 1,  # no-go area
            "area_index": 5,
            "points": [
                {"x": -1.0, "y": -1.0},
                {"x": 1.0, "y": -1.0},
                {"x": 1.0, "y": 1.0},
                {"x": -1.0, "y": 1.0},
            ],
        },
        {
            "type": 6,  # no-mop area (device-emitted code)
            "area_index": 6,
            "points": [{"x": 2.0, "y": 2.0}, {"x": 3.0, "y": 3.0}],
        },
    ]
    snap = parse_map(raw)
    assert snap is not None
    assert len(snap.zones) == 2
    nogo = snap.zones[0]
    assert nogo.zone_id == 5
    assert nogo.type_id == 1
    assert nogo.points == [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]
    assert snap.zones[1].type_id == 6
    assert snap.zones[1].zone_id == 6


def test_virtual_walls_line_wall_parsed() -> None:
    raw = _minimal_raw()
    raw["virtual_walls"] = [
        {"type": 2, "area_index": 1, "points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]},
    ]
    snap = parse_map(raw)
    assert snap is not None
    assert len(snap.zones) == 1
    assert snap.zones[0].type_id == 2
    assert snap.zones[0].points == [(0.0, 0.0), (1.0, 1.0)]


def test_virtual_walls_unknown_type_kept() -> None:
    """Lenient parse: unknown/omitted types are kept (raw type preserved) so the
    renderer can still surface them — areas may use type codes we haven't mapped."""
    raw = _minimal_raw()
    raw["virtual_walls"] = [
        {"type": 9, "area_index": 1, "points": [{"x": 0.0, "y": 0.0}]},  # unknown type
        {"area_index": 2, "points": [{"x": 1.0, "y": 1.0}]},  # type omitted → 0
    ]
    snap = parse_map(raw)
    assert snap is not None
    assert len(snap.zones) == 2
    assert snap.zones[0].type_id == 9
    assert snap.zones[1].type_id == 0


def test_virtual_walls_omitted_zero_fields_default() -> None:
    """MessageToDict omits zero-valued proto fields; area_index/x/y default to 0."""
    raw = _minimal_raw()
    raw["virtual_walls"] = [{"type": 1, "points": [{"x": 1.5}, {"y": -2.0}]}]
    snap = parse_map(raw)
    assert snap is not None
    assert len(snap.zones) == 1
    assert snap.zones[0].zone_id == 0
    assert snap.zones[0].points == [(1.5, 0.0), (0.0, -2.0)]


def test_virtual_walls_missing_is_empty() -> None:
    snap = parse_map(_minimal_raw())
    assert snap is not None
    assert snap.zones == []


def test_virtual_walls_non_list_returns_empty() -> None:
    raw = _minimal_raw()
    raw["virtual_walls"] = "not-a-list"
    snap = parse_map(raw)
    assert snap is not None
    assert snap.zones == []


def test_virtual_walls_malformed_entries_skipped() -> None:
    raw = _minimal_raw()
    raw["virtual_walls"] = [
        "not-a-dict",
        {"type": "bad", "points": [{"x": 0.0, "y": 0.0}]},
        {"type": 1, "points": ["bad", {"x": 1.0, "y": 2.0}]},
        {"type": 1, "points": []},  # no points → skipped
        {"type": 1},  # points absent → skipped
    ]
    snap = parse_map(raw)
    assert snap is not None
    assert len(snap.zones) == 1
    assert snap.zones[0].points == [(1.0, 2.0)]


def test_areas_info_parsed_as_cleaning_zone_not_restriction() -> None:
    """areas_info (field 10) carries active zone-clean rectangles, not restrictions
    (the app parses it via a separate path from virtual_walls). It must surface as a
    CleaningZone, never a RestrictedZone — else a drawn clean area renders as a no-go."""
    raw = _minimal_raw()
    raw["areas_info"] = [
        {"type": 1, "area_index": 7, "points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]},
    ]
    snap = parse_map(raw)
    assert snap is not None
    assert snap.zones == []
    assert len(snap.cleaning_zones) == 1
    assert snap.cleaning_zones[0].zone_id == 7
    assert snap.cleaning_zones[0].points == [(0.0, 0.0), (1.0, 1.0)]


def test_zones_only_from_virtual_walls() -> None:
    raw = _minimal_raw()
    raw["virtual_walls"] = [
        {"type": 2, "area_index": 1, "points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]},
    ]
    raw["areas_info"] = [
        {"type": 1, "area_index": 2, "points": [{"x": 2.0, "y": 2.0}, {"x": 3.0, "y": 3.0}]},
    ]
    snap = parse_map(raw)
    assert snap is not None
    assert {z.zone_id for z in snap.zones} == {1}


# ---------------------------------------------------------------------------
# grid_bytes fallback — iterable-of-ints path (line 59)
# ---------------------------------------------------------------------------


def test_map_data_as_iterable_ints() -> None:
    raw = _minimal_raw()
    raw["map_data"] = list(range(256)) * 14 + [0] * 16  # list of ints, 3600 items
    snap = parse_map(raw)
    assert snap is not None
    assert len(snap.grid.data) == 3600
