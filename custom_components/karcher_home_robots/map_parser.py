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

from .map_data import (
    CarpetArea,
    CleaningZone,
    MapGrid,
    MapObject,
    MapSnapshot,
    Pose,
    RestrictedZone,
    RoomChain,
    RoomInfo,
)

_LOGGER = logging.getLogger(__name__)

# RobotMap.furniture_info type_id marking an area carpet (rug).
# APK-verified: GlobalRender.updateMatericalSpecialInfo, 2026-06-12.
_FURNITURE_CARPET_TYPE_ID = 1550

# DeviceAreaDataInfo.type values (APK WallSettingActivity add-wall buttons →
# addWallArea(type)): 1 = no-go zone, 2 = line virtual wall, 3 = no-mop zone.
# These hold for the SEND path (virtual_walls). The device re-codes some types on
# the report path (e.g. no-mop → 6, see §6.7), so the parser is lenient: it keeps
# every entry with points and preserves the raw type, letting the renderer style
# known types and still surface unknown ones.

# Upper bound on grid dimensions from the cloud map_head. Real grids are ~120;
# the renderer allocates (h*ss, w*ss, 3) with ss=6, so a malicious oversized
# payload would amplify ~108x in memory. Reject anything implausibly large.
_MAX_GRID_DIM = 4000


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
    if not (0 < width <= _MAX_GRID_DIM and 0 < height <= _MAX_GRID_DIM):
        raise ValueError(f"grid dimensions out of range: {width}x{height}")
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
    rooms = _parse_room_data_info(raw.get("room_data_info"))
    room_chains = _parse_room_chain(raw.get("room_chain"), min_x, min_y, resolution)
    carpets = _parse_furniture_info(raw.get("furniture_info"))
    # Only virtual_walls (field 9) holds restrictions (no-go / no-mop / line wall).
    # areas_info (field 10) is a different thing: the app parses it via a separate
    # path (RobotMapApi.parseAreaDataInfo → updateAreaData(false, …), vs
    # parseWallDataInfo → updateAreaData(true, …) for walls) and it carries active
    # zone-clean rectangles, not restrictions. Parsing it as RestrictedZone made a
    # drawn clean area render as a phantom no-go (and inflated the no-go legend).
    # The DEBUG dump records both fields' type codes to confirm this against a live
    # capture with a zone clean active — see doc/MAP_DATA.md §6.7.
    _log_area_fields(raw)
    zones = _parse_area_data_info(raw.get("virtual_walls"))
    cleaning_zones = _parse_cleaning_zones(raw.get("areas_info"))
    return MapSnapshot(
        grid=grid,
        robot=robot,
        charger=charger,
        path=path,
        cur_path=list(cur_path),
        objects=objects,
        rooms=rooms,
        room_chains=room_chains,
        carpets=carpets,
        zones=zones,
        cleaning_zones=cleaning_zones,
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
    except KeyError, TypeError, ValueError:
        return None


def _parse_charge_station(station: Any) -> Pose | None:
    if station is None:
        return None
    try:
        return Pose(
            x=float(station["x"]), y=float(station["y"]), phi=float(station.get("phi", 0.0))
        )
    except KeyError, TypeError, ValueError:
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


def _parse_furniture_info(raw: Any) -> list[CarpetArea]:
    """Parse RobotMap.furniture_info into CarpetArea DTOs.

    Only entries with type_id == 1550 (area carpet) are kept. Points are
    polygon corners in world metres. MessageToDict omits zero-valued proto
    fields, so id/type_id/x/y may be absent — default to 0.
    """
    if not isinstance(raw, list):
        return []
    result: list[CarpetArea] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        with contextlib.suppress(KeyError, TypeError, ValueError):
            if int(item.get("type_id", 0)) != _FURNITURE_CARPET_TYPE_ID:
                continue
            pts: list[tuple[float, float]] = []
            for p in item.get("points") or []:
                if not isinstance(p, dict):
                    continue
                with contextlib.suppress(KeyError, TypeError, ValueError):
                    pts.append((float(p.get("x", 0.0)), float(p.get("y", 0.0))))
            if pts:
                result.append(CarpetArea(carpet_id=int(item.get("id", 0)), points=pts))
    if result:
        _LOGGER.debug(
            "furniture_info carpets: %s",
            [(c.carpet_id, len(c.points), c.points[:4]) for c in result],
        )
    return result


def _log_area_fields(raw: dict[str, Any]) -> None:
    """DEBUG discriminator: dump count + type + first point of both area fields.

    Confirms which field carries the active zone-clean rectangle vs. real
    restrictions, so doc/MAP_DATA.md §6.7 can be finalised from a live capture.
    """
    if not _LOGGER.isEnabledFor(logging.DEBUG):
        return
    for field in ("virtual_walls", "areas_info"):
        items = raw.get(field)
        if not isinstance(items, list) or not items:
            continue
        summary = [
            (it.get("type"), it.get("area_index"), (it.get("points") or [None])[0])
            for it in items
            if isinstance(it, dict)
        ]
        _LOGGER.debug("map field %s: %d entries %s", field, len(items), summary)


def _parse_cleaning_zones(raw: Any) -> list[CleaningZone]:
    """Parse RobotMap.areas_info (field 10) into CleaningZone DTOs.

    Active area-clean rectangles, echoed while a zone clean runs. Same
    DeviceAreaDataInfo structure as virtual_walls but a different meaning (not a
    restriction). Lenient: keeps any entry with at least one point. See §6.7.
    """
    if not isinstance(raw, list):
        return []
    result: list[CleaningZone] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        with contextlib.suppress(KeyError, TypeError, ValueError):
            pts: list[tuple[float, float]] = []
            for p in item.get("points") or []:
                if not isinstance(p, dict):
                    continue
                with contextlib.suppress(KeyError, TypeError, ValueError):
                    pts.append((float(p.get("x", 0.0)), float(p.get("y", 0.0))))
            if pts:
                result.append(CleaningZone(zone_id=int(item.get("area_index", 0)), points=pts))
    return result


def _parse_area_data_info(raw: Any) -> list[RestrictedZone]:
    """Parse a repeated DeviceAreaDataInfo list into RestrictedZone DTOs.

    Used for RobotMap.virtual_walls (field 9) only. areas_info (field 10) is a
    separate concept (active zone-clean rectangles) and is not a restriction.
    Each entry carries a type (1=no-go, 2=line wall, 3=no-mop on the send path),
    an area_index (id), and points in world metres. Lenient by design: any entry
    with at least one point is kept and its raw type preserved, so unknown type
    codes still surface (the renderer styles known types and shows the rest).
    MessageToDict omits zero-valued proto fields, so type/area_index/x/y may be
    absent — default to 0.

    Inference: structure and type values are APK/descriptor-verified, but no live
    capture with populated areas has been confirmed; world-metre coordinates are
    inferred from DevicePointInfo being a float message (like carpets/poses), not
    int32 grid cells. See doc/MAP_DATA.md §6.7.
    """
    if not isinstance(raw, list):
        return []
    result: list[RestrictedZone] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        with contextlib.suppress(KeyError, TypeError, ValueError):
            pts: list[tuple[float, float]] = []
            for p in item.get("points") or []:
                if not isinstance(p, dict):
                    continue
                with contextlib.suppress(KeyError, TypeError, ValueError):
                    pts.append((float(p.get("x", 0.0)), float(p.get("y", 0.0))))
            if pts:
                result.append(
                    RestrictedZone(
                        zone_id=int(item.get("area_index", 0)),
                        type_id=int(item.get("type", 0)),
                        points=pts,
                    )
                )
    return result


def _parse_room_data_info(raw: Any) -> list[RoomInfo]:
    if not isinstance(raw, list):
        return []
    result: list[RoomInfo] = []
    for room in raw:
        with contextlib.suppress(KeyError, TypeError, ValueError):
            post = room.get("room_name_post") or {}
            result.append(
                RoomInfo(
                    room_id=int(room["room_id"]),
                    name=str(room.get("room_name", "")),
                    color_id=int(room.get("color_id", 1)),
                    label_x=float(post.get("x", 0.0)),
                    label_y=float(post.get("y", 0.0)),
                    is_carpet=int(room.get("meterial_id", 0)) == 1,
                )
            )
    return result


def _parse_room_chain(
    raw: Any,
    min_x: float,
    min_y: float,
    resolution: float,
) -> list[RoomChain]:
    if not isinstance(raw, list):
        return []
    result: list[RoomChain] = []
    for chain in raw:
        with contextlib.suppress(KeyError, TypeError, ValueError):
            room_id = int(chain["room_id"])
            pts_raw = chain.get("points") or []
            wall_pts: list[tuple[float, float]] = []
            sep_pts: list[tuple[float, float]] = []
            for p in pts_raw:
                with contextlib.suppress(KeyError, TypeError, ValueError):
                    val = int(p.get("value", -1))
                    wx = min_x + float(p["x"]) * resolution
                    wy = min_y + float(p["y"]) * resolution
                    if val == -1:
                        # Outer wall — used for both overlay polygon and fill.
                        wall_pts.append((wx, wy))
                    else:
                        # value=1 (separator), value=2 (unknown interior),
                        # value=3 (inner boundary) — all kept for fill only.
                        sep_pts.append((wx, wy))
            if wall_pts or sep_pts:
                result.append(
                    RoomChain(
                        room_id=room_id,
                        points=wall_pts,
                        separator_points=sep_pts,
                    )
                )
    return result
