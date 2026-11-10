# SPDX-License-Identifier: MIT
"""How the RVM 4's drawn path behaves across a clean's life, through real entry points.

The safety net for reworking the path model. Every test drives the same calls the
integration makes in production: the state-transition handler, the map-ID handler, the
map refresh and the path push. It never arms private state, and it never mocks a
handler, which is what hid the startup map-ID bug (#217). It asserts only what the
card would show: the path points and the current room.
"""

from __future__ import annotations

from dataclasses import replace as _replace
from unittest.mock import AsyncMock, MagicMock

from custom_components.karcher_home_robots._types import DeviceProperties
from custom_components.karcher_home_robots.coordinator import KarcherCoordinator, VacuumState
from custom_components.karcher_home_robots.map_data import MapSnapshot
from custom_components.karcher_home_robots.state import derive_vacuum_state
from tests.conftest import PROPS_DOCKED, PROPS_RETURNING, FakeAdapter, make_props
from tests.integration.test_map_coordinator import (
    _HALL_PT,
    _KITCHEN_PT,
    _RVM4_DEVICE,
    _id_snapshot,
    _make_coordinator,
)

_CLEANING = make_props(work_mode=1, status=0, charge_state=0, current_map_id="507")
_DOCKED = _replace(PROPS_DOCKED, current_map_id="507")
_RETURNING = _replace(PROPS_RETURNING, current_map_id="507")


def _run(
    n: int, point: tuple[float, float], flag: int = 1
) -> list[tuple[tuple[float, float], int]]:
    return [(point, flag)] * n


class _Robot:
    """One HA session against an RVM 4 whose map snapshot the test steers."""

    def __init__(self) -> None:
        self.snapshot: MapSnapshot = _id_snapshot([], 0)
        self.coord = self._new_coordinator()
        self.props: DeviceProperties | None = None

    def _new_coordinator(self) -> KarcherCoordinator:
        fake = FakeAdapter()
        fake.get_map_snapshot = AsyncMock(side_effect=lambda *a, **k: self.snapshot)  # type: ignore[method-assign]
        coord = _make_coordinator(fake, _RVM4_DEVICE)
        coord.async_update_listeners = MagicMock()  # type: ignore[method-assign]
        return coord

    async def restart_ha(
        self, props: DeviceProperties, snapshot: MapSnapshot, *, first_push_from_none: bool = False
    ) -> None:
        """HA starts while the robot is in `props`, in the order the logs show.

        The first refresh learns the map ID and fetches the map while the state is
        still unknown; the first push then arrives from a state the poll already set,
        or, when `first_push_from_none`, from no state at all.
        """
        self.snapshot = snapshot
        self.coord = self._new_coordinator()
        self.coord.data = None
        await self.coord._maybe_refresh_rooms(props)
        await self.coord._refresh_map()
        self.coord.data = props
        self.props = props
        prev = None if first_push_from_none else derive_vacuum_state(props)
        await self.coord._push_side_effects(props, prev_state=prev)

    async def push(self, props: DeviceProperties, snapshot: MapSnapshot | None = None) -> None:
        """A property push: the state changes, the map is fetched where the code does."""
        if snapshot is not None:
            self.snapshot = snapshot
        prev = derive_vacuum_state(self.props) if self.props is not None else None
        self.coord.data = props
        self.props = props
        await self.coord._push_side_effects(props, prev_state=prev)

    async def refresh(self, snapshot: MapSnapshot) -> None:
        """The 5 s map timer fetching a newer snapshot."""
        self.snapshot = snapshot
        await self.coord._refresh_map()

    def path_points(self) -> list[tuple[float, float, float, int]]:
        return self.coord._path.points

    def drawn_flags(self) -> list[int]:
        return [flag for _x, _y, _phi, flag in self.path_points()]

    def drawn_xy(self) -> set[tuple[float, float]]:
        return {(round(x, 3), round(y, 3)) for x, y, _phi, _flag in self.path_points()}


async def test_restart_mid_clean_draws_the_whole_history() -> None:
    robot = _Robot()
    await robot.restart_ha(_CLEANING, _id_snapshot(_run(100, _HALL_PT), 100))

    assert len(robot.path_points()) == 100

    await robot.refresh(_id_snapshot(_run(110, _HALL_PT), 110))
    await robot.refresh(_id_snapshot(_run(120, _HALL_PT), 120))

    assert len(robot.path_points()) == 120


async def test_first_push_from_no_state_with_cleaned_area_keeps_the_history() -> None:
    robot = _Robot()
    under_way = _replace(_CLEANING, cleaning_area=1797)
    await robot.restart_ha(
        under_way, _id_snapshot(_run(100, _HALL_PT), 100), first_push_from_none=True
    )

    assert len(robot.path_points()) == 100


async def test_first_push_from_no_state_without_cleaned_area_is_a_fresh_start() -> None:
    robot = _Robot()
    fresh = _replace(_CLEANING, cleaning_area=0)
    await robot.restart_ha(fresh, _id_snapshot(_run(100, _HALL_PT), 100), first_push_from_none=True)

    assert robot.path_points() == []


async def test_restart_mid_clean_puts_the_robot_in_its_room_on_the_first_refresh() -> None:
    robot = _Robot()
    snapshot = _id_snapshot(_run(20, _HALL_PT), 20, robot=_HALL_PT, robot_id=20)
    await robot.restart_ha(_CLEANING, snapshot)
    await robot.refresh(snapshot)

    assert robot.coord.current_room_name == "Hall"


async def test_restart_while_docked_shows_the_last_clean() -> None:
    robot = _Robot()
    await robot.restart_ha(_DOCKED, _id_snapshot(_run(40, _HALL_PT), 40))

    assert len(robot.path_points()) == 40


async def test_fresh_clean_does_not_draw_the_previous_clean() -> None:
    robot = _Robot()
    await robot.restart_ha(_DOCKED, _id_snapshot(_run(50, _HALL_PT), 50))
    stale = _id_snapshot(_run(50, _HALL_PT), 50)

    await robot.push(_CLEANING, stale)
    await robot.refresh(stale)
    assert robot.path_points() == []

    await robot.refresh(_id_snapshot([(_KITCHEN_PT, 0)], 1))
    await robot.refresh(_id_snapshot(_run(10, _KITCHEN_PT), 10))

    assert robot.drawn_xy() == {_KITCHEN_PT}


async def test_clean_whose_history_is_already_one_point_draws_its_growth() -> None:
    robot = _Robot()
    await robot.restart_ha(_DOCKED, _id_snapshot(_run(50, _HALL_PT), 50))

    await robot.push(_CLEANING, _id_snapshot([(_KITCHEN_PT, 0)], 1))
    await robot.refresh(_id_snapshot([(_KITCHEN_PT, 0), *_run(8, _HALL_PT)], 9))

    assert len(robot.path_points()) == 9  # the docked point plus the 8 grown since
    assert _HALL_PT in robot.drawn_xy()
    assert robot.coord.current_room_name == "Hall"


async def test_two_cleans_in_a_row_draw_only_the_second() -> None:
    robot = _Robot()
    first = _id_snapshot(_run(30, _HALL_PT), 30)
    await robot.push(_CLEANING, _id_snapshot([(_HALL_PT, 0)], 1))
    await robot.refresh(first)
    await robot.push(_DOCKED, first)
    assert robot.drawn_xy() == {_HALL_PT}

    await robot.push(_CLEANING, first)
    await robot.refresh(_id_snapshot([(_KITCHEN_PT, 0)], 1))
    await robot.refresh(_id_snapshot(_run(12, _KITCHEN_PT), 12))

    assert robot.drawn_xy() == {_KITCHEN_PT}


async def test_the_dock_transition_keeps_the_finished_path() -> None:
    robot = _Robot()
    done = _id_snapshot(_run(30, _HALL_PT), 30)
    await robot.push(_CLEANING, _id_snapshot([(_HALL_PT, 0)], 1))
    await robot.refresh(done)
    drawn = len(robot.path_points())

    await robot.push(_DOCKED, done)

    assert len(robot.path_points()) == drawn > 0


async def test_mopping_points_the_pushes_dropped_come_from_the_history() -> None:
    robot = _Robot()
    await robot.push(_CLEANING, _id_snapshot([(_KITCHEN_PT, 0)], 1))
    robot.coord._handle_path_push([(*_KITCHEN_PT, 0.0, 0)] * 3, 2)

    mop_history = [*_run(4, _KITCHEN_PT, 0), *_run(6, _HALL_PT)]
    await robot.refresh(_id_snapshot(mop_history, 10, robot=_HALL_PT, robot_id=10))

    assert robot.drawn_flags().count(1) == 6
    assert robot.coord.current_room_name == "Hall"


async def test_pushes_newer_than_the_history_are_kept() -> None:
    robot = _Robot()
    await robot.push(_CLEANING, _id_snapshot([(_KITCHEN_PT, 0)], 1))
    await robot.refresh(_id_snapshot([*_run(4, _KITCHEN_PT, 0), *_run(6, _HALL_PT)], 10))

    robot.coord._handle_path_push([(*_KITCHEN_PT, 0.0, 0)] * 3, 11)
    points = robot.path_points()

    assert [(round(x, 3), round(y, 3)) for x, y, _p, _f in points[-3:]] == [_KITCHEN_PT] * 3
    assert robot.drawn_flags().count(1) == 6


async def test_a_push_the_history_already_holds_is_not_drawn_twice() -> None:
    robot = _Robot()
    await robot.push(_CLEANING, _id_snapshot([(_KITCHEN_PT, 0)], 1))
    await robot.refresh(_id_snapshot([*_run(4, _KITCHEN_PT, 0), *_run(6, _HALL_PT)], 10))
    drawn = len(robot.path_points())

    robot.coord._handle_path_push([(*_HALL_PT, 0.0, 0)] * 3, 8)

    assert len(robot.path_points()) == drawn


async def test_switching_maps_mid_clean_clears_the_path() -> None:
    robot = _Robot()
    await robot.restart_ha(_CLEANING, _id_snapshot(_run(60, _HALL_PT), 60))
    assert robot.path_points()

    await robot.push(_replace(_CLEANING, current_map_id="508"), _id_snapshot([(_KITCHEN_PT, 0)], 1))

    assert _HALL_PT not in robot.drawn_xy()
    assert len(robot.path_points()) <= 1


async def test_returning_keeps_the_path_and_does_not_move_the_room() -> None:
    robot = _Robot()
    await robot.push(_CLEANING, _id_snapshot([(_HALL_PT, 0)], 1))
    await robot.refresh(_id_snapshot(_run(12, _HALL_PT), 12, robot=_HALL_PT, robot_id=12))
    assert robot.coord.current_room_name == "Hall"
    drawn = len(robot.path_points())

    back = _id_snapshot([*_run(12, _HALL_PT), *_run(12, _KITCHEN_PT)], 24)
    await robot.push(_RETURNING, back)

    assert robot.coord.vacuum_state == VacuumState.RETURNING
    assert len(robot.path_points()) >= drawn
    assert robot.coord.current_room_name != "Kitchen"


async def test_a_resume_keeps_the_path_it_had() -> None:
    robot = _Robot()
    await robot.push(_CLEANING, _id_snapshot([(_HALL_PT, 0)], 1))
    await robot.refresh(_id_snapshot(_run(12, _HALL_PT), 12))
    paused = make_props(work_mode=4, status=0, charge_state=0, current_map_id="507")
    await robot.push(paused)
    drawn = len(robot.path_points())

    robot.coord.set_resume_intent(True)
    await robot.push(_CLEANING)

    assert len(robot.path_points()) == drawn > 0


async def test_a_history_that_starts_a_new_numbering_replaces_the_path() -> None:
    robot = _Robot()
    await robot.push(_CLEANING, _id_snapshot([(_HALL_PT, 0)], 1))
    await robot.refresh(_id_snapshot(_run(30, _HALL_PT), 30))
    robot.coord._handle_path_push([(*_HALL_PT, 0.0, 1)] * 3, 31)
    assert len(robot.path_points()) == 33

    await robot.refresh(_id_snapshot(_run(12, _KITCHEN_PT), 12))

    assert len(robot.path_points()) == 12
    assert robot.drawn_xy() == {_KITCHEN_PT}


async def test_a_push_numbered_below_the_newest_one_drops_the_old_tail() -> None:
    robot = _Robot()
    await robot.push(_CLEANING, _id_snapshot([(_HALL_PT, 0)], 1))
    await robot.refresh(_id_snapshot(_run(10, _HALL_PT), 10))
    robot.coord._handle_path_push([(*_HALL_PT, 0.0, 1)] * 3, 11)
    assert len(robot.path_points()) == 13

    robot.coord._handle_path_push([(*_KITCHEN_PT, 0.0, 1)] * 3, 5)

    assert len(robot.path_points()) == 10
