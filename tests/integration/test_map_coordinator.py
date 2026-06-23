# SPDX-License-Identifier: MIT
"""Integration tests for coordinator map state: _refresh_map, _handle_path_push,
cur_path retention on dock transition and reset on new-clean-session transition."""

from __future__ import annotations

from dataclasses import replace as _dataclass_replace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.karcher_home_robots._types import DeviceProperties
from custom_components.karcher_home_robots.coordinator import (
    KarcherCoordinator,
    _room_id_for_world_point,
)
from custom_components.karcher_home_robots.map_data import (
    MapGrid,
    MapSnapshot,
    Pose,
    RoomInfo,
)
from custom_components.karcher_home_robots.map_render import RenderLayout
from custom_components.karcher_home_robots.map_render import (
    compute_room_cell_map as _compute_room_cell_map,
)
from tests.conftest import PROPS_DOCKED, PROPS_IDLE, TEST_DEVICE, FakeAdapter

_GRID = MapGrid(width=120, height=120, data=b"\x00" * 3600, resolution=0.05, min_x=0.0, min_y=0.0)
_SNAPSHOT = MapSnapshot(grid=_GRID, robot=Pose(1.0, 1.0), charger=None)


def _make_hass(time_value: float = 1.0) -> MagicMock:
    """Mock hass with a working (inline) async_add_executor_job."""
    hass = MagicMock()
    hass.loop = MagicMock()
    hass.loop.time.return_value = time_value
    hass.async_create_task = MagicMock()
    hass.config = MagicMock()
    hass.config.time_zone = "UTC"

    async def _async_add_executor_job(func: Any, *args: Any) -> Any:
        return func(*args)

    hass.async_add_executor_job = _async_add_executor_job
    return hass


def _make_coordinator(fake: FakeAdapter) -> KarcherCoordinator:
    hass = _make_hass()
    coord = KarcherCoordinator(hass, fake, TEST_DEVICE)  # type: ignore[arg-type]
    coord.async_set_updated_data(PROPS_IDLE)
    coord.hass = hass
    return coord


async def test_refresh_map_stores_snapshot() -> None:
    """_refresh_map calls get_map_snapshot and stores the result."""
    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(return_value=_SNAPSHOT)  # type: ignore[method-assign]

    coord = _make_coordinator(fake)
    with patch("custom_components.karcher_home_robots.coordinator.dt_util") as mock_dt:
        mock_dt.utcnow.return_value = MagicMock()
        coord.async_update_listeners = MagicMock()
        await coord._refresh_map()

    assert coord.map_snapshot is _SNAPSHOT
    assert coord.image_last_updated is not None
    # Legend summary is computed in the executor and cached for the card.
    assert coord.map_legend is not None
    assert set(coord.map_legend) == {
        "no_go",
        "no_mop",
        "virtual_wall",
        "area_clean",
        "carpet",
        "objects",
    }
    coord.async_update_listeners.assert_called()


async def test_refresh_map_decodes_room_id_grid_when_data_sufficient() -> None:
    """_refresh_map builds _room_id_grid when grid data length >= width*height."""
    # 4x4 grid, all zeros except cell (1,2) = byte 60 → room_id = 10
    w, h = 4, 4
    data = bytearray(w * h)
    data[1 * w + 2] = 60  # row=1, col=2 → room_id=10
    grid = MapGrid(width=w, height=h, data=bytes(data), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(grid=grid, robot=Pose(0.1, 0.1), charger=None)

    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(return_value=snapshot)  # type: ignore[method-assign]
    coord = _make_coordinator(fake)
    coord.async_update_listeners = MagicMock()
    await coord._refresh_map()

    assert coord._room_id_grid is not None
    assert int(coord._room_id_grid[1, 2]) == 10


async def test_refresh_map_sets_current_room_from_robot_pose_when_cleaning() -> None:
    """_refresh_map populates current_room_name from robot pose when CLEANING and name is None."""
    from custom_components.karcher_home_robots._types import DeviceProperties

    # 4x4 grid; cell (row=1, col=2) = byte 60 → room_id=10
    # Robot at world (0.10, 0.05) → col=int(0.10/0.05)=2, row=int(0.05/0.05)=1
    w, h = 4, 4
    data = bytearray(w * h)
    data[1 * w + 2] = 60
    grid = MapGrid(width=w, height=h, data=bytes(data), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(
        grid=grid,
        robot=Pose(0.10, 0.05),
        charger=None,
        rooms=[RoomInfo(room_id=10, name="Kitchen", color_id=1, label_x=0.0, label_y=0.0)],
    )

    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(return_value=snapshot)  # type: ignore[method-assign]
    coord = _make_coordinator(fake)
    coord.async_set_updated_data(DeviceProperties(work_mode=1, status=0, charge_state=0))
    coord.current_room_name = None
    coord.async_update_listeners = MagicMock()
    await coord._refresh_map()

    assert coord.current_room_name == "Kitchen"


async def test_refresh_map_pose_fallback_blocked_when_room_not_in_active_set() -> None:
    """_refresh_map does not set current_room_name from robot pose when that room is not
    in _active_clean_room_ids — prevents showing 'Kitchen' when robot departs from dock
    there but Kitchen was not commanded."""
    from custom_components.karcher_home_robots._types import DeviceProperties

    # Robot pose lands in room_id=10 (Kitchen), but only room_id=20 was commanded.
    w, h = 4, 4
    data = bytearray(w * h)
    data[1 * w + 2] = 60  # byte 60 → room_id=10 (Kitchen)
    grid = MapGrid(width=w, height=h, data=bytes(data), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(
        grid=grid,
        robot=Pose(0.10, 0.05),
        charger=None,
        rooms=[
            RoomInfo(room_id=10, name="Kitchen", color_id=1, label_x=0.0, label_y=0.0),
            RoomInfo(room_id=20, name="Living Room", color_id=2, label_x=0.0, label_y=0.0),
        ],
    )

    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(return_value=snapshot)  # type: ignore[method-assign]
    coord = _make_coordinator(fake)
    coord.async_set_updated_data(DeviceProperties(work_mode=1, status=0, charge_state=0))
    coord.current_room_name = None
    coord._active_clean_room_ids = {20}  # only Living Room commanded
    coord.async_update_listeners = MagicMock()

    await coord._refresh_map()

    assert coord.current_room_name is None


async def test_refresh_map_exception_does_not_raise() -> None:
    """_refresh_map swallows exceptions and leaves map_snapshot unchanged."""
    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(side_effect=RuntimeError("CDN down"))  # type: ignore[method-assign]

    coord = _make_coordinator(fake)
    coord.map_snapshot = None
    await coord._refresh_map()
    assert coord.map_snapshot is None


async def test_handle_path_push_extends_cur_path() -> None:
    """Path push extends _cur_path and notifies listeners; must not touch image_last_updated."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.map_snapshot = _SNAPSHOT

    coord.async_update_listeners = MagicMock()
    coord._handle_path_push([(1.0, 2.0, 0.0, 0), (3.0, 4.0, 0.0, 1)])

    assert coord._cur_path == [(1.0, 2.0, 0.0, 0), (3.0, 4.0, 0.0, 1)]
    assert coord.image_last_updated is None  # path push must NOT bump image_last_updated
    coord.async_update_listeners.assert_called()


async def test_handle_path_push_updates_current_robot_pose() -> None:
    """_handle_path_push sets current_robot_pose from the last point, preserving phi."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.map_snapshot = _SNAPSHOT

    coord.async_update_listeners = MagicMock()
    coord._handle_path_push([(1.0, 2.0, 0.5, 0), (3.0, 4.0, 1.2, 1)])

    assert coord.current_robot_pose == (3.0, 4.0, 1.2)


async def test_handle_path_push_robot_pose_cleared_on_dock_transition() -> None:
    """Dock transition clears current_robot_pose."""
    from custom_components.karcher_home_robots.coordinator import VacuumState

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.current_robot_pose = (1.0, 2.0, 0.5)

    props_docked = DeviceProperties(work_mode=0, status=0, charge_state=1)
    coord._maybe_refresh_rooms = AsyncMock()
    coord._refresh_map = AsyncMock()

    await coord._push_side_effects(props_docked, prev_state=VacuumState.CLEANING)

    assert coord.current_robot_pose is None


async def test_refresh_map_skips_pose_fallback_when_room_already_known() -> None:
    """_refresh_map does not overwrite current_room_name when it is already set."""
    from custom_components.karcher_home_robots._types import DeviceProperties

    w, h = 4, 4
    data = bytearray(w * h)
    data[0 * w + 0] = 60  # room_id=10
    grid = MapGrid(width=w, height=h, data=bytes(data), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(grid=grid, robot=Pose(0.0, 0.0), charger=None)

    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(return_value=snapshot)  # type: ignore[method-assign]
    coord = _make_coordinator(fake)
    coord.async_set_updated_data(DeviceProperties(work_mode=1, status=0, charge_state=0))
    coord.current_room_name = "Living Room"  # already populated
    coord.async_update_listeners = MagicMock()
    await coord._refresh_map()

    assert coord.current_room_name == "Living Room"


async def test_handle_path_push_transit_points_do_not_update_room() -> None:
    """_handle_path_push with only flag==0 (transit) points leaves current_room_name unchanged."""
    from custom_components.karcher_home_robots._types import DeviceProperties

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.async_set_updated_data(DeviceProperties(work_mode=1, status=0, charge_state=0))
    coord.map_snapshot = _SNAPSHOT
    coord.current_room_name = None

    with patch("custom_components.karcher_home_robots.coordinator.dt_util"):
        coord.async_update_listeners = MagicMock()
        coord._handle_path_push([(1.0, 1.0, 0.0, 0), (2.0, 2.0, 0.0, 0)])  # all transit

    assert coord.current_room_name is None


async def test_handle_path_push_cleaning_point_outside_grid_leaves_room_unchanged() -> None:
    """_handle_path_push with a cleaning point outside the grid does not update room."""
    from custom_components.karcher_home_robots._types import DeviceProperties
    from custom_components.karcher_home_robots.map_render import decode_room_id_grid

    w, h = 4, 4
    grid = MapGrid(width=w, height=h, data=bytes(w * h), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(grid=grid, robot=None, charger=None)

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.async_set_updated_data(DeviceProperties(work_mode=1, status=0, charge_state=0))
    coord.map_snapshot = snapshot
    coord._room_id_grid = decode_room_id_grid(grid.data, grid.width, grid.height)
    coord.current_room_name = None

    with patch("custom_components.karcher_home_robots.coordinator.dt_util"):
        coord.async_update_listeners = MagicMock()
        # Point far outside grid bounds → room_id is None
        coord._handle_path_push([(99.0, 99.0, 0.0, 1)])

    assert coord.current_room_name is None


def _make_room_snapshot(room_id: int = 10, room_name: str = "Kitchen") -> tuple[MapSnapshot, Any]:
    """Return a (snapshot, room_id_grid) pair with one room cell at col=1, row=0."""
    from custom_components.karcher_home_robots.map_render import decode_room_id_grid

    w, h = 4, 4
    data = bytearray(w * h)
    data[0 * w + 1] = room_id  # col=1, row=0
    grid = MapGrid(width=w, height=h, data=bytes(data), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(
        grid=grid,
        robot=Pose(0.0, 0.0),
        charger=None,
        rooms=[RoomInfo(room_id=room_id, name=room_name, color_id=1, label_x=0.0, label_y=0.0)],
    )
    return snapshot, decode_room_id_grid(grid.data, grid.width, grid.height)


async def test_handle_path_push_updates_current_room_when_cleaning() -> None:
    """_handle_path_push commits room after 5 consecutive cleaning points (hysteresis N=5)."""
    snapshot, room_id_grid = _make_room_snapshot()

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.async_set_updated_data(DeviceProperties(work_mode=1, status=0, charge_state=0))
    coord.map_snapshot = snapshot
    coord._room_id_grid = room_id_grid

    with patch("custom_components.karcher_home_robots.coordinator.dt_util"):
        coord.async_update_listeners = MagicMock()
        # 5 points at world (0.05, 0.0) → col=1, row=0 → room_id=10; flag=1 (cleaning)
        for _ in range(5):
            coord._handle_path_push([(0.05, 0.0, 0.0, 1)])

    assert coord.current_room_name == "Kitchen"


async def test_handle_path_push_fewer_than_5_points_do_not_commit_room() -> None:
    """4 consecutive cleaning points in a new room are not enough to commit the change."""
    snapshot, room_id_grid = _make_room_snapshot()

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.async_set_updated_data(DeviceProperties(work_mode=1, status=0, charge_state=0))
    coord.map_snapshot = snapshot
    coord._room_id_grid = room_id_grid

    with patch("custom_components.karcher_home_robots.coordinator.dt_util"):
        coord.async_update_listeners = MagicMock()
        for _ in range(4):
            coord._handle_path_push([(0.05, 0.0, 0.0, 1)])

    assert coord.current_room_name is None
    assert coord._room_candidate == "Kitchen"
    assert coord._room_candidate_count == 4


async def test_handle_path_push_streak_resets_on_return_to_current_room() -> None:
    """If the robot returns to the current room before reaching N, the streak resets."""
    snapshot, room_id_grid = _make_room_snapshot(room_id=10, room_name="Kitchen")

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.async_set_updated_data(DeviceProperties(work_mode=1, status=0, charge_state=0))
    coord.map_snapshot = snapshot
    coord._room_id_grid = room_id_grid
    # Start already in a different room
    coord.current_room_name = "Living Room"

    with patch("custom_components.karcher_home_robots.coordinator.dt_util"):
        coord.async_update_listeners = MagicMock()
        # 3 points in Kitchen — streak building
        for _ in range(3):
            coord._handle_path_push([(0.05, 0.0, 0.0, 1)])
        assert coord._room_candidate_count == 3
        # Return to Living Room (no grid cell → room_id=None, which is skipped;
        # simulate by clearing the snapshot grid so we can test with a second room)

    # Candidate count should still be 3; room unchanged
    assert coord.current_room_name == "Living Room"
    assert coord._room_candidate_count == 3


async def test_handle_path_push_streak_resets_when_candidate_changes() -> None:
    """Switching candidate mid-streak restarts the count from 1."""
    # Two rooms: room 10 at col=1, room 20 at col=2
    w, h = 4, 4
    data = bytearray(w * h)
    data[0 * w + 1] = 10  # col=1, row=0 → room 10
    data[0 * w + 2] = 20  # col=2, row=0 → room 20
    grid = MapGrid(width=w, height=h, data=bytes(data), resolution=0.05, min_x=0.0, min_y=0.0)
    from custom_components.karcher_home_robots.map_render import decode_room_id_grid

    snapshot = MapSnapshot(
        grid=grid,
        robot=Pose(0.0, 0.0),
        charger=None,
        rooms=[
            RoomInfo(room_id=10, name="Kitchen", color_id=1, label_x=0.0, label_y=0.0),
            RoomInfo(room_id=20, name="Hallway", color_id=2, label_x=0.0, label_y=0.0),
        ],
    )

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.async_set_updated_data(DeviceProperties(work_mode=1, status=0, charge_state=0))
    coord.map_snapshot = snapshot
    coord._room_id_grid = decode_room_id_grid(grid.data, grid.width, grid.height)
    coord.current_room_name = None

    with patch("custom_components.karcher_home_robots.coordinator.dt_util"):
        coord.async_update_listeners = MagicMock()
        # 3 points in Kitchen
        for _ in range(3):
            coord._handle_path_push([(0.05, 0.0, 0.0, 1)])
        assert coord._room_candidate == "Kitchen"
        assert coord._room_candidate_count == 3
        # 1 point in Hallway — candidate switches, count resets to 1
        coord._handle_path_push([(0.10, 0.0, 0.0, 1)])

    assert coord._room_candidate == "Hallway"
    assert coord._room_candidate_count == 1
    assert coord.current_room_name is None


async def test_handle_path_push_ignores_non_commanded_rooms() -> None:
    """Points in rooms not in _active_clean_room_ids are silently ignored."""
    snapshot, room_id_grid = _make_room_snapshot(room_id=10, room_name="Kitchen")

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.async_set_updated_data(DeviceProperties(work_mode=1, status=0, charge_state=0))
    coord.map_snapshot = snapshot
    coord._room_id_grid = room_id_grid
    coord._active_clean_room_ids = {99}  # room 10 not in the commanded set

    with patch("custom_components.karcher_home_robots.coordinator.dt_util"):
        coord.async_update_listeners = MagicMock()
        for _ in range(5):
            coord._handle_path_push([(0.05, 0.0, 0.0, 1)])

    assert coord.current_room_name is None
    assert coord._room_candidate is None


async def test_handle_path_push_accepts_commanded_room() -> None:
    """Points in a room that IS in _active_clean_room_ids are accepted normally."""
    snapshot, room_id_grid = _make_room_snapshot(room_id=10, room_name="Kitchen")

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.async_set_updated_data(DeviceProperties(work_mode=1, status=0, charge_state=0))
    coord.map_snapshot = snapshot
    coord._room_id_grid = room_id_grid
    coord._active_clean_room_ids = {10, 20}  # room 10 is in the commanded set

    with patch("custom_components.karcher_home_robots.coordinator.dt_util"):
        coord.async_update_listeners = MagicMock()
        for _ in range(5):
            coord._handle_path_push([(0.05, 0.0, 0.0, 1)])

    assert coord.current_room_name == "Kitchen"


async def test_handle_path_push_rebuilds_snapshot_cur_path() -> None:
    """_handle_path_push replaces cur_path on the existing MapSnapshot (xy only, no flag)."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.map_snapshot = _SNAPSHOT

    with patch("custom_components.karcher_home_robots.coordinator.dt_util"):
        coord.async_update_listeners = MagicMock()
        coord._handle_path_push([(5.0, 6.0, 0.0, 1)])

    assert coord.map_snapshot is not None
    assert coord.map_snapshot.cur_path == [(5.0, 6.0)]


async def test_handle_path_push_without_snapshot_still_updates() -> None:
    """_handle_path_push works even when no map snapshot is loaded yet."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.map_snapshot = None

    with patch("custom_components.karcher_home_robots.coordinator.dt_util"):
        coord.async_update_listeners = MagicMock()
        coord._handle_path_push([(1.0, 1.0, 0.0, 0)])

    assert coord._cur_path == [(1.0, 1.0, 0.0, 0)]
    assert coord.map_snapshot is None


async def test_project_overlays_snapshot_fallback_phi_unflipped() -> None:
    """No path stream (e.g. docked) → robot phi comes from the cloud snapshot, used
    as-is. It is the same map-frame convention as the path-stream phi the card icon
    is tuned against; no fixed offset is applied (see _project_overlays)."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    snapshot = _dataclass_replace(_SNAPSHOT, robot=Pose(1.0, 1.0, phi=0.7))
    coord.map_snapshot = snapshot
    coord.render_layout = RenderLayout(
        col0=0, row0=0, crop_w=120, crop_h=120, scale=1, out_w=120, out_h=120
    )
    coord.current_robot_pose = None

    coord._project_overlays()

    assert coord.robot_px is not None
    assert coord.robot_px["phi"] == 0.7


async def test_project_overlays_path_stream_phi_not_flipped() -> None:
    """Path stream present (e.g. cleaning) → robot phi is used as-is, no flip."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.map_snapshot = _dataclass_replace(_SNAPSHOT, robot=Pose(1.0, 1.0, phi=0.7))
    coord.render_layout = RenderLayout(
        col0=0, row0=0, crop_w=120, crop_h=120, scale=1, out_w=120, out_h=120
    )
    coord.current_robot_pose = (1.0, 1.0, 0.3)

    coord._project_overlays()

    assert coord.robot_px is not None
    assert coord.robot_px["phi"] == 0.3


async def test_project_overlays_docked_uses_charger_derived_pose() -> None:
    """Docked → current_pose is unreliable (root cause of the recurring "backward
    at dock" bug), so pose/phi are derived from charge_station instead, matching
    the official app's algorithm for this model (RobotMapApi.parseRobotPoseInfo,
    isRobot350): position offset 0.15m along charger phi, heading = charger phi + π."""
    import math

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.async_set_updated_data(PROPS_DOCKED)
    charger = Pose(2.0, 3.0, phi=0.4)
    coord.map_snapshot = _dataclass_replace(
        _SNAPSHOT, robot=Pose(1.0, 1.0, phi=0.7), charger=charger
    )
    coord.render_layout = RenderLayout(
        col0=0, row0=0, crop_w=120, crop_h=120, scale=1, out_w=120, out_h=120
    )
    coord.current_robot_pose = (9.0, 9.0, 1.2)  # stale path-stream pose, must be ignored

    coord._project_overlays()

    assert coord.robot_px is not None
    assert coord.robot_px["phi"] == 0.4 + math.pi
    expected_x, expected_y = coord._world_to_px(
        2.0 + math.cos(0.4) * 0.15, 3.0 + math.sin(0.4) * 0.15
    ).values()  # type: ignore[union-attr]
    assert coord.robot_px["x"] == expected_x
    assert coord.robot_px["y"] == expected_y


async def test_project_overlays_docked_without_charger_falls_back() -> None:
    """Docked but no charger pose available (e.g. first map before charger is
    known) → falls back to existing path-stream / snapshot-phi behavior rather
    than crashing or leaving the robot unplaced."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.async_set_updated_data(PROPS_DOCKED)
    coord.map_snapshot = _dataclass_replace(_SNAPSHOT, robot=Pose(1.0, 1.0, phi=0.7), charger=None)
    coord.render_layout = RenderLayout(
        col0=0, row0=0, crop_w=120, crop_h=120, scale=1, out_w=120, out_h=120
    )
    coord.current_robot_pose = (1.0, 1.0, 0.3)

    coord._project_overlays()

    assert coord.robot_px is not None
    assert coord.robot_px["phi"] == 0.3


async def test_project_overlays_docked_no_layout_yields_none() -> None:
    """Docked with charger present but no render_layout → _world_to_px returns
    None, so robot_px stays None (no crash)."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.async_set_updated_data(PROPS_DOCKED)
    coord.map_snapshot = _dataclass_replace(_SNAPSHOT, charger=Pose(2.0, 3.0, phi=0.4))
    coord.render_layout = None

    coord._project_overlays()

    assert coord.robot_px is None


async def test_cur_path_retained_on_dock_transition() -> None:
    """When robot transitions to DOCKED, _cur_path is retained (post-clean review)."""
    from custom_components.karcher_home_robots.coordinator import VacuumState

    fake = FakeAdapter()
    coord = _make_coordinator(fake)

    finished_path = [(1.0, 1.0, 0.0, 1), (2.0, 2.0, 0.0, 0)]
    coord._cur_path = list(finished_path)
    coord.map_snapshot = _dataclass_replace(_SNAPSHOT, cur_path=[(1.0, 1.0), (2.0, 2.0)])

    props_docked = DeviceProperties(work_mode=0, status=0, charge_state=1)
    coord._maybe_refresh_rooms = AsyncMock()
    coord._refresh_map = AsyncMock()

    await coord._push_side_effects(props_docked, prev_state=VacuumState.CLEANING)

    assert coord._cur_path == finished_path
    assert coord.map_snapshot is not None
    assert coord.map_snapshot.cur_path == [(1.0, 1.0), (2.0, 2.0)]
    coord._refresh_map.assert_called_once()


async def test_cur_path_preserved_on_resume_intent() -> None:
    """Resume (set_resume_intent True) keeps _cur_path so the in-progress trail
    survives the PAUSED→CLEANING transition. The flag is consumed."""
    from custom_components.karcher_home_robots.coordinator import VacuumState

    fake = FakeAdapter()
    coord = _make_coordinator(fake)

    in_progress_path = [(1.0, 1.0, 0.0, 1), (2.0, 2.0, 0.0, 1)]
    coord._cur_path = list(in_progress_path)
    coord.map_snapshot = _dataclass_replace(_SNAPSHOT, cur_path=[(1.0, 1.0), (2.0, 2.0)])
    coord.set_resume_intent(True)

    props_cleaning = DeviceProperties(work_mode=1, status=0, charge_state=0)
    coord._maybe_refresh_rooms = AsyncMock()
    coord._refresh_map = AsyncMock()

    await coord._push_side_effects(props_cleaning, prev_state=VacuumState.PAUSED)

    assert coord._cur_path == in_progress_path
    assert coord.map_snapshot.cur_path == [(1.0, 1.0), (2.0, 2.0)]
    assert coord._resume_intent is False  # consumed


async def test_cur_path_cleared_on_paused_to_cleaning_without_resume_intent() -> None:
    """PAUSED→CLEANING without a resume intent is a Stop→new-clean: clear _cur_path
    so the abandoned clean's path doesn't bleed into the new room clean. Both Stop
    and Pause leave the robot paused, so only the command-set intent tells them apart."""
    from custom_components.karcher_home_robots.coordinator import VacuumState

    fake = FakeAdapter()
    coord = _make_coordinator(fake)

    stale_kitchen_path = [(1.0, 1.0, 0.0, 1), (2.0, 2.0, 0.0, 1)]
    coord._cur_path = list(stale_kitchen_path)
    coord.map_snapshot = _dataclass_replace(_SNAPSHOT, cur_path=[(1.0, 1.0), (2.0, 2.0)])
    coord._room_candidate = "Kitchen"
    coord._room_candidate_count = 3
    coord.set_resume_intent(False)

    props_cleaning = DeviceProperties(work_mode=1, status=0, charge_state=0)
    coord._maybe_refresh_rooms = AsyncMock()
    coord._refresh_map = AsyncMock()

    await coord._push_side_effects(props_cleaning, prev_state=VacuumState.PAUSED)

    assert coord._cur_path == []
    assert coord.map_snapshot.cur_path == []
    assert coord._room_candidate is None
    assert coord._room_candidate_count == 0
    coord._refresh_map.assert_called_once()


async def test_cur_path_cleared_on_idle_to_cleaning_transition() -> None:
    """IDLE→CLEANING (a normal fresh start) clears _cur_path regardless of intent."""
    from custom_components.karcher_home_robots.coordinator import VacuumState

    fake = FakeAdapter()
    coord = _make_coordinator(fake)

    stale_kitchen_path = [(1.0, 1.0, 0.0, 1), (2.0, 2.0, 0.0, 1)]
    coord._cur_path = list(stale_kitchen_path)
    coord.map_snapshot = _dataclass_replace(_SNAPSHOT, cur_path=[(1.0, 1.0), (2.0, 2.0)])
    coord._room_candidate = "Kitchen"
    coord._room_candidate_count = 3

    props_cleaning = DeviceProperties(work_mode=1, status=0, charge_state=0)
    coord._maybe_refresh_rooms = AsyncMock()
    coord._refresh_map = AsyncMock()

    await coord._push_side_effects(props_cleaning, prev_state=VacuumState.IDLE)

    assert coord._cur_path == []
    assert coord.map_snapshot.cur_path == []
    assert coord._room_candidate is None
    assert coord._room_candidate_count == 0
    coord._refresh_map.assert_called_once()


async def test_cur_path_not_cleared_on_cleaning_to_cleaning() -> None:
    """CLEANING→CLEANING (throttled update) must NOT clear _cur_path."""
    from custom_components.karcher_home_robots.coordinator import VacuumState

    fake = FakeAdapter()
    coord = _make_coordinator(fake)

    existing_path = [(1.0, 1.0, 0.0, 1), (2.0, 2.0, 0.0, 1)]
    coord._cur_path = list(existing_path)

    props_cleaning = DeviceProperties(work_mode=1, status=0, charge_state=0)
    coord.async_set_updated_data(props_cleaning)
    coord._maybe_refresh_rooms = AsyncMock()
    coord._refresh_map = AsyncMock()
    coord._last_map_refresh_ts = 100.0
    coord.hass.loop.time.return_value = 100.5  # within throttle window

    await coord._push_side_effects(props_cleaning, prev_state=VacuumState.CLEANING)

    assert coord._cur_path == existing_path
    coord._refresh_map.assert_not_called()


async def test_debounce_state_cleared_on_dock_transition() -> None:
    """Dock transition resets the room hysteresis state and active clean room set."""
    from custom_components.karcher_home_robots.coordinator import VacuumState

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord._room_candidate = "Kitchen"
    coord._room_candidate_count = 3
    coord._active_clean_room_ids = {10, 20}

    props_docked = DeviceProperties(work_mode=0, status=0, charge_state=1)
    coord._maybe_refresh_rooms = AsyncMock()
    coord._refresh_map = AsyncMock()

    await coord._push_side_effects(props_docked, prev_state=VacuumState.CLEANING)

    assert coord._room_candidate is None
    assert coord._room_candidate_count == 0
    assert coord._active_clean_room_ids == set()


async def test_push_side_effects_cleaning_map_throttle() -> None:
    """Map is not refreshed again when cleaning update arrives within throttle window."""
    from custom_components.karcher_home_robots.coordinator import VacuumState

    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(return_value=_SNAPSHOT)  # type: ignore[method-assign]
    coord = _make_coordinator(fake)

    props_cleaning = DeviceProperties(work_mode=1, status=0, charge_state=0)
    coord.async_set_updated_data(props_cleaning)

    ts = 100.0
    coord.hass.loop.time.return_value = ts
    coord._last_map_refresh_ts = ts  # already refreshed this instant
    coord._maybe_refresh_rooms = AsyncMock()

    await coord._push_side_effects(props_cleaning, prev_state=VacuumState.CLEANING)

    # get_map_snapshot should NOT have been called (throttled).
    fake.get_map_snapshot.assert_not_called()


async def test_push_side_effects_cleaning_map_refreshes_after_throttle_window() -> None:
    """Map is refreshed when a CLEANING→CLEANING update arrives after the throttle window."""
    from custom_components.karcher_home_robots.coordinator import (
        _MAP_REFRESH_INTERVAL_CLEANING,
        VacuumState,
    )

    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(return_value=_SNAPSHOT)  # type: ignore[method-assign]
    coord = _make_coordinator(fake)

    props_cleaning = DeviceProperties(work_mode=1, status=0, charge_state=0)
    coord.async_set_updated_data(props_cleaning)

    ts = 100.0
    coord._last_map_refresh_ts = ts
    coord.hass.loop.time.return_value = ts + _MAP_REFRESH_INTERVAL_CLEANING + 1.0
    coord._maybe_refresh_rooms = AsyncMock()

    await coord._push_side_effects(props_cleaning, prev_state=VacuumState.CLEANING)

    fake.get_map_snapshot.assert_called_once()


async def test_push_side_effects_returning_triggers_immediate_refresh() -> None:
    """CLEANING→RETURNING transition refreshes the map immediately."""
    from custom_components.karcher_home_robots.coordinator import VacuumState

    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(return_value=_SNAPSHOT)  # type: ignore[method-assign]
    coord = _make_coordinator(fake)

    props_returning = DeviceProperties(work_mode=5, status=0, charge_state=0)
    coord.async_set_updated_data(props_returning)
    coord._last_map_refresh_ts = 100.0  # recently refreshed — should still fire
    coord.hass.loop.time.return_value = 100.5
    coord._maybe_refresh_rooms = AsyncMock()

    await coord._push_side_effects(props_returning, prev_state=VacuumState.CLEANING)

    fake.get_map_snapshot.assert_called_once()


async def test_push_side_effects_returning_throttles_subsequent_refreshes() -> None:
    """Subsequent RETURNING→RETURNING pushes respect the throttle interval."""
    from custom_components.karcher_home_robots.coordinator import VacuumState

    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(return_value=_SNAPSHOT)  # type: ignore[method-assign]
    coord = _make_coordinator(fake)

    props_returning = DeviceProperties(work_mode=5, status=0, charge_state=0)
    coord.async_set_updated_data(props_returning)

    ts = 100.0
    coord.hass.loop.time.return_value = ts
    coord._last_map_refresh_ts = ts  # refreshed this instant
    coord._maybe_refresh_rooms = AsyncMock()

    # Same state → same state (not a CLEANING→RETURNING transition)
    await coord._push_side_effects(props_returning, prev_state=VacuumState.RETURNING)

    fake.get_map_snapshot.assert_not_called()


async def test_push_side_effects_returning_refreshes_after_throttle_window() -> None:
    """RETURNING→RETURNING triggers _refresh_map once the throttle window has elapsed."""
    from custom_components.karcher_home_robots.coordinator import VacuumState

    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(return_value=_SNAPSHOT)  # type: ignore[method-assign]
    coord = _make_coordinator(fake)

    props_returning = DeviceProperties(work_mode=5, status=0, charge_state=0)
    coord.async_set_updated_data(props_returning)
    coord._maybe_refresh_rooms = AsyncMock()

    # Simulate last refresh 11 s ago (> _MAP_REFRESH_INTERVAL_RETURNING = 10 s)
    coord.hass.loop.time.return_value = 111.0
    coord._last_map_refresh_ts = 100.0

    await coord._push_side_effects(props_returning, prev_state=VacuumState.RETURNING)

    fake.get_map_snapshot.assert_called_once()


async def test_handle_path_push_empty_points_does_not_update_pose() -> None:
    """_handle_path_push with an empty list does not set current_robot_pose."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.map_snapshot = _SNAPSHOT
    coord.current_robot_pose = None

    with patch("custom_components.karcher_home_robots.coordinator.dt_util"):
        coord.async_update_listeners = MagicMock()
        coord._handle_path_push([])

    assert coord.current_robot_pose is None


async def test_handle_path_push_updates_robot_pose_when_not_cleaning() -> None:
    """_handle_path_push updates current_robot_pose even outside CLEANING state (e.g. RETURNING)."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    # RETURNING state
    coord.async_set_updated_data(DeviceProperties(work_mode=5, status=0, charge_state=0))
    coord.map_snapshot = _SNAPSHOT

    with patch("custom_components.karcher_home_robots.coordinator.dt_util"):
        coord.async_update_listeners = MagicMock()
        coord._handle_path_push([(1.0, 2.0, 0.7, 0)])

    assert coord.current_robot_pose == (1.0, 2.0, 0.7)
    # Room should not be updated outside CLEANING
    assert coord.current_room_name is None


async def test_handle_path_push_streak_reset_when_point_matches_current_room() -> None:
    """Cleaning point in current room resets a pending candidate streak."""
    snapshot, room_id_grid = _make_room_snapshot(room_id=10, room_name="Kitchen")

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.async_set_updated_data(DeviceProperties(work_mode=1, status=0, charge_state=0))
    coord.map_snapshot = snapshot
    coord._room_id_grid = room_id_grid
    coord.current_room_name = "Kitchen"  # already in Kitchen
    coord._room_candidate = "Hallway"
    coord._room_candidate_count = 3

    with patch("custom_components.karcher_home_robots.coordinator.dt_util"):
        coord.async_update_listeners = MagicMock()
        # Cleaning point back in Kitchen — should clear the pending streak
        coord._handle_path_push([(0.05, 0.0, 0.0, 1)])

    assert coord._room_candidate is None
    assert coord._room_candidate_count == 0
    assert coord.current_room_name == "Kitchen"


async def test_get_selected_room_ids_returns_copy() -> None:
    """get_selected_room_ids returns the current selection as a set copy."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.set_selected_room_ids([1, 2, 3])

    result = coord.get_selected_room_ids()

    assert result == {1, 2, 3}
    # Mutating the returned set does not affect internal state
    result.add(99)
    assert coord.get_selected_room_ids() == {1, 2, 3}


# ---------------------------------------------------------------------------
# _room_name_for_id: snapshot.rooms fallback path (lines 428-435)
# ---------------------------------------------------------------------------


async def test_room_name_for_id_falls_back_to_snapshot_rooms() -> None:
    """_room_name_for_id finds a name in map_snapshot.rooms when not in self.rooms."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)

    grid = MapGrid(width=5, height=5, data=bytes(25), resolution=0.05, min_x=0.0, min_y=0.0)
    room_info = RoomInfo(room_id=42, name="Bedroom", color_id=1, label_x=0.0, label_y=0.0)
    coord.map_snapshot = MapSnapshot(grid=grid, robot=None, charger=None, rooms=[room_info])
    coord.rooms = []  # not in self.rooms

    name = coord._room_name_for_id(42)
    assert name == "Bedroom"


async def test_room_name_for_id_found_in_self_rooms() -> None:
    """_room_name_for_id returns name directly from self.rooms when present."""
    from custom_components.karcher_home_robots.adapter import Room

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.rooms = [Room(room_id=7, name="Kitchen")]
    coord.map_snapshot = None

    assert coord._room_name_for_id(7) == "Kitchen"


async def test_room_name_for_id_not_in_snapshot_rooms_returns_none() -> None:
    """_room_name_for_id returns None when room_id is absent from both lists."""
    from custom_components.karcher_home_robots.adapter import Room

    fake = FakeAdapter()
    coord = _make_coordinator(fake)

    grid = MapGrid(width=5, height=5, data=bytes(25), resolution=0.05, min_x=0.0, min_y=0.0)
    room_info = RoomInfo(room_id=10, name="Living", color_id=2, label_x=0.0, label_y=0.0)
    coord.map_snapshot = MapSnapshot(grid=grid, robot=None, charger=None, rooms=[room_info])
    # self.rooms has a room but it doesn't match 99; snapshot.rooms also doesn't.
    coord.rooms = [Room(room_id=10, name="Living")]

    assert coord._room_name_for_id(99) is None  # 99 not in self.rooms nor snapshot.rooms


async def test_room_name_for_id_returns_none_for_unknown() -> None:
    """_room_name_for_id returns None when room_id is in neither list."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.rooms = []
    coord.map_snapshot = None

    assert coord._room_name_for_id(99) is None


async def test_room_name_for_id_none_returns_none() -> None:
    """_room_name_for_id(None) returns None immediately."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    assert coord._room_name_for_id(None) is None


# ---------------------------------------------------------------------------
# _room_id_for_world_point: grid-based lookup
# ---------------------------------------------------------------------------


def _make_room_id_grid(room_id: int, row: int, col: int, width: int, height: int) -> Any:
    import numpy as np

    g = np.zeros((height, width), dtype="int16")
    g[row, col] = room_id
    return g


def test_room_id_for_world_point_hit() -> None:
    """Returns room_id when world coord maps to a populated grid cell."""
    import numpy as np

    grid = MapGrid(width=10, height=10, data=b"\x00" * 100, resolution=0.05, min_x=0.0, min_y=0.0)
    room_grid = np.zeros((10, 10), dtype="int16")
    room_grid[1, 2] = 5  # row=1, col=2 → world x=2*0.05=0.10, y=1*0.05=0.05
    assert _room_id_for_world_point(0.10, 0.05, grid, room_grid) == 5


def test_room_id_for_world_point_miss() -> None:
    """Returns None when grid cell has room_id==0."""
    import numpy as np

    grid = MapGrid(width=10, height=10, data=b"\x00" * 100, resolution=0.05, min_x=0.0, min_y=0.0)
    room_grid = np.zeros((10, 10), dtype="int16")
    assert _room_id_for_world_point(0.10, 0.05, grid, room_grid) is None


def test_room_id_for_world_point_out_of_bounds() -> None:
    """Returns None when world coord is outside grid bounds."""
    import numpy as np

    grid = MapGrid(width=5, height=5, data=b"\x00" * 25, resolution=0.05, min_x=0.0, min_y=0.0)
    room_grid = np.ones((5, 5), dtype="int16")
    assert _room_id_for_world_point(99.0, 99.0, grid, room_grid) is None


def test_room_id_for_world_point_none_grid() -> None:
    """Returns None when room_id_grid is None (packed grid, no room data)."""
    grid = MapGrid(width=5, height=5, data=b"\x00" * 25, resolution=0.05, min_x=0.0, min_y=0.0)
    assert _room_id_for_world_point(0.1, 0.1, grid, None) is None


def test_room_id_for_world_point_with_min_offset() -> None:
    """World coords with non-zero min_x/min_y are correctly mapped to grid cells."""
    import numpy as np

    grid = MapGrid(width=10, height=10, data=b"\x00" * 100, resolution=0.05, min_x=1.0, min_y=2.0)
    room_grid = np.zeros((10, 10), dtype="int16")
    room_grid[0, 0] = 3  # world x=1.0+0*0.05=1.0, y=2.0+0*0.05=2.0
    assert _room_id_for_world_point(1.0, 2.0, grid, room_grid) == 3


# ---------------------------------------------------------------------------
# _compute_room_cell_map: out-of-bounds skip and room_id < min skip (lines 497, 502)
# ---------------------------------------------------------------------------


def test_compute_room_cell_map_out_of_crop_cells_skipped() -> None:
    """Cells that project outside the crop window are silently skipped."""
    # 5x5 grid, room cell at position (0,0). Layout crops to col0=2,row0=2
    # so grid_col=0 → px_col=(0-2)*scale = negative → skipped.
    data = bytearray(25)
    data[0] = 12  # room 12 at grid (row=0, col=0)
    grid = MapGrid(width=5, height=5, data=bytes(data), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(grid=grid, robot=None, charger=None)
    layout = RenderLayout(col0=2, row0=2, crop_w=3, crop_h=3, scale=2, out_w=6, out_h=6)
    result = _compute_room_cell_map(snapshot, layout)
    assert 12 not in result


# ---------------------------------------------------------------------------
# _compute_room_cell_map: non-adjacent RLE span flush (lines 519-521)
# ---------------------------------------------------------------------------


def test_compute_room_cell_map_non_adjacent_cells_produce_multiple_spans() -> None:
    """Non-adjacent cells in the same row flush to separate RLE spans."""
    # 5x1 grid with room 12 at col 0 and col 4 (gap at cols 1-3).
    data = bytearray(5)
    data[0] = 12
    data[4] = 12
    grid = MapGrid(width=5, height=1, data=bytes(data), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(grid=grid, robot=None, charger=None)
    layout = RenderLayout(col0=0, row0=0, crop_w=5, crop_h=1, scale=1, out_w=5, out_h=1)
    result = _compute_room_cell_map(snapshot, layout)
    assert 12 in result
    # Two non-adjacent cells must produce two separate spans.
    assert len(result[12]) == 2


# ---------------------------------------------------------------------------
# Poll-path map refresh during CLEANING / PAUSED
# ---------------------------------------------------------------------------


async def test_async_update_data_refreshes_map_when_cleaning() -> None:
    """_async_update_data calls _refresh_map when state is CLEANING."""
    from custom_components.karcher_home_robots.coordinator import KarcherCoordinator
    from tests.conftest import PROPS_CLEANING, FakeAdapter

    fake = FakeAdapter(props=PROPS_CLEANING)
    fake.get_map_snapshot = AsyncMock(return_value=_SNAPSHOT)  # type: ignore[method-assign]

    hass = _make_hass(time_value=1000.0)

    coord = KarcherCoordinator(hass, fake, TEST_DEVICE)  # type: ignore[arg-type]
    coord.async_set_updated_data(PROPS_CLEANING)
    coord.async_update_listeners = MagicMock()

    with patch("custom_components.karcher_home_robots.coordinator.dt_util"):
        result = await coord._async_update_data()

    assert result is PROPS_CLEANING
    fake.get_map_snapshot.assert_called_once()
    assert coord._last_map_refresh_ts == 1000.0


async def test_async_update_data_refreshes_map_when_paused() -> None:
    """_async_update_data calls _refresh_map when state is PAUSED."""
    from custom_components.karcher_home_robots.coordinator import KarcherCoordinator
    from tests.conftest import PROPS_PAUSED, FakeAdapter

    fake = FakeAdapter(props=PROPS_PAUSED)
    fake.get_map_snapshot = AsyncMock(return_value=_SNAPSHOT)  # type: ignore[method-assign]

    hass = _make_hass(time_value=500.0)

    coord = KarcherCoordinator(hass, fake, TEST_DEVICE)  # type: ignore[arg-type]
    coord.async_set_updated_data(PROPS_PAUSED)
    coord.async_update_listeners = MagicMock()

    with patch("custom_components.karcher_home_robots.coordinator.dt_util"):
        result = await coord._async_update_data()

    assert result is PROPS_PAUSED
    fake.get_map_snapshot.assert_called_once()


async def test_async_update_data_no_map_refresh_when_idle() -> None:
    """_async_update_data does not call _refresh_map when state is IDLE."""
    from custom_components.karcher_home_robots.coordinator import KarcherCoordinator
    from tests.conftest import PROPS_IDLE, FakeAdapter

    fake = FakeAdapter(props=PROPS_IDLE)
    fake.get_map_snapshot = AsyncMock(return_value=_SNAPSHOT)  # type: ignore[method-assign]

    hass = _make_hass()

    coord = KarcherCoordinator(hass, fake, TEST_DEVICE)  # type: ignore[arg-type]
    coord.async_set_updated_data(PROPS_IDLE)
    coord.async_update_listeners = MagicMock()

    result = await coord._async_update_data()

    assert result is PROPS_IDLE
    fake.get_map_snapshot.assert_not_called()


async def test_refresh_map_seeds_cur_path_from_history_pose() -> None:
    """_refresh_map seeds _cur_path from snapshot.path when _cur_path is empty."""
    history = [(1.0, 2.0), (3.0, 4.0)]
    snapshot = MapSnapshot(grid=_GRID, robot=None, charger=None, path=history)

    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(return_value=snapshot)  # type: ignore[method-assign]
    coord = _make_coordinator(fake)
    coord.async_update_listeners = MagicMock()
    await coord._refresh_map()

    assert len(coord._cur_path) == 2
    assert coord._cur_path[0] == (1.0, 2.0, 0.0, 1)
    assert coord._cur_path[1] == (3.0, 4.0, 0.0, 1)
    assert coord.map_snapshot is not None
    assert coord.map_snapshot.cur_path == [(1.0, 2.0), (3.0, 4.0)]


async def test_refresh_map_does_not_overwrite_live_cur_path() -> None:
    """_refresh_map leaves _cur_path alone when it is already populated."""
    history = [(1.0, 2.0), (3.0, 4.0)]
    snapshot = MapSnapshot(grid=_GRID, robot=None, charger=None, path=history)

    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(return_value=snapshot)  # type: ignore[method-assign]
    coord = _make_coordinator(fake)
    coord._cur_path = [(9.0, 9.0, 0.5, 1)]  # pre-populated live path
    coord.async_update_listeners = MagicMock()
    await coord._refresh_map()

    assert len(coord._cur_path) == 1
    assert coord._cur_path[0] == (9.0, 9.0, 0.5, 1)
    # Fresh snapshots arrive with cur_path=[]; the live path is carried over.
    assert coord.map_snapshot is not None
    assert coord.map_snapshot.cur_path == [(9.0, 9.0)]


async def test_refresh_map_history_seed_is_one_shot() -> None:
    """Only the first successful _refresh_map seeds from history_pose.

    Regression: history_pose still carries the previous clean's path at clean
    start; seeding on every refresh resurrected it into the live clean.
    """
    history = [(1.0, 2.0), (3.0, 4.0)]
    snapshot = MapSnapshot(grid=_GRID, robot=None, charger=None, path=history)

    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(return_value=snapshot)  # type: ignore[method-assign]
    coord = _make_coordinator(fake)
    coord.async_update_listeners = MagicMock()

    await coord._refresh_map()
    assert len(coord._cur_path) == 2  # startup recovery seeds

    coord._cur_path = []  # e.g. cleared at clean start
    await coord._refresh_map()
    assert coord._cur_path == []  # stale history must not be re-seeded
    assert coord.map_snapshot is not None
    assert coord.map_snapshot.cur_path == []


async def test_clean_start_transition_disables_history_seed() -> None:
    """A clean-start transition before the first map fetch disables seeding."""
    from custom_components.karcher_home_robots.coordinator import VacuumState

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    assert coord._seed_cur_path_from_history is True

    props_cleaning = DeviceProperties(work_mode=1, status=0, charge_state=0)
    coord._maybe_refresh_rooms = AsyncMock()
    coord._refresh_map = AsyncMock()

    await coord._push_side_effects(props_cleaning, prev_state=VacuumState.DOCKED)

    assert coord._cur_path == []
    assert coord._seed_cur_path_from_history is False


async def test_push_side_effects_clears_stale_cleaning_zone_on_pause() -> None:
    """A transition that wouldn't otherwise refresh the map still does so when a
    cleaning-zone rectangle is on the map but the live state says to hide it."""
    from custom_components.karcher_home_robots.coordinator import VacuumState

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord._map_has_cleaning_zone = True
    coord._maybe_refresh_rooms = AsyncMock()
    coord._refresh_map = AsyncMock()

    props_paused = DeviceProperties(work_mode=2, status=0, charge_state=0)
    await coord._push_side_effects(props_paused, prev_state=VacuumState.CLEANING)

    coord._refresh_map.assert_called_once()


async def test_push_side_effects_no_extra_refresh_when_no_stale_zone() -> None:
    """No extra _refresh_map call when there is no lingering cleaning-zone rectangle."""
    from custom_components.karcher_home_robots.coordinator import VacuumState

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord._map_has_cleaning_zone = False
    coord._maybe_refresh_rooms = AsyncMock()
    coord._refresh_map = AsyncMock()

    props_paused = DeviceProperties(work_mode=2, status=0, charge_state=0)
    await coord._push_side_effects(props_paused, prev_state=VacuumState.CLEANING)

    coord._refresh_map.assert_not_called()


async def test_refresh_map_strips_lingering_cleaning_zone() -> None:
    """_refresh_map clears cleaning_zones from the stored snapshot once the zone
    clean is no longer actively running (areas_info lingers after completion)."""
    from custom_components.karcher_home_robots.map_data import CleaningZone

    grid = MapGrid(width=4, height=4, data=b"\x00" * 16, resolution=0.05, min_x=0.0, min_y=0.0)
    zone = CleaningZone(zone_id=1, points=[(0.0, 0.0), (1.0, 1.0)])
    snapshot = MapSnapshot(grid=grid, robot=Pose(0.1, 0.1), charger=None, cleaning_zones=[zone])

    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(return_value=snapshot)  # type: ignore[method-assign]
    coord = _make_coordinator(fake)
    coord.async_update_listeners = MagicMock()
    # Idle (PROPS_IDLE from _make_coordinator) is not an active zone clean.
    await coord._refresh_map()

    assert coord.map_snapshot is not None
    assert coord.map_snapshot.cleaning_zones == []
    assert coord._map_has_cleaning_zone is False


async def test_refresh_map_keeps_active_cleaning_zone() -> None:
    """_refresh_map keeps cleaning_zones intact while the zone clean is actively running."""
    from custom_components.karcher_home_robots.map_data import CleaningZone

    grid = MapGrid(width=4, height=4, data=b"\x00" * 16, resolution=0.05, min_x=0.0, min_y=0.0)
    zone = CleaningZone(zone_id=1, points=[(0.0, 0.0), (1.0, 1.0)])
    snapshot = MapSnapshot(grid=grid, robot=Pose(0.1, 0.1), charger=None, cleaning_zones=[zone])

    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(return_value=snapshot)  # type: ignore[method-assign]
    coord = _make_coordinator(fake)
    coord.async_update_listeners = MagicMock()
    props_zone_cleaning = DeviceProperties(work_mode=30, status=0, charge_state=0)
    coord.async_set_updated_data(props_zone_cleaning)

    await coord._refresh_map()

    assert coord.map_snapshot is not None
    assert coord.map_snapshot.cleaning_zones == [zone]
    assert coord._map_has_cleaning_zone is True


async def test_async_zone_clean_sends_zone_points_and_starts_clean() -> None:
    """async_zone_clean converts pixel corners to world metres and sends the two
    commands the robot expects: set_zone_points then set_zone_clean."""
    grid = MapGrid(width=20, height=20, data=b"\x00" * 400, resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(grid=grid, robot=Pose(0.1, 0.1), charger=None)

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.map_snapshot = snapshot
    coord.render_layout = RenderLayout(
        col0=0, row0=0, crop_w=20, crop_h=20, scale=10, out_w=200, out_h=200
    )

    await coord.async_zone_clean((0.0, 0.0, 100.0, 100.0))

    assert [name for name, _ in fake.commands_sent] == ["set_zone_points", "set_zone_clean"]
    zone_points_call = fake.commands_sent[0][1]
    assert len(zone_points_call["zone_points"]) == 8
    assert fake.commands_sent[1][1] == {"ctrl_value": 1}


async def test_async_zone_clean_raises_when_map_not_loaded() -> None:
    """async_zone_clean raises ServiceValidationError when there is no map yet."""
    import pytest
    from homeassistant.exceptions import ServiceValidationError

    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.map_snapshot = None
    coord.render_layout = None

    with pytest.raises(ServiceValidationError):
        await coord.async_zone_clean((0.0, 0.0, 100.0, 100.0))

    assert fake.commands_sent == []
