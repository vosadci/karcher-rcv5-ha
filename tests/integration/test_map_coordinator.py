# SPDX-License-Identifier: MIT
"""Integration tests for coordinator map state: _refresh_map, _handle_path_push,
cur_path reset on dock transition."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.karcher_home_robots._types import DeviceProperties
from custom_components.karcher_home_robots.coordinator import (
    KarcherCoordinator,
    _compute_room_cell_map,
    _current_room_id,
    _point_in_polygon,
)
from custom_components.karcher_home_robots.map_data import (
    MapGrid,
    MapSnapshot,
    Pose,
    RoomChain,
    RoomInfo,
)
from custom_components.karcher_home_robots.map_render import RenderLayout
from tests.integration.test_init_lifecycle import (
    PROPS_IDLE,
    TEST_DEVICE,
    FakeAdapter,
)

_GRID = MapGrid(width=120, height=120, data=b"\x00" * 3600, resolution=0.05, min_x=0.0, min_y=0.0)
_SNAPSHOT = MapSnapshot(grid=_GRID, robot=Pose(1.0, 1.0), charger=None)


def _make_coordinator(fake: FakeAdapter) -> KarcherCoordinator:
    hass = MagicMock()
    hass.loop = MagicMock()
    hass.loop.time.return_value = 1.0
    hass.async_create_task = MagicMock()
    hass.config = MagicMock()
    hass.config.time_zone = "UTC"
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
    coord.async_update_listeners.assert_called()


async def test_refresh_map_exception_does_not_raise() -> None:
    """_refresh_map swallows exceptions and leaves map_snapshot unchanged."""
    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(side_effect=RuntimeError("CDN down"))  # type: ignore[method-assign]

    coord = _make_coordinator(fake)
    coord.map_snapshot = None
    await coord._refresh_map()
    assert coord.map_snapshot is None


async def test_handle_path_push_extends_cur_path() -> None:
    """_handle_path_push extends _cur_path and updates image_last_updated."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.map_snapshot = _SNAPSHOT

    with patch("custom_components.karcher_home_robots.coordinator.dt_util") as mock_dt:
        mock_dt.utcnow.return_value = MagicMock()
        coord.async_update_listeners = MagicMock()
        coord._handle_path_push([(1.0, 2.0), (3.0, 4.0)])

    assert coord._cur_path == [(1.0, 2.0), (3.0, 4.0)]
    assert coord.image_last_updated is not None
    coord.async_update_listeners.assert_called()


async def test_handle_path_push_rebuilds_snapshot_cur_path() -> None:
    """_handle_path_push replaces cur_path on the existing MapSnapshot."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.map_snapshot = _SNAPSHOT

    with patch("custom_components.karcher_home_robots.coordinator.dt_util"):
        coord.async_update_listeners = MagicMock()
        coord._handle_path_push([(5.0, 6.0)])

    assert coord.map_snapshot is not None
    assert coord.map_snapshot.cur_path == [(5.0, 6.0)]


async def test_handle_path_push_without_snapshot_still_updates() -> None:
    """_handle_path_push works even when no map snapshot is loaded yet."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)
    coord.map_snapshot = None

    with patch("custom_components.karcher_home_robots.coordinator.dt_util"):
        coord.async_update_listeners = MagicMock()
        coord._handle_path_push([(1.0, 1.0)])

    assert coord._cur_path == [(1.0, 1.0)]
    assert coord.map_snapshot is None


async def test_cur_path_cleared_on_dock_transition() -> None:
    """When robot transitions to DOCKED, _cur_path is cleared."""
    fake = FakeAdapter()
    coord = _make_coordinator(fake)

    coord._cur_path = [(1.0, 1.0), (2.0, 2.0)]

    props_cleaning = DeviceProperties(work_mode=1, status=0, charge_state=0)
    coord.async_set_updated_data(props_cleaning)

    props_docked = DeviceProperties(work_mode=0, status=0, charge_state=1)
    ts = coord.hass.loop.time.return_value + 1.0
    coord.hass.loop.time.return_value = ts

    coord.hass.async_create_task = MagicMock()
    coord._maybe_refresh_rooms = AsyncMock()

    await coord._apply_update(props_docked, ts)

    assert coord._cur_path == []


async def test_apply_update_cleaning_map_throttle() -> None:
    """Map is not refreshed again when cleaning update arrives within throttle window."""
    fake = FakeAdapter()
    fake.get_map_snapshot = AsyncMock(return_value=_SNAPSHOT)  # type: ignore[method-assign]
    coord = _make_coordinator(fake)

    props_cleaning = DeviceProperties(work_mode=1, status=0, charge_state=0)
    coord.async_set_updated_data(props_cleaning)

    ts = 100.0
    coord.hass.loop.time.return_value = ts
    coord._last_map_refresh_ts = ts  # already refreshed this instant
    coord._maybe_refresh_rooms = AsyncMock()

    await coord._apply_update(props_cleaning, ts + 0.1)

    # get_map_snapshot should NOT have been called (throttled).
    fake.get_map_snapshot.assert_not_called()


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


# ---------------------------------------------------------------------------
# _current_room_id and _point_in_polygon (lines 446-464)
# ---------------------------------------------------------------------------


def test_current_room_id_robot_inside_polygon() -> None:
    """_current_room_id returns chain.room_id when robot is inside the polygon."""
    grid = MapGrid(width=10, height=10, data=bytes(100), resolution=0.05, min_x=0.0, min_y=0.0)
    chain = RoomChain(
        room_id=7,
        points=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
    )
    snapshot = MapSnapshot(grid=grid, robot=Pose(0.5, 0.5), charger=None, room_chains=[chain])
    assert _current_room_id(snapshot) == 7


def test_current_room_id_robot_outside_all_polygons() -> None:
    """_current_room_id returns None when robot is outside all room polygons."""
    grid = MapGrid(width=10, height=10, data=bytes(100), resolution=0.05, min_x=0.0, min_y=0.0)
    chain = RoomChain(
        room_id=7,
        points=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
    )
    snapshot = MapSnapshot(grid=grid, robot=Pose(5.0, 5.0), charger=None, room_chains=[chain])
    assert _current_room_id(snapshot) is None


def test_current_room_id_no_robot() -> None:
    """_current_room_id returns None when robot pose is absent."""
    grid = MapGrid(width=10, height=10, data=bytes(100), resolution=0.05, min_x=0.0, min_y=0.0)
    snapshot = MapSnapshot(grid=grid, robot=None, charger=None)
    assert _current_room_id(snapshot) is None


def test_point_in_polygon_inside() -> None:
    square = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
    assert _point_in_polygon(1.0, 1.0, square) is True


def test_point_in_polygon_outside() -> None:
    square = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
    assert _point_in_polygon(3.0, 3.0, square) is False


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
