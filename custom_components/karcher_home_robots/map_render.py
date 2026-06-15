# SPDX-License-Identifier: MIT
"""Render a MapSnapshot to PNG bytes using Pillow + numpy.

Pure function — no I/O, no HA imports. Called in an executor from
KarcherMapImage.async_image(). Pillow and numpy are HA core dependencies.

Rendering pipeline:
  1. Decode cell grid → numpy array.
  2. Crop to content bounding box + margin.
  3. Colour-fill cells at SUPERSAMPLE x output scale.
  4. Draw AI object markers at high res.
  5. Downsample with LANCZOS for anti-aliased output.

Paths, the robot icon, room labels, and the charger are NOT rendered here —
the Lovelace card draws them on its canvas overlay from the cur_path_px /
robot_px / charger_px attributes.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from .map_data import CarpetArea, MapSnapshot, RoomInfo

_LOGGER = logging.getLogger(__name__)

# Cell type values from the map grid encoding (GridMap.java, PositionInfo.java).
# Raw bytes masked with & 0x3: 0=free, 1=cleaned, 2=deep-cleaned, 3=wall (0xFF&3).
_CELL_WALL = 3
_CELL_CLEANED = 1
_CELL_DEEP_CLEANED = 2

# Room-byte range bounds (doc/MAP_DATA.md §4.2, verified against the signed-byte
# branches of APK GridMap.updateGlobalMap, 2026-06-12).
_ROOM_BYTE_MIN = 10  # raw bytes below this are free/cleaned/wall cells
_ROOM_RAW_HI = 59  # unvisited room cells: 10..59, room_id = byte
_ROOM_CLN_LO = 60  # cleaned room cells: 60..127 (signed b >= 60), room_id = byte - 50
_ROOM_CLN_HI = 127
# Bytes 147-196 (signed -109..-60): room cell with carpet/second-pass marking,
# room_id = 206 - byte. The app renders these as a white-on-room-colour
# checkerboard — this is how area carpets (rugs) appear on the map.
_ROOM_DBL_LO = 147
_ROOM_DBL_HI = 196
# Byte 253 (signed -3): carpet/second-pass cell outside any room — checkerboard
# white over the cleaned-area colour.
_CARPET_NONROOM_BYTE = 253

# Colours matched to the Kärcher app aesthetic.
_COLOUR_BG = (255, 255, 255)  # white canvas / free space
_COLOUR_CLEANED = (213, 240, 232)  # app: #D5F0E8 light cyan cleaned area
_COLOUR_WALL = (90, 90, 90)  # dark grey wall

# Room colour palette from ROOM_COLOR[] in GridMap.java (APK-verified 2026-05-08).
# Index = (color_id - 1) % 5  →  colour.
_ROOM_COLOR_TABLE: list[tuple[int, int, int]] = [
    (201, 220, 210),  # color_id 1 — teal-green  (#c9dcd2, INT_COVER)
    (233, 186, 192),  # color_id 2 — pink        (#e9bac0)
    (232, 231, 227),  # color_id 3 — off-white   (#e8e7e3)
    (189, 221, 224),  # color_id 4 — light blue  (#bddde0)
    (183, 183, 183),  # color_id 5 — grey        (#b7b7b7)
]
_ROOM_COLOUR_DEFAULT = (220, 220, 220)


def _room_colour(color_id: int) -> tuple[int, int, int]:
    if color_id < 1:
        return _ROOM_COLOUR_DEFAULT
    return _ROOM_COLOR_TABLE[(color_id - 1) % len(_ROOM_COLOR_TABLE)]


# AI object type IDs (AiObjectType.java) → (fill_colour, label).
# Only types the app surfaces to the user are included.
_OBJECT_TYPES: dict[int, tuple[tuple[int, int, int], str]] = {
    1001: ((220, 120, 60), "sock"),
    1002: ((180, 100, 40), "shoe"),
    1003: ((230, 60, 60), "wire"),
    1005: ((100, 160, 100), "carpet"),
    1007: ((160, 100, 200), "dog"),
    1006: ((160, 100, 200), "cat"),
    1011: ((200, 60, 60), "!"),  # pet waste
    1017: ((80, 140, 200), "scale"),
    1038: ((120, 120, 120), "chair"),
}

# Render at SUPERSAMPLE x the requested scale, then downsample.
_SUPERSAMPLE = 3

# Output scale: pixels per grid cell in the final PNG.
# Used by both render_map and compute_render_layout — must stay in sync with
# image.py (render_map) and coordinator.py (_derive_map_state / compute_render_layout).
_DEFAULT_SCALE = 2

_MIN_POLYGON_PTS = 3

# Margin around the content bounding box, in grid cells.
_MARGIN_CELLS = 10


@dataclass(frozen=True)
class RenderLayout:
    """Crop and scale parameters for one render call."""

    col0: int
    row0: int
    crop_w: int
    crop_h: int
    scale: int
    out_w: int
    out_h: int


def compute_render_layout(snapshot: MapSnapshot, *, scale: int = _DEFAULT_SCALE) -> RenderLayout:
    """Compute crop/scale layout without rendering the image."""
    grid = snapshot.grid
    _, col0, row0, crop_h, crop_w = _crop_cells(grid.data, grid.width, grid.height)
    return RenderLayout(
        col0=col0,
        row0=row0,
        crop_w=crop_w,
        crop_h=crop_h,
        scale=scale,
        out_w=crop_w * scale,
        out_h=crop_h * scale,
    )


def world_to_pixel(
    x: float,
    y: float,
    layout: RenderLayout,
    grid_width: int,
    grid_height: int,
    resolution: float,
    min_x: float,
    min_y: float,
) -> tuple[int, int]:
    """Convert world coordinates to pixel coordinates in the rendered image.

    Matches render_map's w2p: cells are centred within their pixel block, which
    means an offset of scale//2 on both axes after the supersampled render is
    downsampled to the output scale.
    """
    col = int((x - min_x) / resolution)
    row = int((y - min_y) / resolution)
    col = max(0, min(grid_width - 1, col))
    row = max(0, min(grid_height - 1, row))
    half = layout.scale // 2
    px = (col - layout.col0) * layout.scale + half
    py = layout.out_h - 1 - ((row - layout.row0) * layout.scale + half)
    return px, py


def render_map(snapshot: MapSnapshot, *, scale: int = _DEFAULT_SCALE) -> bytes:
    """Return PNG bytes for the given MapSnapshot."""
    grid = snapshot.grid
    ss = scale * _SUPERSAMPLE

    cells, col0, row0, crop_h, crop_w = _crop_cells(grid.data, grid.width, grid.height)

    img_h = crop_h * ss

    def w2p(x: float, y: float) -> tuple[int, int]:
        col = int((x - grid.min_x) / grid.resolution)
        row = int((y - grid.min_y) / grid.resolution)
        col = max(0, min(grid.width - 1, col))
        row = max(0, min(grid.height - 1, row))
        px = (col - col0) * ss + ss // 2
        # Flip Y: cell row 0 = world min_y = image bottom.
        py = img_h - 1 - ((row - row0) * ss + ss // 2)
        return px, py

    # Build image: white background → room fills → wall overlay.
    img = _build_base_image(
        cells,
        ss,
        snapshot.rooms,
        w2p,
        grid.data,
        grid.width,
        grid.height,
        col0,
        row0,
        dilation=max(0, 2 - scale),
    )

    # Area carpets (furniture_info type 1550) — over room fills, under markers.
    if snapshot.carpets:
        img = _draw_carpet_areas(img, snapshot.carpets, w2p, ss)

    draw = ImageDraw.Draw(img)

    if snapshot.objects:
        _draw_objects(draw, snapshot.objects, w2p, ss)

    # Downsample to output resolution for anti-aliasing.
    out_w = crop_w * scale
    out_h = crop_h * scale
    img = img.resize((out_w, out_h), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _crop_cells(data: bytes, width: int, height: int) -> tuple[np.ndarray, int, int, int, int]:
    """Decode, find content bbox, return (cropped_cells, col0, row0, crop_h, crop_w)."""
    cells = _decode_cells(data, width, height)

    occupied = cells != 0
    rows_any = np.any(occupied, axis=1)
    cols_any = np.any(occupied, axis=0)

    if not rows_any.any():
        return cells, 0, 0, height, width

    row0 = int(np.argmax(rows_any))
    row1 = int(len(rows_any) - np.argmax(rows_any[::-1]))
    col0 = int(np.argmax(cols_any))
    col1 = int(len(cols_any) - np.argmax(cols_any[::-1]))

    row0 = max(0, row0 - _MARGIN_CELLS)
    row1 = min(height, row1 + _MARGIN_CELLS)
    col0 = max(0, col0 - _MARGIN_CELLS)
    col1 = min(width, col1 + _MARGIN_CELLS)

    cropped = cells[row0:row1, col0:col1]
    crop_h = row1 - row0
    crop_w = col1 - col0
    return cropped, col0, row0, crop_h, crop_w


def _apply_wall_overlay(
    img_arr: np.ndarray,
    cells: np.ndarray,
    ss: int,
    raw_data: bytes,
    grid_width: int,
    grid_height: int,
    row0: int,
    col0: int,
    rooms: list[RoomInfo],
    dilation: int,
) -> None:
    """Paint wall cells onto img_arr in-place.

    Wall bytes: (byte & 0x3) == 3 AND not a room byte range.
    Single-cell speckles (no cardinal neighbour) are dropped before expanding.
    """
    h, w = cells.shape
    if rooms and len(raw_data) >= grid_width * grid_height:
        raw_arr = np.frombuffer(raw_data, dtype=np.uint8)
        raw_cropped = raw_arr[: grid_width * grid_height].reshape(grid_height, grid_width)
        raw_crop = raw_cropped[row0 : row0 + h, col0 : col0 + w][::-1, :]
        is_room_byte = ((raw_crop >= _ROOM_BYTE_MIN) & (raw_crop <= _ROOM_CLN_HI)) | (
            (raw_crop >= _ROOM_DBL_LO) & (raw_crop <= _ROOM_DBL_HI)
        )
        wall_mask = ((raw_crop & 0x3) == _CELL_WALL) & ~is_room_byte
    else:
        wall_mask = (cells == _CELL_WALL)[::-1, :]
    # Drop isolated single-cell speckles (no adjacent wall neighbour).
    has_wall_neighbour = (
        np.roll(wall_mask, 1, axis=0)
        | np.roll(wall_mask, -1, axis=0)
        | np.roll(wall_mask, 1, axis=1)
        | np.roll(wall_mask, -1, axis=1)
    )
    wall_mask = wall_mask & has_wall_neighbour
    # Keep only boundary wall cells — those adjacent to at least one non-wall cell.
    # This collapses multi-cell-thick walls to a 1-cell outline, matching the app's
    # thin-stroke appearance regardless of how wide the robot's wall data is.
    has_non_wall_neighbour = (
        ~np.roll(wall_mask, 1, axis=0)
        | ~np.roll(wall_mask, -1, axis=0)
        | ~np.roll(wall_mask, 1, axis=1)
        | ~np.roll(wall_mask, -1, axis=1)
    )
    wall_mask = wall_mask & has_non_wall_neighbour
    if ss > 1:
        wall_mask = np.repeat(np.repeat(wall_mask, ss, axis=0), ss, axis=1)
    if dilation > 0:
        dilated = wall_mask.copy()
        for d in range(1, dilation + 1):
            dilated = (
                dilated
                | np.roll(wall_mask, d, axis=0)
                | np.roll(wall_mask, -d, axis=0)
                | np.roll(wall_mask, d, axis=1)
                | np.roll(wall_mask, -d, axis=1)
            )
        img_arr[dilated] = _COLOUR_WALL
    else:
        img_arr[wall_mask] = _COLOUR_WALL


def _build_base_image(
    cells: np.ndarray,
    ss: int,
    rooms: list[RoomInfo],
    w2p: Any,
    raw_data: bytes,
    grid_width: int,
    grid_height: int,
    col0: int,
    row0: int,
    dilation: int = 1,
) -> Image.Image:
    """White → room colour fills (cell-based) → carpet hatch → cleaned → walls."""
    h, w = cells.shape
    img_arr = np.full((h * ss, w * ss, 3), _COLOUR_BG, dtype=np.uint8)

    # --- Room colour fills from raw grid bytes ---
    if rooms and len(raw_data) >= grid_width * grid_height:
        colour_by_id: dict[int, tuple[int, int, int]] = {
            r.room_id: _room_colour(r.color_id) for r in rooms
        }
        carpet_ids = {r.room_id for r in rooms if r.is_carpet}
        room_id_grid = decode_room_id_grid(raw_data, grid_width, grid_height)

        # Crop to the same region as `cells`.
        cropped_ids = room_id_grid[row0 : row0 + h, col0 : col0 + w]

        # Stamp each room's colour onto the image array (Y-flip to match cells).
        # The cells array is already cropped; row 0 of cells = world top = image top
        # after the [::-1] flip applied during render. We apply the same flip here.
        flipped_ids = cropped_ids[::-1, :]

        for room in rooms:
            rid = room.room_id
            colour = colour_by_id[rid]
            room_mask = flipped_ids == rid
            if not room_mask.any():
                continue
            if ss > 1:
                room_mask = np.repeat(np.repeat(room_mask, ss, axis=0), ss, axis=1)
            img_arr[room_mask] = colour

            # Carpet: lighten the room fill with a 25 % white wash.
            if rid in carpet_ids:
                img_arr[room_mask] = (img_arr[room_mask] * 0.75 + 255 * 0.25).astype(np.uint8)

    # --- Cleaned area overlay — only on cells with no room colour ---
    # Room cells (raw byte >= 10) masked with & 0x3 become 0-3, so their
    # cleaned/wall bits would incorrectly trigger this mask without the exclusion.
    cleaned_mask = ((cells == _CELL_CLEANED) | (cells == _CELL_DEEP_CLEANED))[::-1, :]
    if ss > 1:
        cleaned_mask = np.repeat(np.repeat(cleaned_mask, ss, axis=0), ss, axis=1)
    if rooms and len(raw_data) >= grid_width * grid_height:
        no_room_base = flipped_ids == 0
        no_room = (
            np.repeat(np.repeat(no_room_base, ss, axis=0), ss, axis=1) if ss > 1 else no_room_base
        )
        img_arr[cleaned_mask & no_room] = _COLOUR_CLEANED
    else:
        img_arr[cleaned_mask] = _COLOUR_CLEANED

    # --- Carpet cell overlay ---
    # Replace the app's per-cell checkerboard with a smooth 25 % white wash.
    # carpet_room bytes (147-196): second-pass cells inside a room — lighten over room colour.
    # carpet_nonroom byte (253): second-pass cells outside any room — lighten over cleaned colour.
    if len(raw_data) >= grid_width * grid_height:
        raw_arr = np.frombuffer(raw_data, dtype=np.uint8)
        raw_grid = raw_arr[: grid_width * grid_height].reshape(grid_height, grid_width)
        raw_crop = raw_grid[row0 : row0 + h, col0 : col0 + w][::-1, :]

        carpet_room = (raw_crop >= _ROOM_DBL_LO) & (raw_crop <= _ROOM_DBL_HI)
        carpet_nonroom = raw_crop == _CARPET_NONROOM_BYTE
        carpet_any = carpet_room | carpet_nonroom

        def _up(mask: np.ndarray) -> np.ndarray:
            return np.repeat(np.repeat(mask, ss, axis=0), ss, axis=1)

        carpet_mask = _up(carpet_any)
        img_arr[carpet_mask] = (img_arr[carpet_mask] * 0.75 + 255 * 0.25).astype(np.uint8)

    _apply_wall_overlay(
        img_arr, cells, ss, raw_data, grid_width, grid_height, row0, col0, rooms, dilation
    )

    return Image.fromarray(img_arr, mode="RGB")


def _decode_cells(data: bytes, width: int, height: int) -> np.ndarray:
    """Return a (height, width) uint8 array of cell values (0-3)."""
    arr = np.frombuffer(data, dtype=np.uint8)
    n_cells = width * height

    if len(arr) >= n_cells:
        return (arr[:n_cells] & 0x3).reshape(height, width)

    # 2 bits per cell packed (doc/PROTOCOL.md §13.3).
    half_w = width // 2
    half_h = height // 2
    packed = arr[: half_w * half_h].reshape(half_h, half_w)
    cells = np.zeros((height, width), dtype=np.uint8)
    cells[0::2, 0::2] = (packed >> 6) & 0x3
    cells[1::2, 0::2] = (packed >> 4) & 0x3
    cells[0::2, 1::2] = (packed >> 2) & 0x3
    cells[1::2, 1::2] = (packed >> 0) & 0x3
    return cells


def decode_room_id_grid(data: bytes, width: int, height: int) -> np.ndarray:
    """Return a (height, width) int16 array of room IDs decoded from raw grid bytes.

    0 means "no room". Only valid for full-resolution grids (len(data) >= width*height).

    Encoding (APK GridMap.updateGlobalMap signed-byte branches, doc/MAP_DATA.md §4.2):
      byte in [ 10,  59]: raw (unvisited) room cell;        room_id = byte
      byte in [ 60, 127]: cleaned room cell;                room_id = byte - 50
      byte in [147, 196]: carpet/second-pass room cell;     room_id = 206 - byte
      all other values (incl. 128-146, 197-254, 255): not a room cell → 0
    """
    n = width * height
    bv = np.frombuffer(data, dtype=np.uint8)[:n]
    out = np.zeros(n, dtype=np.int16)
    mask_raw = (bv >= _ROOM_BYTE_MIN) & (bv <= _ROOM_RAW_HI)
    mask_cln = (bv >= _ROOM_CLN_LO) & (bv <= _ROOM_CLN_HI)
    mask_dbl = (bv >= _ROOM_DBL_LO) & (bv <= _ROOM_DBL_HI)
    out[mask_raw] = bv[mask_raw].astype(np.int16)
    out[mask_cln] = (bv[mask_cln] - 50).astype(np.int16)
    out[mask_dbl] = (206 - bv[mask_dbl]).astype(np.int16)
    return out.reshape(height, width)


# Area-carpet quad styling (furniture_info type 1550, doc/MAP_DATA.md §6.4).
_CARPET_FILL = (180, 120, 60, 100)  # semi-transparent orange-brown (RGBA)
_CARPET_OUTLINE = (140, 80, 30, 220)  # darker orange-brown outline


def _draw_carpet_areas(
    img: Image.Image,
    carpets: list[CarpetArea],
    w2p: Any,
    ss: int,
) -> Image.Image:
    """Render furniture_info carpet quads (type 1550) on a copy of img.

    The app consumes exactly the FIRST FOUR points of each entry as a quad
    (APK CarpetTexture.processPose reads 8 floats; CarpetMap.changeRectPose
    draws the border as the cycle p0→p1→p2→p3). Any further points in the
    entry are ignored by the app — we must do the same, otherwise extra
    points produce arbitrary self-intersecting polygons.
    Style matches the app: semi-transparent fill with a darker outline.
    """
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)

    for carpet in carpets:
        px_pts: list[tuple[int, int]] = [w2p(x, y) for x, y in carpet.points[:4]]
        if len(px_pts) < _MIN_POLYGON_PTS:
            continue
        odraw.polygon(px_pts, fill=_CARPET_FILL)
        # Closed border as a line loop — polygon outline is 1px only, which
        # would not survive the LANCZOS downsample at supersampled resolution.
        odraw.line([*px_pts, px_pts[0]], fill=_CARPET_OUTLINE, width=max(1, ss // 3))

    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _draw_objects(
    draw: ImageDraw.ImageDraw,
    objects: list[Any],
    w2p: Any,
    ss: int,
) -> None:
    # All AI objects — including 1005 carpet — are plain labelled dots, as in
    # the app (icons only). The carpet AREA comes from the grid-byte
    # checkerboard in _build_base_image, not from these detection points.
    r = max(4, ss // 2)

    for obj in objects:
        colour, label = _OBJECT_TYPES.get(obj.type_id, ((160, 160, 160), "?"))
        cx, cy = w2p(obj.x, obj.y)
        draw.ellipse(
            [(cx - r, cy - r), (cx + r, cy + r)],
            fill=colour,
            outline=(255, 255, 255),
            width=max(1, ss // 8),
        )
        char = label[0].upper()
        bbox = draw.textbbox((0, 0), char)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text((cx - tw // 2, cy - th // 2), char, fill=(255, 255, 255))


def compute_room_cell_map(
    snapshot: MapSnapshot, layout: RenderLayout
) -> dict[int, list[tuple[int, int, int]]]:
    """Return RLE-encoded room cells for each room.

    Format: {room_id: [(px_row, px_col_start, run_len), ...]}
    Each tuple encodes a horizontal run of `run_len` cells (each cell is
    `layout.scale` pixels wide/tall) starting at (px_col_start, px_row).

    Positions are in PNG pixel coordinates (after crop + scale).
    """
    grid = snapshot.grid
    n = grid.width * grid.height

    # Only full-resolution grids encode room IDs (packed 2-bit grids don't).
    if len(grid.data) < n:
        return {}

    scale = layout.scale
    room_id_grid = decode_room_id_grid(grid.data, grid.width, grid.height)

    # Collect {room_id: {px_row: sorted_col_list}} for RLE compression.
    rows_by_room: dict[int, dict[int, list[int]]] = {}

    coords = np.argwhere(room_id_grid > 0)
    for grid_row, grid_col in coords:
        room_id = int(room_id_grid[grid_row, grid_col])
        px_col = (int(grid_col) - layout.col0) * scale
        px_row = layout.out_h - scale - (int(grid_row) - layout.row0) * scale

        if px_col < 0 or px_row < 0 or px_col >= layout.out_w or px_row >= layout.out_h:
            continue

        room_rows = rows_by_room.setdefault(room_id, {})
        room_rows.setdefault(px_row, []).append(px_col)

    # Build RLE spans: (px_row, col_start, run_len).
    result: dict[int, list[tuple[int, int, int]]] = {}
    for room_id, row_dict in rows_by_room.items():
        spans: list[tuple[int, int, int]] = []
        for px_row in sorted(row_dict):
            cols = sorted(row_dict[px_row])
            run_start = cols[0]
            run_end = cols[0]
            for col in cols[1:]:
                if col == run_end + scale:
                    run_end = col
                else:
                    spans.append((px_row, run_start, (run_end - run_start) // scale + 1))
                    run_start = col
                    run_end = col
            spans.append((px_row, run_start, (run_end - run_start) // scale + 1))
        result[room_id] = spans
    return result
