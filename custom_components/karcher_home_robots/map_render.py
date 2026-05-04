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

from .map_data import MapSnapshot, RoomChain, RoomInfo

# Cell type values from the map grid encoding (GridMap.java, PositionInfo.java).
# Raw bytes masked with & 0x3: 0=free, 1=cleaned, 2=deep-cleaned, 3=wall (0xFF&3).
_CELL_WALL = 3
_CELL_CLEANED = 1  # value=2 is deep-cleaned, also rendered as cleaned

# Colours matched to the Kärcher app aesthetic.
_COLOUR_BG = (255, 255, 255)       # white canvas / free space
_COLOUR_CLEANED = (213, 240, 232)  # app: #D5F0E8 light cyan cleaned area
_COLOUR_WALL = (37, 199, 174)      # app: #25C7AE teal wall

_COLOUR_PATH = (80, 140, 120)      # darker teal — visible on light-cyan background
_COLOUR_CUR_PATH = (255, 160, 0)   # amber current-run path
_COLOUR_CHARGER = (30, 30, 30)     # dark charger dot
_COLOUR_ROBOT = (255, 255, 255)    # white robot body
_COLOUR_ROBOT_OUTLINE = (30, 30, 30)  # dark robot outline

# Room colour palette matched to the Kärcher app (color_id 1–5).
# Falls back to light grey for unknown IDs.
_ROOM_COLOURS: dict[int, tuple[int, int, int]] = {
    1: (255, 200, 200),  # pink/rose
    2: (180, 230, 225),  # teal/cyan
    3: (190, 205, 220),  # blue-grey
    4: (195, 215, 200),  # green-grey
    5: (210, 200, 225),  # lavender
}
_ROOM_COLOUR_DEFAULT = (220, 220, 220)
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

# Render at SUPERSAMPLE × the requested scale, then downsample.
_SUPERSAMPLE = 4

# Margin around the content bounding box, in grid cells.
_MARGIN_CELLS = 10


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
    img = _build_base_image(cells, ss, snapshot.room_chains, snapshot.rooms, w2p)

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


def _build_base_image(
    cells: np.ndarray,
    ss: int,
    chains: list[RoomChain],
    rooms: list[RoomInfo],
    w2p: Any,
) -> Image.Image:
    """White background → room colour fills → wall cells stamped on top."""
    h, w = cells.shape
    img = Image.new("RGB", (w * ss, h * ss), _COLOUR_BG)

    # Render all wall cells.
    wall_mask_flipped = (cells == _CELL_WALL)[::-1, :]
    if ss > 1:
        wall_mask_flipped = np.repeat(np.repeat(wall_mask_flipped, ss, axis=0), ss, axis=1)

    img_arr = np.array(img)
    # value=1 (cleaned) and value=2 (deep-cleaned) both render as cleaned area.
    cleaned_mask_flipped = ((cells == 1) | (cells == 2))[::-1, :]
    if ss > 1:
        cleaned_mask_flipped = np.repeat(np.repeat(cleaned_mask_flipped, ss, axis=0), ss, axis=1)
    img_arr[cleaned_mask_flipped] = _COLOUR_CLEANED
    img_arr[wall_mask_flipped] = _COLOUR_WALL
    return Image.fromarray(img_arr, mode="RGB")



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


def _simplify_rectilinear(
    pts: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Snap a 1-cell boundary trace to axis-aligned segments."""
    if len(pts) < 2:
        return pts
    snapped: list[tuple[float, float]] = [pts[0]]
    for p in pts[1:]:
        prev = snapped[-1]
        if abs(p[0] - prev[0]) >= abs(p[1] - prev[1]):
            snapped.append((p[0], prev[1]))
        else:
            snapped.append((prev[0], p[1]))
    deduped: list[tuple[float, float]] = [snapped[0]]
    for p in snapped[1:]:
        if p != deduped[-1]:
            deduped.append(p)
    result: list[tuple[float, float]] = [deduped[0]]
    for i in range(1, len(deduped) - 1):
        prev = result[-1]
        cur = deduped[i]
        nxt = deduped[i + 1]
        if (prev[0] == cur[0] == nxt[0]) or (prev[1] == cur[1] == nxt[1]):
            continue
        result.append(cur)
    if deduped[-1] != result[-1]:
        result.append(deduped[-1])
    return result


def _draw_room_fills(
    draw: ImageDraw.ImageDraw,
    chains: list[RoomChain],
    rooms: list[RoomInfo],
    w2p: Any,
) -> None:
    colour_by_id = {r.room_id: _ROOM_COLOURS.get(r.color_id, _ROOM_COLOUR_DEFAULT) for r in rooms}
    for chain in chains:
        colour = colour_by_id.get(chain.room_id, _ROOM_COLOUR_DEFAULT)
        if len(chain.points) < 3:
            continue
        simplified = _simplify_rectilinear(chain.points)
        if len(simplified) < 3:
            continue
        poly = [w2p(x, y) for x, y in simplified]
        draw.polygon(poly, fill=colour)


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
    from scipy.spatial import ConvexHull  # HA core dep

    clusters = _cluster_points(carpet_points, _CARPET_CLUSTER_DIST)

    # RGBA overlay for alpha compositing.
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)

    for cluster in clusters:
        px_pts = [w2p(x, y) for x, y in cluster]
        if len(px_pts) < 3:
            # Too few points — draw a simple dot.
            cx, cy = px_pts[0]
            r = 8
            odraw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=_CARPET_FILL, outline=_CARPET_OUTLINE[:3])
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
    objects: list,
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
