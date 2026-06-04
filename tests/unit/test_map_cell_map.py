# SPDX-License-Identifier: MIT
"""Unit tests for map_render.compute_room_cell_map and vacuum extra_state_attributes."""

from __future__ import annotations

from unittest.mock import MagicMock

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
    """Bytes 60-146 (cleaned room cells, room_id = byte - 50) are decoded."""
    data = bytes([0, 0, 62, 0, 0])  # room_id = 62 - 50 = 12
    snap = _snapshot(data, width=5, height=1)
    layout = _layout(5, 1)
    result = _compute_room_cell_map(snap, layout)
    assert 12 in result


def test_cell_map_double_cleaned_byte_range() -> None:
    """Bytes 147-196 (double-cleaned, room_id = 206 - byte) are decoded."""
    # byte 194 → room_id = 206 - 194 = 12
    data = bytes([0, 0, 194, 0, 0])
    snap = _snapshot(data, width=5, height=1)
    layout = _layout(5, 1)
    result = _compute_room_cell_map(snap, layout)
    assert 12 in result


def test_cell_map_double_cleaned_boundary_147() -> None:
    """Byte 147 → room_id = 59 (boundary of double-cleaned range)."""
    data = bytes([147])
    snap = _snapshot(data, width=1, height=1)
    layout = _layout(1, 1)
    result = _compute_room_cell_map(snap, layout)
    assert 59 in result


def test_cell_map_double_cleaned_boundary_196() -> None:
    """Byte 196 → room_id = 10 (other boundary of double-cleaned range)."""
    data = bytes([196])
    snap = _snapshot(data, width=1, height=1)
    layout = _layout(1, 1)
    result = _compute_room_cell_map(snap, layout)
    assert 10 in result


def test_cell_map_byte_146_is_cleaned_not_double_cleaned() -> None:
    """Byte 146 → room_id = 96 (cleaned range), NOT double-cleaned (60)."""
    data = bytes([146])
    snap = _snapshot(data, width=1, height=1)
    layout = _layout(1, 1)
    result = _compute_room_cell_map(snap, layout)
    assert 96 in result
    assert 60 not in result


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
    """Return (KarcherVacuum, mock_coordinator) with minimal state."""
    from custom_components.karcher_home_robots.vacuum import KarcherVacuum

    coord = MagicMock()
    coord.device.device_id = "test_device"
    coord.rooms = []
    coord.map_snapshot = None
    coord.room_cell_map = {}
    coord.render_image_size = None
    coord.render_layout = None
    coord.current_robot_pose = None

    vacuum = KarcherVacuum.__new__(KarcherVacuum)
    vacuum.coordinator = coord
    return vacuum, coord


def test_extra_state_attributes_no_map() -> None:
    """extra_state_attributes returns safe defaults when no map is available."""
    vacuum, _ = _make_vacuum_entity()
    attrs = vacuum.extra_state_attributes
    assert attrs["rooms"] == {}
    assert attrs["room_map"] == {}
    assert attrs["map_image_size"] is None
    assert attrs["robot_px"] is None
    assert attrs["charger_px"] is None


def test_extra_state_attributes_with_map_and_robot() -> None:
    """robot_px comes from current_robot_pose (path stream); charger_px from snapshot."""
    from custom_components.karcher_home_robots.map_data import MapGrid, MapSnapshot
    from custom_components.karcher_home_robots.map_render import RenderLayout

    vacuum, coord = _make_vacuum_entity()

    grid = MapGrid(width=10, height=10, data=bytes(100), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(
        grid=grid,
        robot=None,
        charger=Pose(x=0.1, y=0.1),
    )
    layout = RenderLayout(col0=0, row0=0, crop_w=10, crop_h=10, scale=2, out_w=20, out_h=20)

    coord.map_snapshot = snapshot
    coord.render_layout = layout
    coord.render_image_size = (20, 20, 2)
    coord.room_cell_map = {}
    coord.current_robot_pose = (0.25, 0.25, 1.0)

    attrs = vacuum.extra_state_attributes

    robot_px = attrs["robot_px"]
    assert robot_px is not None
    assert "x" in robot_px and "y" in robot_px
    assert robot_px["phi"] == 1.0

    charger_px = attrs["charger_px"]
    assert charger_px is not None
    assert "x" in charger_px and "y" in charger_px


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
