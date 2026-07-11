# SPDX-License-Identifier: MIT
"""HIL: map fetch — adapter.get_map_snapshot() -> map_parser.parse_map() end to end.

The map path (adapter.get_map_snapshot() -> map_parser.parse_map() -> render)
otherwise rests entirely on documented fixtures; no other HIL test touches the
real wire format for it. This fetches a real map from the account's device and
asserts parse_map yielded a structurally valid MapSnapshot.

Requires at least one full cleaning cycle to have run, so the robot has a
generated map with rooms.

Run with:  KARCHER_HIL=1 RCV5_SN=<sn> RCV5_EMAIL=<e> RCV5_PASSWORD=<pw>
 pytest tests/hardware/ -v
"""

from __future__ import annotations

import pytest
from custom_components.karcher_home_robots.adapter import AdapterConfig, KarcherAdapter
from custom_components.karcher_home_robots.map_data import Pose

# Real RCV5 grids are documented at 120x120 (doc/MAP_DATA.md); generous bound
# to catch a parser regression (e.g. reading the wrong protobuf field) without
# being brittle to a legitimate device-specific size.
_MAX_SANE_GRID_DIM = 2000


@pytest.mark.asyncio
async def test_map_fetch_yields_structurally_valid_snapshot(
    device_sn: str,
    hil_region: str,
    hil_email: str,
    hil_password: str,
) -> None:
    """A real map fetch parses into a MapSnapshot with sane grid/room/pose data."""
    adapter = KarcherAdapter(None, AdapterConfig(region=hil_region))  # type: ignore[arg-type]
    await adapter.async_setup()
    await adapter.authenticate(hil_email, hil_password)
    devices = await adapter.get_devices()

    device = next((d for d in devices if d.sn == device_sn), None)
    if device is None:
        pytest.skip(f"device with SN={device_sn} not found on account")

    try:
        snapshot = await adapter.get_map_snapshot(device)
        if snapshot is None:
            pytest.skip("No map on device — run a full clean first")

        grid = snapshot.grid
        assert 0 < grid.width <= _MAX_SANE_GRID_DIM, f"grid.width out of sane bounds: {grid.width}"
        assert 0 < grid.height <= _MAX_SANE_GRID_DIM, (
            f"grid.height out of sane bounds: {grid.height}"
        )
        assert grid.resolution > 0, f"grid.resolution must be positive: {grid.resolution}"
        assert len(grid.data) >= grid.width * grid.height, (
            f"grid.data too short for {grid.width}x{grid.height}: {len(grid.data)} bytes"
        )

        if not snapshot.rooms:
            pytest.skip("No rooms on device map — run a full clean first")
        for room in snapshot.rooms:
            assert room.room_id > 0, f"room_id must be positive: {room.room_id}"
            assert room.name, f"room {room.room_id} has an empty name"

        world_x_hi = grid.min_x + grid.width * grid.resolution
        world_y_hi = grid.min_y + grid.height * grid.resolution

        def _assert_pose_in_bounds(pose: Pose, label: str) -> None:
            assert grid.min_x <= pose.x <= world_x_hi, (
                f"{label}.x={pose.x} outside grid bounds [{grid.min_x}, {world_x_hi}]"
            )
            assert grid.min_y <= pose.y <= world_y_hi, (
                f"{label}.y={pose.y} outside grid bounds [{grid.min_y}, {world_y_hi}]"
            )

        if snapshot.robot is not None:
            _assert_pose_in_bounds(snapshot.robot, "robot")
        if snapshot.charger is not None:
            _assert_pose_in_bounds(snapshot.charger, "charger")
    finally:
        await adapter.close()
