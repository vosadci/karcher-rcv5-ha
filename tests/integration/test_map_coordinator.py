# SPDX-License-Identifier: MIT
"""Integration tests for coordinator map state: _refresh_map, _handle_path_push,
cur_path reset on dock transition."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.karcher_home_robots._types import DeviceProperties
from custom_components.karcher_home_robots.coordinator import KarcherCoordinator
from custom_components.karcher_home_robots.map_data import MapGrid, MapSnapshot, Pose
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

    # Seed _cur_path with some points.
    coord._cur_path = [(1.0, 1.0), (2.0, 2.0)]

    # Set current state to CLEANING (work_mode in WORK_MODE_CLEANING → mode 1).
    props_cleaning = DeviceProperties(work_mode=1, status=0, charge_state=0)
    coord.async_set_updated_data(props_cleaning)

    # Now simulate transition to DOCKED (work_mode=0, charge_state=1 → docked).
    props_docked = DeviceProperties(work_mode=0, status=0, charge_state=1)
    ts = coord.hass.loop.time.return_value + 1.0
    coord.hass.loop.time.return_value = ts

    coord.hass.async_create_task = MagicMock()
    coord._maybe_refresh_rooms = AsyncMock()

    await coord._apply_update(props_docked, ts)

    assert coord._cur_path == []
