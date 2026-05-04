# SPDX-License-Identifier: MIT
"""Parse the karcher-home Map.data dict into a MapSnapshot DTO.

Pure function — no I/O, no HA imports. The dict structure mirrors the
protobuf fields documented in doc/PROTOCOL.md §13.4.
"""

from __future__ import annotations

import base64
import contextlib
import logging
from typing import Any

from .map_data import MapGrid, MapObject, MapSnapshot, Pose

_LOGGER = logging.getLogger(__name__)


def parse_map(
    raw: dict[str, Any],
    cur_path: list[tuple[float, float]],
) -> MapSnapshot | None:
    """Translate Map.data dict from karcher-home into a MapSnapshot.

    Returns None if the map header or grid bytes are missing/malformed.
    """
    try:
        return _parse(raw, cur_path)
    except Exception as exc:
        _LOGGER.warning("map parse failed: %s", exc)
        return None


def _parse(
    raw: dict[str, Any],
    cur_path: list[tuple[float, float]],
) -> MapSnapshot:
    head = raw.get("map_head", {})
    resolution = float(head.get("resolution", 0.05))
    # karcher-home applies snake_case() to proto field names:
    # mapHead.sizeX → size_x, mapHead.minX → min_x, etc.
    width = int(head.get("size_x", head.get("sizeX", 120)))
    height = int(head.get("size_y", head.get("sizeY", 120)))
    min_x = float(head.get("min_x", head.get("minX", 0.0)))
    min_y = float(head.get("min_y", head.get("minY", 0.0)))

    # karcher-home extracts mapData.mapData bytes and base64-encodes them via
    # MessageToDict, so raw["map_data"] is a base64 string (not a nested dict).
    grid_bytes_raw = raw.get("map_data")
    if grid_bytes_raw is None:
        raise ValueError("map_data is missing")

    if isinstance(grid_bytes_raw, bytes | bytearray):
        grid_bytes = bytes(grid_bytes_raw)
    elif isinstance(grid_bytes_raw, str):
        grid_bytes = base64.b64decode(grid_bytes_raw)
    else:
        grid_bytes = bytes(grid_bytes_raw)

    grid = MapGrid(
        width=width,
        height=height,
        data=grid_bytes,
        resolution=resolution,
        min_x=min_x,
        min_y=min_y,
    )

    path = _parse_history_pose(raw.get("history_pose", {}))
    robot = _parse_current_pose(raw.get("current_pose"))
    charger = _parse_charge_station(raw.get("charge_station"))
    objects = _parse_objects(raw.get("objects"))

    return MapSnapshot(
        grid=grid,
        robot=robot,
        charger=charger,
        path=path,
        cur_path=list(cur_path),
        objects=objects,
    )


def _parse_history_pose(history: dict[str, Any]) -> list[tuple[float, float]]:
    points_raw = history.get("points") or history.get("poseInfo", [])
    if not isinstance(points_raw, list | tuple):
        return []
    result: list[tuple[float, float]] = []
    for p in points_raw:
        with contextlib.suppress(KeyError, TypeError, ValueError):
            result.append((float(p["x"]), float(p["y"])))
    return result


def _parse_current_pose(pose: Any) -> Pose | None:
    if pose is None:
        return None
    try:
        return Pose(x=float(pose["x"]), y=float(pose["y"]), phi=float(pose.get("phi", 0.0)))
    except (KeyError, TypeError, ValueError):
        return None


def _parse_charge_station(station: Any) -> Pose | None:
    if station is None:
        return None
    try:
        return Pose(x=float(station["x"]), y=float(station["y"]))
    except (KeyError, TypeError, ValueError):
        return None


def _parse_objects(raw: Any) -> list[MapObject]:
    if not isinstance(raw, list):
        return []
    result: list[MapObject] = []
    for obj in raw:
        with contextlib.suppress(KeyError, TypeError, ValueError):
            result.append(
                MapObject(
                    object_id=int(obj["object_id"]),
                    type_id=int(obj["object_type_id"]),
                    x=float(obj["x"]),
                    y=float(obj["y"]),
                )
            )
    return result
