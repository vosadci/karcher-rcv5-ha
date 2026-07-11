# SPDX-License-Identifier: MIT
"""Integration-owned DTOs for map data."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MapGrid:
    width: int
    height: int
    data: bytes
    resolution: float
    min_x: float
    min_y: float


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    phi: float = 0.0


@dataclass(frozen=True)
class MapObject:
    object_id: int
    type_id: int
    x: float
    y: float


@dataclass(frozen=True)
class RoomInfo:
    room_id: int
    name: str
    color_id: int
    label_x: float  # world coords for name label
    label_y: float
    is_carpet: bool = False  # meterial_id == 1 in room_data_info


@dataclass(frozen=True)
class CarpetArea:
    """Area carpet (rug) polygon from RobotMap.furniture_info (type_id 1550).

    Points are polygon corners in world metres (4 for a rectangle).
    See doc/MAP_DATA.md §6.4.
    """

    carpet_id: int
    points: list[tuple[float, float]]


@dataclass(frozen=True)
class RestrictedZone:
    """User-configured restriction from RobotMap.virtual_walls (DeviceAreaDataInfo).

    type_id: 1 = no-go area, 2 = line virtual wall, 3 = no-mop area
    (APK WallSettingActivity add-wall buttons → addWallArea type arg).
    Points are polygon corners (no-go/no-mop) or line endpoints (wall), in world
    metres. See doc/MAP_DATA.md §6.7.
    """

    zone_id: int
    type_id: int
    points: list[tuple[float, float]]


@dataclass(frozen=True)
class RoomChain:
    room_id: int
    # Outer-wall polygon in world coords (metres): value=-1 points only.
    points: list[tuple[float, float]]
    # Interior points (value=1 separator, value=2, value=3 inner boundary).
    # Used to close the polygon for colour fills; excluded from the overlay outline.
    separator_points: list[tuple[float, float]] = field(default_factory=list)


@dataclass(frozen=True)
class MapSnapshot:
    grid: MapGrid
    robot: Pose | None
    charger: Pose | None
    path: list[tuple[float, float]] = field(default_factory=list)
    objects: list[MapObject] = field(default_factory=list)
    rooms: list[RoomInfo] = field(default_factory=list)
    room_chains: list[RoomChain] = field(default_factory=list)
    carpets: list[CarpetArea] = field(default_factory=list)
    zones: list[RestrictedZone] = field(default_factory=list)
