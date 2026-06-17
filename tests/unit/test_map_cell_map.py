# SPDX-License-Identifier: MIT
"""Unit tests for map_render.compute_room_cell_map and vacuum extra_state_attributes."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from custom_components.karcher_home_robots.map_data import (
    MapGrid,
    MapSnapshot,
    Pose,
    RoomInfo,
)
from custom_components.karcher_home_robots.map_render import RenderLayout
from custom_components.karcher_home_robots.map_render import (
    compute_room_cell_map as _compute_room_cell_map,
)


def _layout(width: int, height: int, scale: int = 2) -> RenderLayout:
    return RenderLayout(
        col0=0,
        row0=0,
        crop_w=width,
        crop_h=height,
        scale=scale,
        out_w=width * scale,
        out_h=height * scale,
    )


def _snapshot(data: bytes, width: int = 5, height: int = 1) -> MapSnapshot:
    grid = MapGrid(
        width=width,
        height=height,
        data=data,
        resolution=0.05,
        min_x=0.0,
        min_y=0.0,
    )
    return MapSnapshot(grid=grid, robot=None, charger=None)


# ---------------------------------------------------------------------------
# _compute_room_cell_map: byte encoding coverage
# ---------------------------------------------------------------------------


def test_cell_map_raw_byte_range() -> None:
    """Bytes 10-59 (raw room cells) are decoded and mapped to pixel positions."""
    data = bytes([0, 0, 12, 0, 0])  # cell (0,2) = room 12
    snap = _snapshot(data, width=5, height=1)
    layout = _layout(5, 1)
    result = _compute_room_cell_map(snap, layout)
    assert 12 in result
    assert len(result[12]) > 0


def test_cell_map_cleaned_byte_range() -> None:
    """Bytes 60-127 (cleaned room cells, room_id = byte - 50) are decoded."""
    data = bytes([0, 0, 62, 0, 0])  # room_id = 62 - 50 = 12
    snap = _snapshot(data, width=5, height=1)
    layout = _layout(5, 1)
    result = _compute_room_cell_map(snap, layout)
    assert 12 in result


def test_cell_map_carpet_byte_range() -> None:
    """Bytes 147-196 (carpet/second-pass, room_id = 206 - byte) are decoded."""
    # byte 194 → room_id = 206 - 194 = 12
    data = bytes([0, 0, 194, 0, 0])
    snap = _snapshot(data, width=5, height=1)
    layout = _layout(5, 1)
    result = _compute_room_cell_map(snap, layout)
    assert 12 in result


def test_cell_map_carpet_boundary_147() -> None:
    """Byte 147 → room_id = 59 (boundary of the carpet range)."""
    data = bytes([147])
    snap = _snapshot(data, width=1, height=1)
    layout = _layout(1, 1)
    result = _compute_room_cell_map(snap, layout)
    assert 59 in result


def test_cell_map_carpet_boundary_196() -> None:
    """Byte 196 → room_id = 10 (other boundary of the carpet range)."""
    data = bytes([196])
    snap = _snapshot(data, width=1, height=1)
    layout = _layout(1, 1)
    result = _compute_room_cell_map(snap, layout)
    assert 10 in result


def test_cell_map_cleaned_boundary_127() -> None:
    """Byte 127 → room_id = 77 (upper boundary of the cleaned range)."""
    data = bytes([127])
    snap = _snapshot(data, width=1, height=1)
    layout = _layout(1, 1)
    result = _compute_room_cell_map(snap, layout)
    assert 77 in result


def test_cell_map_bytes_128_to_146_and_197_plus_ignored() -> None:
    """Bytes 128-146 and 197-254 are not room cells (APK GridMap.updateGlobalMap
    handles neither; see doc/MAP_DATA.md §4.2) — no room entries produced."""
    data = bytes([128, 146, 197, 253, 254])
    snap = _snapshot(data, width=5, height=1)
    layout = _layout(5, 1)
    result = _compute_room_cell_map(snap, layout)
    assert result == {}


def test_cell_map_non_room_bytes_ignored() -> None:
    """Bytes 0-9 and 255 produce no room cell entries."""
    data = bytes([0, 1, 2, 3, 9])
    snap = _snapshot(data, width=5, height=1)
    layout = _layout(5, 1)
    result = _compute_room_cell_map(snap, layout)
    assert result == {}


def test_cell_map_packed_grid_returns_empty() -> None:
    """Packed 2-bit grids (len < width*height) return empty dict."""
    data = bytes(6)  # 10x1 grid needs 10 bytes; 6 < 10
    snap = _snapshot(data, width=10, height=1)
    layout = _layout(10, 1)
    result = _compute_room_cell_map(snap, layout)
    assert result == {}


def test_cell_map_rle_spans_are_sorted() -> None:
    """RLE output has spans in ascending row order for each room."""
    # 3x3 grid; fill entire second row (idx 3,4,5) with room 12.
    data = bytearray(9)
    data[3] = 12
    data[4] = 12
    data[5] = 12
    snap = _snapshot(bytes(data), width=3, height=3)
    layout = _layout(3, 3, scale=2)
    result = _compute_room_cell_map(snap, layout)
    assert 12 in result
    rows = [span[0] for span in result[12]]
    assert rows == sorted(rows)


def test_cell_map_adjacent_cells_form_single_span() -> None:
    """Horizontally adjacent room cells become one RLE span."""
    data = bytes([12, 12, 12, 0, 0])  # three adjacent cells in one row
    snap = _snapshot(data, width=5, height=1)
    layout = _layout(5, 1, scale=1)
    result = _compute_room_cell_map(snap, layout)
    assert 12 in result
    # All three cells should collapse to a single span with run_len=3.
    spans = result[12]
    assert any(span[2] == 3 for span in spans)


# ---------------------------------------------------------------------------
# vacuum.extra_state_attributes
# ---------------------------------------------------------------------------


def _make_vacuum_entity() -> tuple[object, MagicMock]:
    """Return (KarcherVacuum, mock_coordinator) with minimal state.

    Overlay fields (robot_px/charger_px/cur_path_px/room_areas_m2) are projected
    by the coordinator now, so they default to empty here — the entity only reads
    them. _project_overlays itself is covered by the coordinator tests below.
    """
    from custom_components.karcher_home_robots.vacuum import KarcherVacuum

    coord = MagicMock()
    coord.device.device_id = "test_device"
    coord.rooms = []
    coord.map_snapshot = None
    coord.room_cell_map = {}
    coord.render_image_size = None
    coord.room_areas_m2 = {}
    coord.robot_px = None
    coord.charger_px = None
    coord.cur_path_px = []

    vacuum = KarcherVacuum.__new__(KarcherVacuum)
    vacuum.coordinator = coord
    vacuum._pref_entity_map_cache = None
    return vacuum, coord


# ---------------------------------------------------------------------------
# coordinator._project_overlays: world → pixel projection
# ---------------------------------------------------------------------------


def _make_coordinator() -> object:
    """Return a bare KarcherCoordinator carrying only the attributes _project_overlays reads."""
    from custom_components.karcher_home_robots.coordinator import KarcherCoordinator

    coord = KarcherCoordinator.__new__(KarcherCoordinator)
    coord.map_snapshot = None
    coord.render_layout = None
    coord.current_robot_pose = None
    coord._cur_path = []
    coord.cur_path_px = []
    coord._cur_path_px_base = []
    coord._cur_path_proj_idx = 0
    coord._cur_path_proj_layout = None
    coord.robot_px = None
    coord.charger_px = None
    return coord


def _project_world(wx: float, wy: float, layout: RenderLayout, grid: MapGrid) -> tuple[int, int]:
    """Reference world→pixel projection for assertions (independent of the SUT path)."""
    from custom_components.karcher_home_robots.map_render import world_to_pixel

    return world_to_pixel(
        wx, wy, layout, grid.width, grid.height, grid.resolution, grid.min_x, grid.min_y
    )


def test_project_overlays_robot_from_path_stream() -> None:
    """robot_px comes from current_robot_pose (path stream); charger_px from snapshot."""
    coord = _make_coordinator()
    grid = MapGrid(width=10, height=10, data=bytes(100), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(grid=grid, robot=None, charger=Pose(x=0.1, y=0.1))
    layout = RenderLayout(col0=0, row0=0, crop_w=10, crop_h=10, scale=2, out_w=20, out_h=20)

    coord.map_snapshot = snapshot
    coord.render_layout = layout
    coord.current_robot_pose = (0.25, 0.25, 1.0)
    coord._project_overlays()

    px, py = _project_world(0.25, 0.25, layout, grid)
    assert coord.robot_px == {"x": px, "y": py, "phi": 1.0}
    cx, cy = _project_world(0.1, 0.1, layout, grid)
    assert coord.charger_px == {"x": cx, "y": cy}


def test_project_overlays_robot_falls_back_to_snapshot_when_docked() -> None:
    """When current_robot_pose is None (docked), robot_px falls back to snapshot.robot."""
    coord = _make_coordinator()
    grid = MapGrid(width=10, height=10, data=bytes(100), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(grid=grid, robot=Pose(x=0.25, y=0.25, phi=1.5), charger=None)
    layout = RenderLayout(col0=0, row0=0, crop_w=10, crop_h=10, scale=2, out_w=20, out_h=20)

    coord.map_snapshot = snapshot
    coord.render_layout = layout
    coord.current_robot_pose = None  # docked — no live path stream
    coord._project_overlays()

    px, py = _project_world(0.25, 0.25, layout, grid)
    assert coord.robot_px is not None
    assert coord.robot_px["x"] == px and coord.robot_px["y"] == py
    assert coord.robot_px["phi"] == pytest.approx(1.5)
    assert coord.charger_px is None


def test_project_overlays_no_map_yields_defaults() -> None:
    """With no snapshot/layout, overlays project to safe empty defaults."""
    coord = _make_coordinator()
    coord.current_robot_pose = (0.25, 0.25, 1.0)
    coord._cur_path = [(0.25, 0.25, 1.0, 1)]
    coord._project_overlays()
    assert coord.robot_px is None
    assert coord.charger_px is None
    assert coord.cur_path_px == []


def test_project_overlays_decimates_and_keeps_last_point() -> None:
    """cur_path is decimated by step=3 but the final point is always included."""
    coord = _make_coordinator()
    grid = MapGrid(width=20, height=20, data=bytes(400), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(grid=grid, robot=None, charger=None)
    layout = RenderLayout(col0=0, row0=0, crop_w=20, crop_h=20, scale=2, out_w=40, out_h=40)

    # 5 points: indices 0 and 3 are kept by the step, index 4 (last) is force-included.
    raw = [(0.05 * i, 0.05 * i, 0.0, 1) for i in range(5)]
    coord.map_snapshot = snapshot
    coord.render_layout = layout
    coord._cur_path = raw
    coord._project_overlays()

    kept = [raw[0], raw[3], raw[4]]
    expected: list[int] = []
    for wx, wy, _phi, _flag in kept:
        px, py = _project_world(wx, wy, layout, grid)
        expected.extend([px, py])
    assert coord.cur_path_px == expected


def test_project_overlays_path_length_multiple_of_step_skips_force_include() -> None:
    """When len(cur_path) is an exact multiple of step, the last point is already
    covered by the strided loop, so the force-include block must not double it."""
    coord = _make_coordinator()
    grid = MapGrid(width=20, height=20, data=bytes(400), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(grid=grid, robot=None, charger=None)
    layout = RenderLayout(col0=0, row0=0, crop_w=20, crop_h=20, scale=2, out_w=40, out_h=40)

    # 6 points, step=3: indices 0 and 3 are kept; 6 % 3 == 0 so no force-include.
    raw = [(0.05 * i, 0.05 * i, 0.0, 1) for i in range(6)]
    coord.map_snapshot = snapshot
    coord.render_layout = layout
    coord._cur_path = raw
    coord._project_overlays()

    kept = [raw[0], raw[3]]
    expected: list[int] = []
    for wx, wy, _phi, _flag in kept:
        px, py = _project_world(wx, wy, layout, grid)
        expected.extend([px, py])
    assert coord.cur_path_px == expected


def test_project_overlays_reprojects_against_live_layout_after_shift() -> None:
    """A layout shift (explored grid grew) reprojects the whole path, not a stale cache.

    Locks the invariant that _project_overlays always uses the live layout: a
    future tail-append optimisation must not reintroduce mixed coordinate systems.
    """
    coord = _make_coordinator()
    grid = MapGrid(width=30, height=30, data=bytes(900), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(grid=grid, robot=None, charger=None)
    # 8 points: step=3 keeps indices 0, 3, 6; index 7 (last) is force-included.
    raw = [(0.05 * i, 0.05 * i, 0.0, 1) for i in range(8)]
    coord.map_snapshot = snapshot
    coord._cur_path = raw

    layout_a = RenderLayout(col0=0, row0=0, crop_w=30, crop_h=30, scale=2, out_w=60, out_h=60)
    coord.render_layout = layout_a
    coord._project_overlays()
    projected_a = list(coord.cur_path_px)

    # Map grew: crop origin and scale both shift.
    layout_b = RenderLayout(col0=5, row0=3, crop_w=30, crop_h=30, scale=3, out_w=90, out_h=90)
    coord.render_layout = layout_b
    coord._project_overlays()

    expected_b: list[int] = []
    for wx, wy, _phi, _flag in [raw[0], raw[3], raw[6], raw[7]]:
        px, py = _project_world(wx, wy, layout_b, grid)
        expected_b.extend([px, py])
    assert coord.cur_path_px == expected_b
    assert coord.cur_path_px != projected_a


def test_project_overlays_incremental_matches_full_reprojection() -> None:
    """Growing the path point-by-point yields the same cur_path_px as one full pass.

    Guards the incremental tail-append cache: each push projects only the newly
    appended points, but the result must be byte-identical to projecting the
    whole path at once against the same (unchanged) layout.
    """
    grid = MapGrid(width=40, height=40, data=bytes(1600), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(grid=grid, robot=None, charger=None)
    layout = RenderLayout(col0=0, row0=0, crop_w=40, crop_h=40, scale=2, out_w=80, out_h=80)
    raw = [(0.05 * (i % 30), 0.05 * (i % 25), 0.0, 1) for i in range(23)]

    # Incremental: extend the path in irregular batches, reprojecting each time.
    incr = _make_coordinator()
    incr.map_snapshot = snapshot
    incr.render_layout = layout
    for batch in (raw[0:1], raw[1:5], raw[5:6], raw[6:20], raw[20:23]):
        incr._cur_path = incr._cur_path + list(batch)
        incr._project_overlays()

    # Full: project the whole path in a single call.
    full = _make_coordinator()
    full.map_snapshot = snapshot
    full.render_layout = layout
    full._cur_path = list(raw)
    full._project_overlays()

    assert incr.cur_path_px == full.cur_path_px


def test_project_overlays_resets_cache_when_path_shrinks() -> None:
    """A path reset (clean start / dock) discards the cache instead of reusing stale offsets."""
    grid = MapGrid(width=40, height=40, data=bytes(1600), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(grid=grid, robot=None, charger=None)
    layout = RenderLayout(col0=0, row0=0, crop_w=40, crop_h=40, scale=2, out_w=80, out_h=80)

    coord = _make_coordinator()
    coord.map_snapshot = snapshot
    coord.render_layout = layout
    coord._cur_path = [(0.05 * i, 0.05 * i, 0.0, 1) for i in range(10)]
    coord._project_overlays()

    # Reset to a short fresh path under the same layout object.
    coord._cur_path = [(0.1, 0.1, 0.0, 1), (0.15, 0.15, 0.0, 1)]
    coord._project_overlays()

    expected: list[int] = []
    px, py = _project_world(0.1, 0.1, layout, grid)
    expected.extend([px, py])
    # len 2, step 3 → 2 % 3 != 0, last point force-included.
    px, py = _project_world(0.15, 0.15, layout, grid)
    expected.extend([px, py])
    assert coord.cur_path_px == expected


def test_vacuum_passes_through_coordinator_overlays() -> None:
    """The entity forwards the coordinator's projected overlays verbatim."""
    from custom_components.karcher_home_robots.vacuum import KarcherVacuum

    coord = MagicMock()
    coord.device.device_id = "test_device"
    coord.rooms = []
    coord.map_snapshot = None
    coord.room_cell_map = {}
    coord.render_image_size = None
    coord.room_areas_m2 = {}
    coord.robot_px = {"x": 1.0, "y": 2.0, "phi": 3.0}
    coord.charger_px = {"x": 4.0, "y": 5.0}
    coord.cur_path_px = [6, 7, 8, 9]
    coord.data = None

    vacuum = KarcherVacuum.__new__(KarcherVacuum)
    vacuum.coordinator = coord
    vacuum._pref_entity_map_cache = None

    attrs = vacuum.extra_state_attributes
    assert attrs["robot_px"] is coord.robot_px
    assert attrs["charger_px"] is coord.charger_px
    assert attrs["cur_path_px"] is coord.cur_path_px


def test_extra_state_attributes_status_label_locating() -> None:
    """status_label is 'Locating' when fault == 2108."""
    from custom_components.karcher_home_robots._types import DeviceProperties

    vacuum, coord = _make_vacuum_entity()
    coord.data = DeviceProperties(work_mode=1, status=0, charge_state=0, fault=2108)

    attrs = vacuum.extra_state_attributes
    assert attrs["status_label"] == "Locating"


def test_extra_state_attributes_status_label_none_when_no_fault() -> None:
    """status_label is None when fault is 0."""
    from custom_components.karcher_home_robots._types import DeviceProperties

    vacuum, coord = _make_vacuum_entity()
    coord.data = DeviceProperties(work_mode=1, status=0, charge_state=0, fault=0)

    attrs = vacuum.extra_state_attributes
    assert attrs["status_label"] is None


def test_extra_state_attributes_map_image_size() -> None:
    """map_image_size reflects render_image_size from coordinator."""
    from custom_components.karcher_home_robots.map_data import MapGrid, MapSnapshot
    from custom_components.karcher_home_robots.map_render import RenderLayout

    vacuum, coord = _make_vacuum_entity()

    grid = MapGrid(width=10, height=10, data=bytes(100), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(grid=grid, robot=None, charger=None)
    layout = RenderLayout(col0=0, row0=0, crop_w=10, crop_h=10, scale=2, out_w=20, out_h=20)

    coord.map_snapshot = snapshot
    coord.render_layout = layout
    coord.render_image_size = (20, 20, 2)

    attrs = vacuum.extra_state_attributes
    assert attrs["map_image_size"] == {"width": 20, "height": 20, "cell_size": 2}


def test_extra_state_attributes_room_map_includes_cells() -> None:
    """room_map attribute includes per-room cell spans from coordinator."""
    from custom_components.karcher_home_robots.map_data import MapGrid, MapSnapshot
    from custom_components.karcher_home_robots.map_render import RenderLayout

    vacuum, coord = _make_vacuum_entity()

    grid = MapGrid(width=10, height=10, data=bytes(100), resolution=0.05, min_x=0.0, min_y=0.0)
    room_info = RoomInfo(room_id=12, name="Hall", color_id=1, label_x=0.0, label_y=0.0)
    snapshot = MapSnapshot(grid=grid, robot=None, charger=None, rooms=[room_info])
    layout = RenderLayout(col0=0, row0=0, crop_w=10, crop_h=10, scale=2, out_w=20, out_h=20)

    room = MagicMock()
    room.room_id = 12
    room.name = "Hall"

    coord.map_snapshot = snapshot
    coord.render_layout = layout
    coord.render_image_size = (20, 20, 2)
    coord.rooms = [room]
    coord.room_cell_map = {12: [(10, 4, 3)]}

    attrs = vacuum.extra_state_attributes
    assert "12" in attrs["room_map"]
    assert attrs["room_map"]["12"]["cells"] == [(10, 4, 3)]
    assert attrs["room_map"]["12"]["color_id"] == 1


# ---------------------------------------------------------------------------
# coordinator._derive_map_state: per-room area (m²)
# ---------------------------------------------------------------------------


def test_derive_map_state_room_areas_m2() -> None:
    """room_areas_m2 = cell_count * resolution² per room, rounded to 0.1."""
    from custom_components.karcher_home_robots.coordinator import _derive_map_state

    # 3x2 grid (full-res, len == w*h): three cells of room 12, one of room 13.
    #   row 0: [12, 12, 0]
    #   row 1: [12, 13, 0]
    data = bytes([12, 12, 0, 12, 13, 0])
    grid = MapGrid(width=3, height=2, data=data, resolution=0.5, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(grid=grid, robot=None, charger=None)

    _layout_out, _cell_map, room_id_grid, areas = _derive_map_state(snapshot)

    assert room_id_grid is not None
    # cell_area = 0.5² = 0.25 m². room 12: 3 cells → 0.75 → 0.8; room 13: 1 cell → 0.2.
    assert areas[12] == pytest.approx(0.8)
    assert areas[13] == pytest.approx(0.2)
    assert 0 not in areas  # "no room" cells excluded
    # Areas key is the full set of room IDs present in the grid, not filtered by
    # coordinator.rooms — the entity filters at read time via .get(room_id).
    assert set(areas) == {12, 13}
