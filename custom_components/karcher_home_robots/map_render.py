# SPDX-License-Identifier: MIT
"""Render a MapSnapshot to PNG bytes using Pillow + numpy.

Pure function — no I/O, no HA imports. Called in an executor from
KarcherMapImage.async_image(). Pillow and numpy are HA core dependencies.

Rendering pipeline:
  1. Decode cell grid → numpy array.
  2. Crop to content bounding box + margin.
  3. Colour-fill cells at SUPERSAMPLE × output scale.
  4. Draw path/cur_path/robot/charger overlays at high res.
  5. Downsample with LANCZOS for anti-aliased output.
"""

from __future__ import annotations

import io
import math
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from .map_data import MapSnapshot

# Cell type values from the map grid encoding (doc/PROTOCOL.md §13.3).
_CELL_WALL = 1
_CELL_CLEANED = 3

# Colours matched to the Kärcher app aesthetic.
_COLOUR_BG = (255, 255, 255)       # white canvas / free space
_COLOUR_CLEANED = (180, 210, 220)  # light blue-grey cleaned area
_COLOUR_WALL = (50, 50, 55)        # near-black wall/obstacle

_COLOUR_PATH = (120, 160, 190)     # muted blue-grey history path
_COLOUR_CUR_PATH = (255, 180, 0)   # amber current-run path
_COLOUR_CHARGER = (30, 30, 30)     # dark charger dot
_COLOUR_ROBOT = (255, 255, 255)    # white robot body
_COLOUR_ROBOT_OUTLINE = (60, 60, 60)  # dark robot outline

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

# Render at SUPERSAMPLE × the requested scale, then downsample.
_SUPERSAMPLE = 4

# Margin around the content bounding box, in grid cells.
_MARGIN_CELLS = 10


def render_map(snapshot: MapSnapshot, *, scale: int = 2) -> bytes:
    """Return PNG bytes for the given MapSnapshot."""
    grid = snapshot.grid
    ss = scale * _SUPERSAMPLE

    cells, col0, row0, crop_h, crop_w = _crop_cells(grid.data, grid.width, grid.height)

    img = _cells_to_image(cells, ss)
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

    draw = ImageDraw.Draw(img)

    path_w = max(1, ss // 3)
    if snapshot.path:
        _draw_polyline(draw, snapshot.path, w2p, _COLOUR_PATH, width=path_w)

    cur_w = max(2, ss // 2)
    if snapshot.cur_path:
        _draw_polyline(draw, snapshot.cur_path, w2p, _COLOUR_CUR_PATH, width=cur_w)

    if snapshot.objects:
        _draw_objects(draw, snapshot.objects, w2p, ss)

    if snapshot.charger is not None:
        cx, cy = w2p(snapshot.charger.x, snapshot.charger.y)
        r = max(4, ss // 2)
        draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=_COLOUR_CHARGER)
        ri = max(2, r - ss // 4)
        draw.ellipse([(cx - ri, cy - ri), (cx + ri, cy + ri)], fill=(200, 200, 200))

    if snapshot.robot is not None:
        rx, ry = w2p(snapshot.robot.x, snapshot.robot.y)
        r = max(5, ss // 2 + 1)
        draw.ellipse(
            [(rx - r, ry - r), (rx + r, ry + r)],
            fill=_COLOUR_ROBOT,
            outline=_COLOUR_ROBOT_OUTLINE,
            width=max(1, ss // 6),
        )
        phi = snapshot.robot.phi
        line_len = r + max(4, ss // 3)
        ex = rx + int(round(math.cos(phi) * line_len))
        ey = ry - int(round(math.sin(phi) * line_len))
        draw.line([(rx, ry), (ex, ey)], fill=_COLOUR_ROBOT_OUTLINE, width=max(2, ss // 5))

    # Downsample to output resolution for anti-aliasing.
    out_w = crop_w * scale
    out_h = crop_h * scale
    img = img.resize((out_w, out_h), Image.LANCZOS)

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


def _cells_to_image(cells: np.ndarray, px_per_cell: int) -> Image.Image:
    """Colour-fill cells and return a PIL Image (not yet downsampled)."""
    lut = np.array(
        [_COLOUR_BG, _COLOUR_WALL, _COLOUR_BG, _COLOUR_CLEANED], dtype=np.uint8
    )
    rgb = lut[cells]

    # Flip Y before scaling.
    rgb = rgb[::-1, :, :]

    if px_per_cell > 1:
        rgb = np.repeat(np.repeat(rgb, px_per_cell, axis=0), px_per_cell, axis=1)

    return Image.fromarray(np.ascontiguousarray(rgb), mode="RGB")


def _decode_cells(data: bytes, width: int, height: int) -> np.ndarray:
    """Return a (height, width) uint8 array of cell values (0–3)."""
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


def _draw_objects(
    draw: ImageDraw.ImageDraw,
    objects: list,
    w2p: Any,
    ss: int,
) -> None:
    r = max(4, ss // 2)
    for obj in objects:
        colour, label = _OBJECT_TYPES.get(obj.type_id, ((160, 160, 160), "?"))
        cx, cy = w2p(obj.x, obj.y)
        # Filled circle with white outline.
        draw.ellipse(
            [(cx - r, cy - r), (cx + r, cy + r)],
            fill=colour,
            outline=(255, 255, 255),
            width=max(1, ss // 8),
        )
        # Single-character label centred in the dot.
        char = label[0].upper()
        bbox = draw.textbbox((0, 0), char)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text((cx - tw // 2, cy - th // 2), char, fill=(255, 255, 255))


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
    draw.line([w2p(x, y) for x, y in points], fill=colour, width=width)
