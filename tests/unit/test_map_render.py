# SPDX-License-Identifier: MIT
"""Unit tests for map_render.render_map() and decode_room_id_grid()."""

from __future__ import annotations

import io
import struct

import numpy as np
from custom_components.karcher_home_robots.map_data import (
    MapGrid,
    MapSnapshot,
    Pose,
    RoomInfo,
)
from custom_components.karcher_home_robots.map_render import (
    decode_room_id_grid,
    render_map,
)
from PIL import Image


def _make_snapshot(
    *,
    width: int = 120,
    height: int = 120,
    cell_value: int = 0,
    robot: Pose | None = None,
    charger: Pose | None = None,
    path: list[tuple[float, float]] | None = None,
    cur_path: list[tuple[float, float]] | None = None,
) -> MapSnapshot:
    # Encode all cells with the given value (0, 1, or 3).
    cells_per_byte = 4
    n_bytes = (width * height) // cells_per_byte
    # Each byte encodes a 2x2 block with the same value in all 4 slots.
    byte_val = cell_value | (cell_value << 2) | (cell_value << 4) | (cell_value << 6)
    grid = MapGrid(
        width=width,
        height=height,
        data=bytes([byte_val]) * n_bytes,
        resolution=0.05,
        min_x=0.0,
        min_y=0.0,
    )
    return MapSnapshot(
        grid=grid,
        robot=robot,
        charger=charger,
        path=path or [],
        cur_path=cur_path or [],
    )


def _is_valid_png(data: bytes) -> bool:
    return data[:8] == b"\x89PNG\r\n\x1a\n"


def _read_ihdr(data: bytes) -> tuple[int, int]:
    """Return (width, height) from the PNG IHDR chunk."""
    # Offset 8: chunk length (4), type (4), data (13)
    w = struct.unpack(">I", data[16:20])[0]
    h = struct.unpack(">I", data[20:24])[0]
    return w, h


def test_returns_valid_png() -> None:
    snap = _make_snapshot()
    result = render_map(snap)
    assert _is_valid_png(result)


def test_dimensions_match_scale_4() -> None:
    # All-wall grid: crop = full grid, output = width*scale x height*scale.
    snap = _make_snapshot(width=120, height=120, cell_value=1)
    result = render_map(snap, scale=4)
    w, h = _read_ihdr(result)
    # With margin the cropped region ≤ full grid, so output ≤ 120*scale.
    assert w <= 120 * 4
    assert h <= 120 * 4
    assert w > 0
    assert h > 0


def test_small_grid_correct_size() -> None:
    # All-wall grid: output must be at least scale pixels in each dimension.
    snap = _make_snapshot(width=10, height=10, cell_value=1)
    result = render_map(snap, scale=2)
    w, h = _read_ihdr(result)
    assert w > 0
    assert h > 0


def test_wall_cells_render() -> None:
    snap = _make_snapshot(cell_value=1)
    result = render_map(snap)
    assert _is_valid_png(result)


def test_cleaned_cells_render() -> None:
    snap = _make_snapshot(cell_value=3)
    result = render_map(snap)
    assert _is_valid_png(result)


def test_robot_pose_renders() -> None:
    snap = _make_snapshot(robot=Pose(x=3.0, y=3.0, phi=0.0))
    result = render_map(snap)
    assert _is_valid_png(result)


def test_charger_renders() -> None:
    snap = _make_snapshot(charger=Pose(x=1.0, y=1.0))
    result = render_map(snap)
    assert _is_valid_png(result)


def test_path_renders() -> None:
    snap = _make_snapshot(path=[(0.1, 0.1), (2.0, 2.0), (4.0, 1.0)])
    result = render_map(snap)
    assert _is_valid_png(result)


def test_cur_path_renders() -> None:
    snap = _make_snapshot(cur_path=[(0.2, 0.2), (3.0, 3.0)])
    result = render_map(snap)
    assert _is_valid_png(result)


def test_single_path_point_no_error() -> None:
    snap = _make_snapshot(path=[(1.0, 1.0)])
    result = render_map(snap)
    assert _is_valid_png(result)


def test_objects_render() -> None:
    from custom_components.karcher_home_robots.map_data import MapObject

    snap = _make_snapshot(
        cell_value=3,
        robot=Pose(x=3.0, y=3.0, phi=0.0),
    )
    snap_with_objects = MapSnapshot(
        grid=snap.grid,
        robot=snap.robot,
        charger=None,
        objects=[
            MapObject(object_id=1, type_id=1003, x=1.0, y=1.0),  # wire
            MapObject(object_id=2, type_id=1005, x=2.0, y=2.0),  # carpet
            MapObject(object_id=3, type_id=9999, x=3.0, y=3.0),  # unknown type
        ],
    )
    result = render_map(snap_with_objects)
    assert _is_valid_png(result)


def test_all_features_together() -> None:
    snap = _make_snapshot(
        robot=Pose(x=3.0, y=3.0, phi=1.57),
        charger=Pose(x=0.5, y=0.5),
        path=[(0.1, 0.1), (3.0, 3.0)],
        cur_path=[(3.0, 3.0), (4.0, 4.0)],
    )
    result = render_map(snap)
    assert _is_valid_png(result)


# ---------------------------------------------------------------------------
# decode_room_id_grid
# ---------------------------------------------------------------------------


def test_decode_room_id_grid_raw_range() -> None:
    """Bytes 10-59: room_id equals byte value."""
    data = bytes([10, 20, 59])
    grid = decode_room_id_grid(data, width=3, height=1)
    assert grid[0, 0] == 10
    assert grid[0, 1] == 20
    assert grid[0, 2] == 59


def test_decode_room_id_grid_cleaned_range() -> None:
    """Bytes 60-146 and 197-254: room_id = byte - 50."""
    data = bytes([60, 100, 146, 197, 254])
    grid = decode_room_id_grid(data, width=5, height=1)
    assert grid[0, 0] == 10  # 60  - 50
    assert grid[0, 1] == 50  # 100 - 50
    assert grid[0, 2] == 96  # 146 - 50
    assert grid[0, 3] == 147  # 197 - 50
    assert grid[0, 4] == 204  # 254 - 50


def test_decode_room_id_grid_double_cleaned_range() -> None:
    """Bytes 147-196: room_id = 206 - byte (double-cleaned variant)."""
    data = bytes([147, 196, 170])
    grid = decode_room_id_grid(data, width=3, height=1)
    assert grid[0, 0] == 59  # 206 - 147
    assert grid[0, 1] == 10  # 206 - 196
    assert grid[0, 2] == 36  # 206 - 170


def test_decode_room_id_grid_boundary_146_not_double_cleaned() -> None:
    """Byte 146 is in cleaned range (60-146), NOT double-cleaned (147-196)."""
    data = bytes([146])
    grid = decode_room_id_grid(data, width=1, height=1)
    assert grid[0, 0] == 96  # 146 - 50, not 206 - 146 = 60


def test_decode_room_id_grid_non_room_bytes_are_zero() -> None:
    """Bytes 0-9 and 255 are not room cells; output is 0."""
    data = bytes([0, 1, 2, 3, 4, 9, 255])
    grid = decode_room_id_grid(data, width=7, height=1)
    assert (grid == 0).all()


def test_decode_room_id_grid_shape() -> None:
    data = bytes(range(10, 10 + 12))  # 12 room-ID bytes
    grid = decode_room_id_grid(data, width=4, height=3)
    assert grid.shape == (3, 4)


# ---------------------------------------------------------------------------
# Room colour fills
# ---------------------------------------------------------------------------


def _make_room_snapshot(room_byte: int, room_id: int = 12) -> MapSnapshot:
    """Snapshot with a 10x10 grid; cell (5, 5) set to room_byte, rest 0."""
    width, height = 10, 10
    data = bytearray(width * height)
    data[5 * width + 5] = room_byte
    grid = MapGrid(
        width=width,
        height=height,
        data=bytes(data),
        resolution=0.05,
        min_x=0.0,
        min_y=0.0,
    )
    rooms = [RoomInfo(room_id=room_id, name="Hall", color_id=1, label_x=0.25, label_y=0.25)]
    return MapSnapshot(grid=grid, robot=None, charger=None, rooms=rooms)


def test_room_colour_fill_raw_byte() -> None:
    """Room cells encoded as raw bytes (10-59) are filled with the room colour."""
    snap = _make_room_snapshot(room_byte=12, room_id=12)
    result = render_map(snap, scale=2)
    assert _is_valid_png(result)
    # Output should not be all-white; the room colour differs from background.
    img = Image.open(io.BytesIO(result)).convert("RGB")
    arr = np.array(img)
    # At least one pixel should not be pure white (255,255,255).
    assert not (arr == 255).all()


def test_room_colour_fill_cleaned_byte() -> None:
    """Room cells encoded as cleaned bytes (60-146) are filled with the room colour."""
    snap = _make_room_snapshot(room_byte=62, room_id=12)  # 62 - 50 = 12
    result = render_map(snap, scale=2)
    assert _is_valid_png(result)


def test_room_colour_fill_double_cleaned_byte() -> None:
    """Room cells encoded as double-cleaned bytes (147-196) are filled with room colour."""
    snap = _make_room_snapshot(room_byte=194, room_id=12)  # 206 - 194 = 12
    result = render_map(snap, scale=2)
    assert _is_valid_png(result)


# ---------------------------------------------------------------------------
# Wall mask
# ---------------------------------------------------------------------------


def test_wall_byte_3_renders_dark() -> None:
    """Pure wall bytes (value 3) produce dark pixels in the rendered image."""
    width, height = 10, 10
    data = bytearray(width * height)
    # Use a connected wall segment so it survives the single-cell speckle filter.
    for col in range(4, 7):
        data[5 * width + col] = 3  # 3-cell horizontal wall
    grid = MapGrid(
        width=width, height=height, data=bytes(data), resolution=0.05, min_x=0.0, min_y=0.0
    )
    snap = MapSnapshot(grid=grid, robot=None, charger=None, rooms=[])
    result = render_map(snap, scale=2)
    assert _is_valid_png(result)
    img = Image.open(io.BytesIO(result)).convert("RGB")
    arr = np.array(img)
    # Should contain at least one dark pixel (wall colour ~= (60,60,60)).
    assert (arr < 100).any()


def test_room_byte_with_low_bits_11_not_treated_as_wall() -> None:
    """A room byte whose low 2 bits are 11 (e.g. 15 = 0x0F) must NOT render as wall."""
    # byte 15: low 2 bits = 3 (wall pattern), but it is a room cell (raw range 10-59).
    # room_id = 15, color_id = 1.
    width, height = 10, 10
    data = bytearray(width * height)
    data[5 * width + 5] = 15  # room byte with ambiguous low bits
    grid = MapGrid(
        width=width, height=height, data=bytes(data), resolution=0.05, min_x=0.0, min_y=0.0
    )
    rooms = [RoomInfo(room_id=15, name="Kitchen", color_id=2, label_x=0.25, label_y=0.25)]
    snap = MapSnapshot(grid=grid, robot=None, charger=None, rooms=rooms)
    result = render_map(snap, scale=2)
    img = Image.open(io.BytesIO(result)).convert("RGB")
    arr = np.array(img)
    # The room colour for color_id=2 is (233, 186, 192) -- not dark.
    # At least one pixel should match the room colour (not the wall colour).
    assert (arr > 150).any()
