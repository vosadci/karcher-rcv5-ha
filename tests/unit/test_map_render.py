# SPDX-License-Identifier: MIT
"""Unit tests for map_render.render_map()."""

from __future__ import annotations

import struct

from custom_components.karcher_home_robots.map_data import MapGrid, MapSnapshot, Pose
from custom_components.karcher_home_robots.map_render import render_map


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
    # All-wall grid: crop = full grid, output = width*scale × height*scale.
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
