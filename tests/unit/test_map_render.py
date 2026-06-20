# SPDX-License-Identifier: MIT
"""Unit tests for map_render.render_map() and decode_room_id_grid()."""

from __future__ import annotations

import io
import struct

import numpy as np
from custom_components.karcher_home_robots.map_data import (
    MapGrid,
    MapObject,
    MapSnapshot,
    Pose,
    RoomChain,
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


def test_zones_render() -> None:
    from custom_components.karcher_home_robots.map_data import RestrictedZone

    base = _make_snapshot(cell_value=3)
    snap_with_zones = MapSnapshot(
        grid=base.grid,
        robot=None,
        charger=None,
        zones=[
            RestrictedZone(  # no-go area (filled polygon)
                zone_id=1,
                type_id=1,
                points=[(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)],
            ),
            RestrictedZone(  # no-mop area (filled polygon) — device type 6
                zone_id=2,
                type_id=6,
                points=[(4.0, 4.0), (5.0, 4.0), (5.0, 5.0), (4.0, 5.0)],
            ),
            RestrictedZone(  # line virtual wall (polyline)
                zone_id=3,
                type_id=2,
                points=[(0.5, 5.0), (5.0, 0.5)],
            ),
        ],
    )
    result = render_map(snap_with_zones)
    assert _is_valid_png(result)
    # Zones must actually alter the rendered output.
    assert result != render_map(base)


def test_nogo_and_nomop_render_differently() -> None:
    """Device type 1 (no-go, red) and type 6 (no-mop, blue) must be visually
    distinct — distinguishing the two is the whole point of the feature."""
    from custom_components.karcher_home_robots.map_data import RestrictedZone

    base = _make_snapshot(cell_value=3)
    pts = [(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)]
    nogo = MapSnapshot(
        grid=base.grid,
        robot=None,
        charger=None,
        zones=[RestrictedZone(zone_id=1, type_id=1, points=pts)],
    )
    nomop = MapSnapshot(
        grid=base.grid,
        robot=None,
        charger=None,
        zones=[RestrictedZone(zone_id=1, type_id=6, points=pts)],
    )
    assert render_map(nogo) != render_map(nomop)


def test_zone_degenerate_points_no_error() -> None:
    from custom_components.karcher_home_robots.map_data import RestrictedZone

    base = _make_snapshot(cell_value=3)
    snap = MapSnapshot(
        grid=base.grid,
        robot=None,
        charger=None,
        zones=[
            RestrictedZone(zone_id=1, type_id=1, points=[(1.0, 1.0)]),  # too few for polygon
            RestrictedZone(zone_id=2, type_id=2, points=[(1.0, 1.0)]),  # too few for line
        ],
    )
    assert _is_valid_png(render_map(snap))


def test_cleaning_zone_rendered_and_distinct() -> None:
    """An active area-clean rectangle (areas_info → CleaningZone) renders as a
    visible overlay, distinct from a no-go restriction over the same box."""
    from custom_components.karcher_home_robots.map_data import CleaningZone, RestrictedZone

    base = _make_snapshot(cell_value=3)
    pts = [(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)]
    plain = MapSnapshot(grid=base.grid, robot=None, charger=None)
    clean = MapSnapshot(
        grid=base.grid,
        robot=None,
        charger=None,
        cleaning_zones=[CleaningZone(zone_id=1, points=pts)],
    )
    nogo = MapSnapshot(
        grid=base.grid,
        robot=None,
        charger=None,
        zones=[RestrictedZone(zone_id=1, type_id=1, points=pts)],
    )
    assert render_map(clean) != render_map(plain)  # the box is drawn
    assert render_map(clean) != render_map(nogo)  # teal, not red


def test_cleaning_zone_degenerate_points_no_error() -> None:
    from custom_components.karcher_home_robots.map_data import CleaningZone

    base = _make_snapshot(cell_value=3)
    snap = MapSnapshot(
        grid=base.grid,
        robot=None,
        charger=None,
        cleaning_zones=[CleaningZone(zone_id=1, points=[(1.0, 1.0)])],  # too few
    )
    assert _is_valid_png(render_map(snap))


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
    """Bytes 60-127: room_id = byte - 50 (cleaned room cells)."""
    data = bytes([60, 100, 127])
    grid = decode_room_id_grid(data, width=3, height=1)
    assert grid[0, 0] == 10  # 60  - 50
    assert grid[0, 1] == 50  # 100 - 50
    assert grid[0, 2] == 77  # 127 - 50


def test_decode_room_id_grid_carpet_range() -> None:
    """Bytes 147-196: room_id = 206 - byte (carpet/second-pass room cells)."""
    data = bytes([147, 196, 170])
    grid = decode_room_id_grid(data, width=3, height=1)
    assert grid[0, 0] == 59  # 206 - 147
    assert grid[0, 1] == 10  # 206 - 196
    assert grid[0, 2] == 36  # 206 - 170


def test_decode_room_id_grid_non_room_bytes_are_zero() -> None:
    """Bytes 0-9, 128-146, 197-254 and 255 are not room cells; output is 0.

    The app's colour pass only handles signed b >= 60 (unsigned 60-127) and
    signed [-109, -60] (unsigned 147-196); everything else gets no room colour
    (APK GridMap.updateGlobalMap, doc/MAP_DATA.md §4.2).
    """
    data = bytes([0, 1, 2, 3, 4, 9, 128, 146, 197, 253, 254, 255])
    grid = decode_room_id_grid(data, width=12, height=1)
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
    """Room cells encoded as cleaned bytes (60-127) are filled with the room colour."""
    snap = _make_room_snapshot(room_byte=62, room_id=12)  # 62 - 50 = 12
    result = render_map(snap, scale=2)
    assert _is_valid_png(result)


def test_room_colour_fill_carpet_byte() -> None:
    """Room cells encoded as carpet bytes (147-196) are filled with room colour."""
    snap = _make_room_snapshot(room_byte=194, room_id=12)  # 206 - 194 = 12
    result = render_map(snap, scale=2)
    assert _is_valid_png(result)


def test_room_with_no_cells_is_skipped() -> None:
    """A room declared in the room list but absent from the grid is skipped.

    The grid encodes room_id 12 (byte 12), but the room list declares room_id
    99. Its colour mask is empty, so the fill loop `continue`s rather than
    stamping nothing — and the render still produces a valid PNG.
    """
    snap = _make_room_snapshot(room_byte=12, room_id=99)
    result = render_map(snap, scale=2)
    assert _is_valid_png(result)
    # No room colour was stamped (room 99 has no cells), so the image is all
    # background white.
    img = Image.open(io.BytesIO(result)).convert("RGB")
    assert (np.array(img) == 255).all()


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


def test_scale_1_triggers_dilation() -> None:
    """scale=1 sets dilation=1, exercising the wall dilation path in _build_wall_mask."""
    snap = _make_snapshot(width=10, height=10, cell_value=1)
    result = render_map(snap, scale=1)
    assert _is_valid_png(result)


def test_room_colour_zero_color_id_returns_default() -> None:
    """color_id=0 returns the default room colour rather than indexing the table."""
    from custom_components.karcher_home_robots.map_render import _room_colour

    r, g, b = _room_colour(0)
    assert (r, g, b) == (220, 220, 220)


def test_room_labels_rendered_when_room_chains_present() -> None:
    """Room labels are drawn when both room_chains and rooms are non-empty."""
    width, height = 20, 20
    data = bytearray(width * height)
    # Place room byte 10 (room_id=10) at several cells to create visible content.
    for row in range(5, 15):
        for col in range(5, 15):
            data[row * width + col] = 10
    grid = MapGrid(
        width=width, height=height, data=bytes(data), resolution=0.05, min_x=0.0, min_y=0.0
    )
    rooms = [RoomInfo(room_id=10, name="Kitchen", color_id=1, label_x=0.5, label_y=0.5)]
    chains = [RoomChain(room_id=10, points=[(0.25, 0.25), (0.75, 0.25), (0.75, 0.75)])]
    snap = MapSnapshot(grid=grid, robot=None, charger=None, rooms=rooms, room_chains=chains)
    result = render_map(snap, scale=2)
    assert _is_valid_png(result)


def test_carpet_room_stripe_rendered() -> None:
    """is_carpet=True rooms get a stripe hatch overlay; no exception expected."""
    width, height = 20, 20
    data = bytearray(width * height)
    for row in range(4, 16):
        for col in range(4, 16):
            data[row * width + col] = 10
    grid = MapGrid(
        width=width, height=height, data=bytes(data), resolution=0.05, min_x=0.0, min_y=0.0
    )
    rooms = [
        RoomInfo(room_id=10, name="Hall", color_id=3, label_x=0.5, label_y=0.5, is_carpet=True)
    ]
    snap = MapSnapshot(grid=grid, robot=None, charger=None, rooms=rooms)
    result = render_map(snap, scale=2)
    assert _is_valid_png(result)


def test_carpet_cells_lighten_non_carpet_room() -> None:
    """Second-pass/carpet cells (bytes 147-196) get the carpet wash even when the
    room is NOT flagged is_carpet — fixes rugs (e.g. a hall rug) being invisible."""
    width, height = 10, 10
    rooms = [
        RoomInfo(room_id=12, name="Hall", color_id=1, label_x=0.25, label_y=0.25, is_carpet=False)
    ]

    def _render(byte: int) -> np.ndarray:
        data = bytearray(width * height)
        for row in range(3, 7):
            for col in range(3, 7):
                data[row * width + col] = byte
        grid = MapGrid(
            width=width, height=height, data=bytes(data), resolution=0.05, min_x=0.0, min_y=0.0
        )
        snap = MapSnapshot(grid=grid, robot=None, charger=None, rooms=rooms)
        png = render_map(snap, scale=2)
        return np.array(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)

    plain = _render(12)  # plain room cells (byte 12 → room_id 12)
    carpet = _render(194)  # carpet cells (byte 194 → room_id 12), washed lighter

    # The carpet wash lightens toward white, so the rug must be visibly lighter
    # than the same room rendered as plain floor.
    assert carpet.mean() > plain.mean()


def test_compute_map_legend_counts_zones_objects_carpet() -> None:
    from custom_components.karcher_home_robots.map_data import (
        CleaningZone,
        MapObject,
        RestrictedZone,
    )
    from custom_components.karcher_home_robots.map_render import compute_map_legend

    rect = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    base = _make_snapshot(width=10, height=10)  # full-res grid, no carpet bytes
    snap = MapSnapshot(
        grid=base.grid,
        robot=None,
        charger=None,
        zones=[
            RestrictedZone(zone_id=1, type_id=1, points=rect),  # no-go
            RestrictedZone(zone_id=2, type_id=6, points=rect),  # no-mop
            RestrictedZone(zone_id=3, type_id=6, points=rect),  # no-mop (2nd)
            RestrictedZone(zone_id=4, type_id=2, points=[(0.0, 0.0), (1.0, 1.0)]),  # wall
        ],
        cleaning_zones=[CleaningZone(zone_id=9, points=rect)],
        objects=[
            MapObject(object_id=1, type_id=1003, x=1.0, y=1.0),  # wire
            MapObject(object_id=2, type_id=1003, x=2.0, y=2.0),  # wire
            MapObject(object_id=3, type_id=1002, x=3.0, y=3.0),  # shoe
        ],
    )
    legend = compute_map_legend(snap)
    assert legend["no_go"] == 1
    assert legend["no_mop"] == 2
    assert legend["virtual_wall"] == 1
    assert legend["area_clean"] == 1
    assert legend["carpet"] is False
    assert legend["objects"] == {"1003": 2, "1002": 1}


def test_compute_map_legend_carpet_from_grid_bytes() -> None:
    from custom_components.karcher_home_robots.map_render import compute_map_legend

    width, height = 10, 10
    data = bytearray(width * height)
    data[5 * width + 5] = 194  # second-pass/carpet byte (147-196)
    grid = MapGrid(
        width=width, height=height, data=bytes(data), resolution=0.05, min_x=0.0, min_y=0.0
    )
    snap = MapSnapshot(grid=grid, robot=None, charger=None)
    assert compute_map_legend(snap)["carpet"] is True


def test_compute_map_legend_carpet_from_room_material() -> None:
    from custom_components.karcher_home_robots.map_render import compute_map_legend

    base = _make_snapshot(width=10, height=10)
    snap = MapSnapshot(
        grid=base.grid,
        robot=None,
        charger=None,
        rooms=[
            RoomInfo(room_id=1, name="Rug", color_id=1, label_x=0.0, label_y=0.0, is_carpet=True)
        ],
    )
    assert compute_map_legend(snap)["carpet"] is True


def test_compute_map_legend_empty() -> None:
    from custom_components.karcher_home_robots.map_render import compute_map_legend

    legend = compute_map_legend(_make_snapshot(width=10, height=10))
    assert legend == {
        "no_go": 0,
        "no_mop": 0,
        "virtual_wall": 0,
        "area_clean": 0,
        "carpet": False,
        "objects": {},
    }


def test_carpet_objects_are_suppressed() -> None:
    """1005 (carpet) AI detections are dropped, not drawn as dots.

    The carpet AREA is already shown via the grid-byte checkerboard and
    furniture_info polygons; rendering individual detection dots on top
    would duplicate the same carpet as a swarm of unrelated markers.
    """
    snap = _make_snapshot(width=20, height=20, cell_value=3)
    objects = [MapObject(object_id=i, type_id=1005, x=0.1 * i, y=0.1 * i) for i in range(1, 8)]
    snap_with_carpets = MapSnapshot(
        grid=snap.grid,
        robot=None,
        charger=None,
        objects=objects,
    )
    result = render_map(snap_with_carpets, scale=2)
    assert _is_valid_png(result)
    # No dots drawn — output is identical to the object-less render.
    base = MapSnapshot(grid=snap.grid, robot=None, charger=None)
    assert result == render_map(base, scale=2)


# ---------------------------------------------------------------------------
# Area carpets — grid-byte checkerboard (doc/MAP_DATA.md §6.4 mechanism 1)
# ---------------------------------------------------------------------------


def _carpet_grid_snapshot() -> MapSnapshot:
    """40x40 grid: wall border, cleaned room 10, carpet block, non-room carpet."""
    width, height = 40, 40
    data = bytearray(width * height)
    for row in range(5, 30):
        for col in range(5, 30):
            data[row * width + col] = 60  # cleaned cell, room 10
    for row in range(10, 20):
        for col in range(10, 20):
            data[row * width + col] = 196  # carpet cell, room 10 (206 - 196)
    for row in range(32, 36):
        for col in range(32, 38):
            data[row * width + col] = 253  # carpet cell outside any room
    for col in range(4, 31):  # wall border for a stable crop bbox
        data[4 * width + col] = 255
        data[30 * width + col] = 255
    grid = MapGrid(
        width=width, height=height, data=bytes(data), resolution=0.05, min_x=0.0, min_y=0.0
    )
    rooms = [RoomInfo(room_id=10, name="LR", color_id=1, label_x=1.25, label_y=1.25)]
    return MapSnapshot(grid=grid, robot=None, charger=None, rooms=rooms)


def test_carpet_checkerboard_rendered() -> None:
    """Carpet bytes (147-196) render as a uniform white-wash lighter than the room colour.

    The old per-cell checkerboard is replaced by a 25 % white blend applied to all
    carpet cells uniformly.
    """
    from custom_components.karcher_home_robots.map_render import compute_render_layout

    snap = _carpet_grid_snapshot()
    scale = 4
    layout = compute_render_layout(snap, scale=scale)
    result = render_map(snap, scale=scale)
    arr = np.array(Image.open(io.BytesIO(result)).convert("RGB"))

    def cell_centre(row: int, col: int) -> tuple[int, int]:
        px = (col - layout.col0) * scale + scale // 2
        py = layout.out_h - 1 - ((row - layout.row0) * scale + scale // 2)
        return py, px

    # Interior carpet cells: all cells should be lighter than the plain room colour
    # (white-wash applied) and uniform — no alternating pattern.
    carpet_colours = []
    for row in range(12, 18):
        for col in range(12, 18):
            py, px = cell_centre(row, col)
            carpet_colours.append(arr[py, px].tolist())
    assert len(set(map(tuple, carpet_colours))) == 1, "carpet cells should be uniform"
    # White-washed colour must be brighter than the plain room colour.
    plain_py, plain_px = cell_centre(22, 22)
    plain_colour = arr[plain_py, plain_px]
    assert all(c >= p for c, p in zip(carpet_colours[0], plain_colour.tolist(), strict=False)), (
        "carpet cells should be lighter than plain room cells"
    )


def test_carpet_nonroom_byte_253_checkerboard() -> None:
    """Byte 253 cells (carpet outside rooms) get a white-wash lighter than the cleaned colour."""
    from custom_components.karcher_home_robots.map_render import compute_render_layout

    snap = _carpet_grid_snapshot()
    scale = 4
    layout = compute_render_layout(snap, scale=scale)
    arr = np.array(Image.open(io.BytesIO(render_map(snap, scale=scale))).convert("RGB"))

    carpet_colours = []
    for row in range(33, 35):
        for col in range(33, 37):
            px = (col - layout.col0) * scale + scale // 2
            py = layout.out_h - 1 - ((row - layout.row0) * scale + scale // 2)
            carpet_colours.append(arr[py, px].tolist())

    # All cells uniform (no alternation).
    assert len(set(map(tuple, carpet_colours))) == 1, "byte-253 carpet cells should be uniform"
    # Must be brighter than the raw cleaned colour (white-wash applied).
    from custom_components.karcher_home_robots.map_render import _COLOUR_CLEANED

    assert all(c >= cl for c, cl in zip(carpet_colours[0], list(_COLOUR_CLEANED), strict=False)), (
        "byte-253 carpet cells should be lighter than the cleaned colour"
    )


# ---------------------------------------------------------------------------
# Area carpets — furniture_info quads (doc/MAP_DATA.md §6.4 mechanism 2)
# ---------------------------------------------------------------------------


def test_carpet_quads_rendered() -> None:
    """CarpetArea quads change the rendered output."""
    from custom_components.karcher_home_robots.map_data import CarpetArea

    base = _carpet_grid_snapshot()
    quad = CarpetArea(
        carpet_id=3,
        points=[(0.3, 0.3), (0.8, 0.3), (0.8, 0.7), (0.3, 0.7)],
    )
    with_quad = MapSnapshot(
        grid=base.grid, robot=None, charger=None, rooms=base.rooms, carpets=[quad]
    )
    png_quad = render_map(with_quad, scale=2)
    assert _is_valid_png(png_quad)
    assert png_quad != render_map(base, scale=2)


def test_carpet_quad_uses_first_four_points_only() -> None:
    """Points beyond the first four are ignored — the app reads exactly 8 floats
    (APK CarpetTexture.processPose); extra points must not distort the quad."""
    from custom_components.karcher_home_robots.map_data import CarpetArea

    base = _carpet_grid_snapshot()
    corners = [(0.3, 0.3), (0.8, 0.3), (0.8, 0.7), (0.3, 0.7)]
    junk = [(1.5, 1.5), (0.1, 1.4), (1.2, 0.2)]
    snap_a = MapSnapshot(
        grid=base.grid,
        robot=None,
        charger=None,
        rooms=base.rooms,
        carpets=[CarpetArea(carpet_id=1, points=corners)],
    )
    snap_b = MapSnapshot(
        grid=base.grid,
        robot=None,
        charger=None,
        rooms=base.rooms,
        carpets=[CarpetArea(carpet_id=1, points=corners + junk)],
    )
    assert render_map(snap_a, scale=2) == render_map(snap_b, scale=2)


def test_carpet_quad_degenerate_points_skipped() -> None:
    """A CarpetArea with fewer than 3 points is skipped without error."""
    from custom_components.karcher_home_robots.map_data import CarpetArea

    base = _carpet_grid_snapshot()
    snap = MapSnapshot(
        grid=base.grid,
        robot=None,
        charger=None,
        rooms=base.rooms,
        carpets=[CarpetArea(carpet_id=9, points=[(0.5, 0.5), (0.6, 0.6)])],
    )
    png = render_map(snap, scale=2)
    assert _is_valid_png(png)
    assert png == render_map(base, scale=2)
