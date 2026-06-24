# SPDX-License-Identifier: MIT
"""Generate a synthetic (non-device) map fixture for card screenshots.

Builds a fake 5-room apartment through the real render/derivation pipeline
(map_render.py, the same functions coordinator.py calls) so the PNG and
attribute JSON it produces are in exactly the shape karcher-vacuum-card.js
expects — without ever touching real device/cloud data.

Usage:
    ~/.venvs/ha-dev/bin/python tests/tools/generate_demo_map_fixture.py [--out-dir DIR]

Output (default ./demo_fixture/):
    demo_map.png          — floor-plan PNG (use as the image entity's picture)
    demo_attributes.json  — vacuum entity attributes (room_map, map_image_size,
                             robot_px, charger_px, cur_path_px, map_legend, ...)

To use: run a local HA dev instance with the card resource registered, then
set a vacuum entity's state via Developer Tools -> States, pasting the JSON
attributes and pointing map_image_size's backing <img> at demo_map.png served
from <config>/www/. Screenshot the card in a real browser.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from custom_components.karcher_home_robots.map_data import (
    MapGrid,
    MapSnapshot,
    Pose,
    RoomInfo,
)
from custom_components.karcher_home_robots.map_render import (
    compute_map_legend,
    compute_render_layout,
    compute_room_cell_map,
    render_map,
    world_to_pixel,
)

RESOLUTION = 0.05  # metres/cell
GRID_WIDTH = 200
GRID_HEIGHT = 300  # 2:3 portrait, closer to a real multi-room apartment scan

_WALL = 3
_FREE = 0

# Three stacked bands (top to bottom): Kitchen|Bathroom, Living room (full
# width), Bedroom|Office — gives a tall, portrait apartment shape rather than
# a single wide row.
# (name, color_id, row_start, row_end, col_start, col_end) — half-open ranges,
# raw room byte = 10 + index (must stay in the 10-59 "unvisited room" range
# decode_room_id_grid expects).
_ROOMS = [
    ("Kitchen", 1, 20, 100, 20, 99),
    ("Bathroom", 3, 20, 100, 101, 179),
    ("Living room", 2, 101, 191, 20, 179),
    ("Bedroom", 4, 192, 284, 20, 99),
    ("Office", 5, 192, 284, 101, 179),
]


def _build_grid() -> np.ndarray:
    grid = np.full((GRID_HEIGHT, GRID_WIDTH), _FREE, dtype=np.uint8)

    # Outer wall ring around the apartment footprint.
    grid[19, 20:180] = _WALL
    grid[285, 20:180] = _WALL
    grid[19:286, 19] = _WALL
    grid[19:286, 180] = _WALL

    # Internal dividers between rooms.
    grid[20:100, 100] = _WALL  # Kitchen | Bathroom
    grid[100, 20:180] = _WALL  # top band | Living room
    grid[191, 20:180] = _WALL  # Living room | bottom band
    grid[192:284, 100] = _WALL  # Bedroom | Office

    for index, (_name, _color, r0, r1, c0, c1) in enumerate(_ROOMS):
        room_byte = 10 + index + 1  # 11..15, distinct from wall dividers
        grid[r0:r1, c0:c1] = room_byte

    return grid


def _room_centre_world(r0: int, r1: int, c0: int, c1: int) -> tuple[float, float]:
    return ((c0 + c1) / 2 * RESOLUTION, (r0 + r1) / 2 * RESOLUTION)


def build_snapshot() -> MapSnapshot:
    grid_arr = _build_grid()
    grid = MapGrid(
        width=GRID_WIDTH,
        height=GRID_HEIGHT,
        data=grid_arr.tobytes(),
        resolution=RESOLUTION,
        min_x=0.0,
        min_y=0.0,
    )

    rooms = [
        RoomInfo(
            room_id=10 + index + 1,
            name=name,
            color_id=color_id,
            label_x=_room_centre_world(r0, r1, c0, c1)[0],
            label_y=_room_centre_world(r0, r1, c0, c1)[1],
        )
        for index, (name, color_id, r0, r1, c0, c1) in enumerate(_ROOMS)
    ]

    # Default state is docked: robot pose isn't used directly (build_attributes
    # derives robot_px from the charger, matching coordinator._compute_robot_px
    # for VacuumState.DOCKED), but MapSnapshot.robot must still be set.
    charger = Pose(x=30 * RESOLUTION, y=25 * RESOLUTION, phi=0.0)  # Kitchen
    robot = charger

    return MapSnapshot(
        grid=grid,
        robot=robot,
        charger=charger,
        rooms=rooms,
    )


def build_attributes(snapshot: MapSnapshot) -> dict[str, Any]:
    assert snapshot.robot is not None
    assert snapshot.charger is not None
    layout = compute_render_layout(snapshot)
    cell_map = compute_room_cell_map(snapshot, layout)
    legend = compute_map_legend(snapshot)

    def world_to_px(x: float, y: float) -> dict[str, float]:
        px, py = world_to_pixel(
            x,
            y,
            layout,
            snapshot.grid.width,
            snapshot.grid.height,
            snapshot.grid.resolution,
            snapshot.grid.min_x,
            snapshot.grid.min_y,
        )
        return {"x": px, "y": py}

    room_map: dict[str, dict[str, Any]] = {}
    rooms_attr: dict[str, str] = {}
    for room in snapshot.rooms:
        rid = str(room.room_id)
        rooms_attr[rid] = room.name
        room_map[rid] = {
            "name": room.name,
            "color_id": room.color_id,
            "cells": cell_map.get(room.room_id, []),
            "area_m2": None,
        }

    # Docked: robot snaps to a point just in front of the charger, matching
    # coordinator._compute_robot_px's VacuumState.DOCKED branch.
    charger = snapshot.charger
    robot_x = charger.x + math.cos(charger.phi) * 0.15
    robot_y = charger.y + math.sin(charger.phi) * 0.15
    robot_px = world_to_px(robot_x, robot_y)
    robot_px["phi"] = charger.phi + math.pi
    charger_px = world_to_px(charger.x, charger.y)

    cur_path_px: list[int] = []
    for x, y in snapshot.cur_path:
        p = world_to_px(x, y)
        cur_path_px.extend([int(p["x"]), int(p["y"])])

    return {
        "rooms": rooms_attr,
        "room_map": room_map,
        "room_preferences": {},
        "prefer_mode": "standard",
        "map_image_size": {
            "width": layout.out_w,
            "height": layout.out_h,
            "cell_size": layout.scale,
        },
        "robot_px": robot_px,
        "charger_px": charger_px,
        "cur_path_px": cur_path_px,
        "active_clean_room_ids": [],
        "map_legend": legend,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="demo_fixture", type=Path)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    snapshot = build_snapshot()
    png_bytes = render_map(snapshot)
    attributes = build_attributes(snapshot)

    png_path = args.out_dir / "demo_map.png"
    json_path = args.out_dir / "demo_attributes.json"
    png_path.write_bytes(png_bytes)
    json_path.write_text(json.dumps(attributes, indent=2))

    print(f"Wrote {png_path} ({len(png_bytes)} bytes)")
    print(f"Wrote {json_path}")


if __name__ == "__main__":
    main()
