# SPDX-License-Identifier: MIT
"""Render a MapSnapshot to PNG bytes using Pillow + numpy.

Pure function — no I/O, no HA imports. Called in an executor from
KarcherMapImage.async_image(). Pillow and numpy are HA core dependencies.

Rendering pipeline:
  1. Decode cell grid → numpy array.
  2. Crop to content bounding box + margin.
  3. Colour-fill cells at SUPERSAMPLE x output scale.
  4. Draw path/cur_path/robot/charger overlays at high res.
  5. Downsample with LANCZOS for anti-aliased output.
"""

from __future__ import annotations

import io
import logging
import math
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

import numpy as np
from PIL import Image, ImageDraw

from .map_data import MapSnapshot, RoomInfo

# Cell type values from the map grid encoding (GridMap.java, PositionInfo.java).
# Raw bytes masked with & 0x3: 0=free, 1=cleaned, 2=deep-cleaned, 3=wall (0xFF&3).
_CELL_WALL = 3
_CELL_CLEANED = 1
_CELL_DEEP_CLEANED = 2

# Colours matched to the Kärcher app aesthetic.
_COLOUR_BG = (255, 255, 255)       # white canvas / free space
_COLOUR_CLEANED = (213, 240, 232)  # app: #D5F0E8 light cyan cleaned area
_COLOUR_WALL = (60, 60, 60)         # dark grey wall, matching app

_COLOUR_PATH = (80, 140, 120)      # darker teal — visible on light-cyan background
_COLOUR_CUR_PATH = (255, 160, 0)   # amber current-run path
_COLOUR_CHARGER = (30, 30, 30)     # dark charger dot
_COLOUR_ROBOT = (255, 255, 255)    # white robot body
_COLOUR_ROBOT_OUTLINE = (30, 30, 30)  # dark robot outline

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
_COLOUR_ROOM_LABEL = (80, 80, 90)

# AI object type IDs (AiObjectType.java) → (fill_colour, label).
# Only types the app surfaces to the user are included.
_OBJECT_TYPES: dict[int, tuple[tuple[int, int, int], str]] = {
    1001: ((220, 120, 60),  "sock"),
    1002: ((180, 100, 40),  "shoe"),
    1003: ((230, 60,  60),  "wire"),
    1005: ((100, 160, 100), "carpet"),
    1007: ((160, 100, 200), "dog"),
    1006: ((160, 100, 200), "cat"),
    1011: ((200, 60,  60),  "!"),      # pet waste
    1017: ((80,  140, 200), "scale"),
    1038: ((120, 120, 120), "chair"),
}

# Render at SUPERSAMPLE x the requested scale, then downsample.
_SUPERSAMPLE = 4

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


def compute_render_layout(snapshot: MapSnapshot, *, scale: int = 2) -> RenderLayout:
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


def render_map(snapshot: MapSnapshot, *, scale: int = 2) -> bytes:
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
        cells, ss, snapshot.rooms, w2p,
        grid.data, grid.width, grid.height, col0, row0,
    )

    draw = ImageDraw.Draw(img)

    path_w = max(1, ss // 4)
    if snapshot.path:
        _draw_polyline(draw, snapshot.path, w2p, _COLOUR_PATH, width=path_w)

    cur_w = max(1, ss // 3)
    if snapshot.cur_path:
        _draw_polyline(draw, snapshot.cur_path, w2p, _COLOUR_CUR_PATH, width=cur_w)

    if snapshot.objects:
        img = _draw_objects(draw, snapshot.objects, w2p, ss, img)
        draw = ImageDraw.Draw(img)

    # Room labels drawn after paths so they sit on top.
    if snapshot.room_chains and snapshot.rooms:
        _draw_room_labels(draw, snapshot.rooms, w2p, scale)

    if snapshot.charger is not None:
        cx, cy = w2p(snapshot.charger.x, snapshot.charger.y)
        r = max(4, ss // 2)
        draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=_COLOUR_CHARGER)
        ri = max(2, r - ss // 4)
        draw.ellipse([(cx - ri, cy - ri), (cx + ri, cy + ri)], fill=(200, 200, 200))

    # Downsample to output resolution for anti-aliasing.
    out_w = crop_w * scale
    out_h = crop_h * scale
    img = img.resize((out_w, out_h), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _crop_cells(
    data: bytes, width: int, height: int
) -> tuple[np.ndarray, int, int, int, int]:
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
        cropped_ids = room_id_grid[row0:row0 + h, col0:col0 + w]

        # Stamp each room's colour onto the image array (Y-flip to match cells).
        # The cells array is already cropped; row 0 of cells = world top = image top
        # after the [::-1] flip applied during render. We apply the same flip here.
        flipped_ids = cropped_ids[::-1, :]

        for room in rooms:
            rid = room.room_id
            colour = colour_by_id[rid]
            room_mask = (flipped_ids == rid)
            if not room_mask.any():
                continue
            if ss > 1:
                room_mask = np.repeat(np.repeat(room_mask, ss, axis=0), ss, axis=1)
            img_arr[room_mask] = colour

            # Carpet: vertical stripe hatch — darken every Nth column within room cells.
            if rid in carpet_ids:
                stripe_spacing = ss * 3  # one stripe per 3 output cells
                hatch_colour = tuple(max(0, c - 50) for c in colour)
                col_indices = np.arange(w * ss)
                stripe_cols = col_indices % stripe_spacing == 0
                # Apply stripe only where this room's mask is set.
                stripe_mask = room_mask & stripe_cols[np.newaxis, :]
                img_arr[stripe_mask] = hatch_colour

    # --- Cleaned area overlay — only on cells with no room colour ---
    # Room cells have raw byte >= 10; after & 0x3 they become 0–3, so their
    # cleaned/wall bits would incorrectly trigger this mask without the exclusion.
    cleaned_mask = ((cells == _CELL_CLEANED) | (cells == _CELL_DEEP_CLEANED))[::-1, :]
    if ss > 1:
        cleaned_mask = np.repeat(np.repeat(cleaned_mask, ss, axis=0), ss, axis=1)
    if rooms and len(raw_data) >= grid_width * grid_height:
        no_room = np.repeat(np.repeat((flipped_ids == 0), ss, axis=0), ss, axis=1) if ss > 1 else (flipped_ids == 0)
        img_arr[cleaned_mask & no_room] = _COLOUR_CLEANED
    else:
        img_arr[cleaned_mask] = _COLOUR_CLEANED

    # --- Wall overlay ---
    # True wall bytes: value 3 (low 2 bits == 3, raw byte in 0-9 range),
    # OR 0xFF (255), which the app uses as a solid obstacle marker.
    # Room bytes (>=10, <147 or 197-255 room range) whose low 2 bits happen
    # to be 11 must be excluded — they are room cells, not walls.
    # Exclusion: raw byte is a room cell if it is in [10,146] or [197,254],
    # OR if it is in [147,196] (double-cleaned rooms). Complement: wall bytes
    # are those where (byte & 0x3)==3 AND byte NOT in any room range, i.e.
    # byte in {0,1,2,3} ∪ {255}.
    if rooms and len(raw_data) >= grid_width * grid_height:
        raw_arr = np.frombuffer(raw_data, dtype=np.uint8)
        raw_cropped = raw_arr[: grid_width * grid_height].reshape(grid_height, grid_width)
        raw_crop = raw_cropped[row0:row0 + h, col0:col0 + w][::-1, :]
        is_room_byte = (raw_crop >= 10) & (raw_crop != 255)
        wall_mask = ((raw_crop & 0x3) == _CELL_WALL) & ~is_room_byte
    else:
        wall_mask = (cells == _CELL_WALL)[::-1, :]
    if ss > 1:
        wall_mask = np.repeat(np.repeat(wall_mask, ss, axis=0), ss, axis=1)
    # Dilate by 1px so walls survive the 4× LANCZOS downsample visibly.
    dilated = (
        wall_mask
        | np.roll(wall_mask, 1, axis=0)
        | np.roll(wall_mask, -1, axis=0)
        | np.roll(wall_mask, 1, axis=1)
        | np.roll(wall_mask, -1, axis=1)
    )
    img_arr[dilated] = _COLOUR_WALL

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

    Encoding (GridMap.java / doc/PROTOCOL.md §13.4):
      byte in [147, 196]: double-cleaned room cell; room_id = 206 - byte
      byte in [ 60, 146] or [197, 254]: cleaned room cell; room_id = byte - 50
      byte in [ 10,  59]: raw (unvisited) room cell; room_id = byte
      all other values: not a room cell → 0
    """
    n = width * height
    bv = np.frombuffer(data, dtype=np.uint8)[:n]
    out = np.zeros(n, dtype=np.int16)
    mask_dbl = (bv >= 147) & (bv <= 196)
    mask_cln = (bv >= 60) & (bv != 255) & ~mask_dbl
    mask_raw = (bv >= 10) & (bv != 255) & ~mask_dbl & ~mask_cln
    out[mask_dbl] = (206 - bv[mask_dbl]).astype(np.int16)
    out[mask_cln] = (bv[mask_cln] - 50).astype(np.int16)
    out[mask_raw] = bv[mask_raw].astype(np.int16)
    return out.reshape(height, width)



_FONT_SEARCH_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/local/share/fonts/DejaVuSans-Bold.ttf",
    "/system/fonts/Roboto-Bold.ttf",
    "/system/fonts/DroidSans-Bold.ttf",
]


def _load_font(size: int) -> Any:
    from PIL import ImageFont
    for path in _FONT_SEARCH_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    # load_default(size=) requires Pillow ≥ 10; fall back gracefully.
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _draw_room_labels(
    draw: ImageDraw.ImageDraw,
    rooms: list[RoomInfo],
    w2p: Any,
    scale: int,
) -> None:
    # Labels are drawn at supersampled resolution but sized for the output
    # scale so they survive LANCZOS downsampling at a legible size.
    # 14px at scale=2 output → readable room names.
    font_size = max(14, scale * 7) * _SUPERSAMPLE
    font = _load_font(font_size)

    for room in rooms:
        lx, ly = w2p(room.label_x, room.label_y)
        text = room.name
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = lx - tw // 2
        ty = ly - th // 2
        # White halo for readability over any background.
        halo = max(2, font_size // 8)
        for dx, dy in ((-halo, 0), (halo, 0), (0, -halo), (0, halo),
                       (-halo, -halo), (halo, -halo), (-halo, halo), (halo, halo)):
            draw.text((tx + dx, ty + dy), text, fill=(255, 255, 255), font=font)
        draw.text((tx, ty), text, fill=_COLOUR_ROOM_LABEL, font=font)


_CARPET_TYPE_ID = 1005
_CARPET_FILL = (180, 120, 60, 100)       # semi-transparent orange-brown (RGBA)
_CARPET_OUTLINE = (140, 80, 30, 220)    # darker orange-brown outline
# Two carpet detections within this distance (metres) belong to the same carpet.
_CARPET_CLUSTER_DIST = 1.5


def _cluster_points(
    points: list[tuple[float, float]], threshold: float
) -> list[list[tuple[float, float]]]:
    """Single-linkage clustering by Euclidean distance threshold."""
    clusters: list[list[tuple[float, float]]] = []
    for pt in points:
        merged = None
        for cluster in clusters:
            if any(
                math.hypot(pt[0] - cp[0], pt[1] - cp[1]) <= threshold
                for cp in cluster
            ):
                if merged is None:
                    cluster.append(pt)
                    merged = cluster
                else:
                    merged.extend(cluster)
                    cluster.clear()
        if merged is None:
            clusters.append([pt])
    return [c for c in clusters if c]


def _draw_carpet_clusters(
    img: Image.Image,
    carpet_points: list[tuple[float, float]],
    w2p: Any,
) -> Image.Image:
    """Render carpet clusters as convex hull polygons on a copy of img."""
    try:
        from scipy.spatial import ConvexHull  # type: ignore[import-untyped]
        _have_scipy = True
    except ImportError:
        _have_scipy = False

    clusters = _cluster_points(carpet_points, _CARPET_CLUSTER_DIST)

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)

    for cluster in clusters:
        px_pts = [w2p(x, y) for x, y in cluster]
        if len(px_pts) < _MIN_POLYGON_PTS or not _have_scipy:
            # Too few points or no scipy — draw an ellipse spanning all points.
            xs = [p[0] for p in px_pts]
            ys = [p[1] for p in px_pts]
            cx = sum(xs) // len(xs)
            cy = sum(ys) // len(ys)
            rx = max(12, (max(xs) - min(xs)) // 2 + 12)
            ry = max(12, (max(ys) - min(ys)) // 2 + 12)
            odraw.ellipse(
                [(cx - rx, cy - ry), (cx + rx, cy + ry)],
                fill=_CARPET_FILL,
                outline=_CARPET_OUTLINE[:3],
            )
            continue

        pts_arr = np.array(px_pts, dtype=float)
        try:
            hull = ConvexHull(pts_arr)
            hull_poly = [tuple(pts_arr[i].astype(int)) for i in hull.vertices]
        except ValueError:
            hull_poly = px_pts

        odraw.polygon(hull_poly, fill=_CARPET_FILL, outline=_CARPET_OUTLINE)

    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _draw_objects(
    draw: ImageDraw.ImageDraw,
    objects: list[Any],
    w2p: Any,
    ss: int,
    img: Image.Image,
) -> Image.Image:
    carpet_points: list[tuple[float, float]] = []
    r = max(4, ss // 2)

    for obj in objects:
        if obj.type_id == _CARPET_TYPE_ID:
            carpet_points.append((obj.x, obj.y))
            continue
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

    if carpet_points:
        img = _draw_carpet_clusters(img, carpet_points, w2p)

    return img


_POLYLINE_MIN_POINTS = 2


def _draw_polyline(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    w2p: Any,
    colour: tuple[int, int, int],
    width: int,
) -> None:
    if len(points) < _POLYLINE_MIN_POINTS:
        return
    # joint="miter" avoids Pillow's default round caps at every vertex,
    # which turn a dense path into a solid blob.
    draw.line([w2p(x, y) for x, y in points], fill=colour, width=width, joint="miter")
