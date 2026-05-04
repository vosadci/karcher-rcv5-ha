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
class MapSnapshot:
    grid: MapGrid
    robot: Pose | None
    charger: Pose | None
    path: list[tuple[float, float]] = field(default_factory=list)
    cur_path: list[tuple[float, float]] = field(default_factory=list)
    objects: list[MapObject] = field(default_factory=list)
