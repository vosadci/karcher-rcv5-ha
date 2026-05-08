# SPDX-License-Identifier: MIT
"""Coordinator -- state ownership, push/poll reconciliation, state derivation."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time  # wall-clock monotonic for outage duration; hass.loop.time() for update ordering
from collections.abc import Mapping
from dataclasses import replace as _dataclass_replace
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.issue_registry import IssueSeverity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ._types import DeviceProperties
from .const import (
    DOMAIN,
    POLL_INTERVAL_SECONDS,
    WORK_MODE_CLEANING,
    WORK_MODE_GO_HOME,
    WORK_MODE_IDLE,
    WORK_MODE_PAUSE,
)
from .exceptions import (
    AuthError,
    PermanentError,
    ProtocolError,
    TokenRejected,
    TransientError,
    ValidationError,
)
from .map_data import MapSnapshot
from .map_render import RenderLayout, compute_render_layout, decode_room_id_grid, world_to_pixel

if TYPE_CHECKING:
    from .adapter import Device, KarcherAdapter, Room

_LOGGER = logging.getLogger(__name__)

# status value meaning "robot is on the dock".
# Source: doc/PROTOCOL.md §6, confirmed 2026-03-28.
_STATUS_DOCKED = 4

# Single poll failure does not immediately surface as UpdateFailed.
_FAILURE_THRESHOLD = 2

# Persistent repair issue is created after this duration of continuous cloud outage.
OUTAGE_REPAIR_THRESHOLD = timedelta(hours=1)

# Map grid refresh interval while cleaning (seconds).
_MAP_REFRESH_INTERVAL_CLEANING = 10.0

# After 5 min in outage, switch from per-failure INFO to one line per 10 min.
_LOG_THROTTLE_AFTER = 300.0
_LOG_THROTTLE_INTERVAL = 600.0


class VacuumState(Enum):
    """HA-visible vacuum states derived from raw device telemetry."""

    CLEANING = "cleaning"
    PAUSED = "paused"
    RETURNING = "returning"
    DOCKED = "docked"
    IDLE = "idle"
    ERROR = "error"
    UNKNOWN = "unknown"


def _is_docked(props: DeviceProperties) -> bool:
    return props.status == _STATUS_DOCKED or bool(props.charge_state)


def derive_vacuum_state(props: DeviceProperties) -> VacuumState:
    """Derive the HA vacuum state from a DeviceProperties snapshot.

    Rules (doc/PROTOCOL.md §6):
      CLEANING work_mode           → Cleaning
      GO_HOME  work_mode + docked  → Docked;  else → Returning
      PAUSE    work_mode           → Paused
      IDLE     work_mode + docked  → Docked;  fault → Error; else → Idle
      unknown  work_mode + docked  → Docked;  else → Unknown

    Error only fires when idle + faulted + not docked; transient faults
    during cleaning or returning do not surface as Error.
    """
    work_mode = props.work_mode
    docked = _is_docked(props)

    if work_mode in WORK_MODE_CLEANING:
        return VacuumState.CLEANING

    if work_mode in WORK_MODE_PAUSE:
        return VacuumState.PAUSED

    if work_mode in WORK_MODE_GO_HOME:
        return VacuumState.DOCKED if docked else VacuumState.RETURNING

    if work_mode in WORK_MODE_IDLE:
        return _derive_idle_state(props, docked)

    _LOGGER.debug("unknown work_mode %s; docked=%s", work_mode, docked)
    return VacuumState.DOCKED if docked else VacuumState.UNKNOWN


def _derive_idle_state(props: DeviceProperties, docked: bool) -> VacuumState:
    if docked:
        return VacuumState.DOCKED
    if props.fault:
        return VacuumState.ERROR
    return VacuumState.IDLE


class KarcherCoordinator(DataUpdateCoordinator[DeviceProperties]):
    """Coordinator for one Kärcher device config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        adapter: KarcherAdapter,
        device: Device,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"karcher_{device.sn}",
            update_interval=timedelta(seconds=POLL_INTERVAL_SECONDS),
            config_entry=config_entry,
        )
        self._adapter = adapter
        self._device = device
        self.rooms: list[Room] = []
        self._selected_room_id: int | None = None
        # Monotonic ts of last accepted update; guards push/poll ordering.
        self._last_update_ts: float = 0.0
        # Lock prevents a poll response from overwriting a newer push.
        self._update_lock: asyncio.Lock = asyncio.Lock()
        self._consecutive_failures: int = 0
        self._current_map_id: str | None = None
        self._room_retry_task: asyncio.Task[None] | None = None
        # Wall-clock time when the current outage started (None = healthy).
        self._outage_start: float | None = None
        self._outage_repair_created: bool = False
        self._last_throttled_log: float = 0.0
        # Map state.
        self.map_snapshot: MapSnapshot | None = None
        self.image_last_updated: datetime | None = None
        self._cur_path: list[tuple[float, float]] = []
        self._last_map_refresh_ts: float = 0.0
        self.current_room_name: str | None = None
        # Grid-based room cell data for the Lovelace card.
        # {room_id: [[col, row], ...]} pixel positions in the rendered image.
        self.room_cell_map: dict[int, list[tuple[int, int, int]]] = {}
        self.render_image_size: tuple[int, int, int] | None = None  # (width, height, cell_size)
        self.render_layout: RenderLayout | None = None

    async def async_setup(self) -> None:
        # Subscribe before first poll so no push is missed between the two.
        await self._adapter.subscribe(self._device, self._handle_push, self._handle_path_push)
        try:
            self.rooms = await self._adapter.get_rooms(self._device)
        except Exception as exc:
            _LOGGER.warning("Initial room fetch failed (will retry on map change): %s", exc)
        await self.async_config_entry_first_refresh()
        if self.data is not None:  # pragma: no branch — first_refresh raises on None data
            self._current_map_id = self.data.current_map_id
        await self._refresh_map()

    async def async_shutdown(self) -> None:
        if self._room_retry_task is not None:
            self._room_retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._room_retry_task
        await self._adapter.unsubscribe(self._device)
        await self._adapter.close()
        await super().async_shutdown()

    def _handle_push(self, props: DeviceProperties) -> None:
        # Called from event loop via call_soon_threadsafe; never from the MQTT thread.
        ts = self.hass.loop.time()
        self.hass.async_create_task(self._apply_update(props, ts))

    async def _apply_update(self, props: DeviceProperties, ts: float) -> None:
        async with self._update_lock:
            if ts <= self._last_update_ts:
                _LOGGER.debug(
                    "Discarding stale update (ts=%.3f <= last=%.3f)",
                    ts,
                    self._last_update_ts,
                )
                return
            self._last_update_ts = ts
            self._consecutive_failures = 0
            prev_state = derive_vacuum_state(self.data) if self.data is not None else None
            self.async_set_updated_data(props)

        new_state = derive_vacuum_state(props)
        transitioning_to_docked = (
            prev_state is not None
            and prev_state != VacuumState.DOCKED
            and new_state == VacuumState.DOCKED
        )
        if transitioning_to_docked:
            self._cur_path = []
            self._last_map_refresh_ts = 0.0
            self.current_room_name = None
            await self._refresh_map()
        elif new_state == VacuumState.CLEANING:
            now = self.hass.loop.time()
            if now - self._last_map_refresh_ts >= _MAP_REFRESH_INTERVAL_CLEANING:
                self._last_map_refresh_ts = now
                await self._refresh_map()

        await self._maybe_refresh_rooms(props)

    async def _maybe_refresh_rooms(self, props: DeviceProperties) -> None:
        """Re-fetch rooms and map snapshot if current_map_id changed."""
        new_map_id = props.current_map_id
        if new_map_id == self._current_map_id:
            return
        _LOGGER.debug("Map ID changed %s → %s; refreshing rooms", self._current_map_id, new_map_id)
        self._current_map_id = new_map_id
        self._cur_path = []
        self.rooms = []
        self._selected_room_id = None
        self.async_update_listeners()

        if new_map_id is None:
            return
        try:
            self.rooms = await self._adapter.get_rooms(self._device)
        except Exception as exc:
            _LOGGER.warning("Room refresh after map change failed: %s", exc)
        finally:
            self.async_update_listeners()

        await self._refresh_map()

    async def _fetch_with_reauth(self) -> DeviceProperties:
        """Fetch properties, performing one silent reauth on TokenRejected."""
        try:
            return await self._adapter.fetch_properties(self._device)
        except TokenRejected:
            try:
                await self._adapter.silent_reauth()
            except AuthError as reauth_exc:
                raise ConfigEntryAuthFailed(str(reauth_exc)) from reauth_exc
            except TransientError as reauth_exc:
                raise UpdateFailed(str(reauth_exc)) from reauth_exc
        # Reauth succeeded — retry the fetch once.
        try:
            return await self._adapter.fetch_properties(self._device)
        except AuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except (TransientError, ValidationError, ProtocolError) as exc:
            raise UpdateFailed(str(exc)) from exc

    async def _async_update_data(self) -> DeviceProperties:
        """DataUpdateCoordinator hook — fetch from device or return cached data."""
        try:
            props = await self._fetch_with_reauth()
        except AuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except PermanentError as exc:
            raise ConfigEntryError(str(exc)) from exc
        except (ValidationError, ProtocolError) as exc:
            _LOGGER.debug("Missed poll update: %s", exc)
            if self.data is not None:
                return self.data
            raise UpdateFailed(str(exc)) from exc
        except TransientError as exc:
            self._consecutive_failures += 1
            if self._consecutive_failures < _FAILURE_THRESHOLD:
                _LOGGER.debug(
                    "Poll failure %d/%d (not yet surfaced): %s",
                    self._consecutive_failures,
                    _FAILURE_THRESHOLD,
                    exc,
                )
                if self.data is not None:
                    return self.data
            self._handle_outage_start(exc)
            raise UpdateFailed(str(exc)) from exc

        ts = self.hass.loop.time()
        async with self._update_lock:
            if ts > self._last_update_ts:
                self._last_update_ts = ts
                self._consecutive_failures = 0

        self._handle_outage_end()

        if (
            not self.rooms
            and props.current_map_id is not None
            and (self._room_retry_task is None or self._room_retry_task.done())
        ):
            self._room_retry_task = self.hass.async_create_task(self._retry_room_fetch())

        return props

    def _handle_outage_start(self, exc: Exception) -> None:
        """Record an outage tick, emit throttled logs, create repair issue when prolonged."""
        now = time.monotonic()
        if self._outage_start is None:
            self._outage_start = now
            self._last_throttled_log = now
            _LOGGER.warning("Cloud unreachable: %s. Entities will become unavailable.", exc)
            return

        outage_duration = now - self._outage_start
        if (
            not self._outage_repair_created
            and outage_duration >= OUTAGE_REPAIR_THRESHOLD.total_seconds()
        ):
            self._outage_repair_created = True
            entry_id = self.config_entry.entry_id if self.config_entry else "unknown"
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"cloud_outage_persistent_{entry_id}",
                is_fixable=False,
                is_persistent=True,
                severity=IssueSeverity.WARNING,
                translation_key="cloud_outage_persistent",
            )

        if outage_duration < _LOG_THROTTLE_AFTER:
            _LOGGER.info("Cloud still unreachable: %s", exc)
        elif now - self._last_throttled_log >= _LOG_THROTTLE_INTERVAL:
            self._last_throttled_log = now
            _LOGGER.info("Cloud unreachable for %.0f min: %s", outage_duration / 60, exc)

    def _handle_outage_end(self) -> None:
        if self._outage_start is None:
            return
        duration = time.monotonic() - self._outage_start
        _LOGGER.warning(
            "Cloud reachable again after %.0f min outage.",
            duration / 60,
        )
        self._outage_start = None
        self._last_throttled_log = 0.0

        if self._outage_repair_created:
            self._outage_repair_created = False
            entry_id = self.config_entry.entry_id if self.config_entry else "unknown"
            ir.async_delete_issue(
                self.hass,
                DOMAIN,
                f"cloud_outage_persistent_{entry_id}",
            )

    async def _retry_room_fetch(self) -> None:
        try:
            rooms = await self._adapter.get_rooms(self._device)
        except Exception as exc:
            _LOGGER.debug("Room fetch retry failed: %s", exc)
            return
        if rooms:
            self.rooms = rooms
            self.async_update_listeners()

    async def _refresh_map(self) -> None:
        """Fetch the current map snapshot from the cloud and notify listeners."""
        try:
            snapshot = await self._adapter.get_map_snapshot(self._device, self._cur_path)
        except Exception as exc:
            _LOGGER.warning("Map refresh failed: %s", exc)
            return
        if snapshot is None:
            _LOGGER.debug("Map snapshot unavailable (robot has no map loaded yet)")
            return
        self.map_snapshot = snapshot
        self.image_last_updated = dt_util.utcnow()
        self.current_room_name = self._room_name_for_id(
            _current_room_id(snapshot)
        )
        layout = compute_render_layout(snapshot)
        self.render_image_size = (layout.out_w, layout.out_h, layout.scale)
        self.render_layout = layout
        self.room_cell_map = _compute_room_cell_map(snapshot, layout)
        self.async_update_listeners()

    def _handle_path_push(self, points: list[tuple[float, float]]) -> None:
        """Called from event loop via call_soon_threadsafe when cur_path/post arrives."""
        self._cur_path.extend(points)
        existing = self.map_snapshot
        if existing is not None:
            self.map_snapshot = _dataclass_replace(existing, cur_path=list(self._cur_path))
        self.image_last_updated = dt_util.utcnow()
        self.async_update_listeners()

    async def async_send_command(self, service: str, params: Mapping[str, Any]) -> None:
        await self._adapter.send_command(self._device, service, params)

    async def async_set_property(self, params: Mapping[str, Any]) -> None:
        await self._adapter.set_property(self._device, params)

    @property
    def vacuum_state(self) -> VacuumState:
        data: DeviceProperties | None = self.data
        if data is None:
            return VacuumState.UNKNOWN
        return derive_vacuum_state(data)

    @property
    def device(self) -> Device:
        return self._device

    def get_selected_room_id(self) -> int | None:
        return self._selected_room_id

    def set_selected_room_id(self, room_id: int | None) -> None:
        self._selected_room_id = room_id

    def _room_name_for_id(self, room_id: int | None) -> str | None:
        if room_id is None:
            return None
        for room in self.rooms:
            if room.room_id == room_id:
                return room.name
        if self.map_snapshot:
            for info in self.map_snapshot.rooms:
                if info.room_id == room_id:
                    return info.name
        return None


def _current_room_id(snapshot: MapSnapshot) -> int | None:
    """Return the room_id of the chain whose polygon contains the robot position.

    Uses ray-casting point-in-polygon — no image rasterisation needed.
    Returns None when the robot pose is unavailable or outside all known rooms.
    """
    if snapshot.robot is None or not snapshot.room_chains:
        return None
    px, py = snapshot.robot.x, snapshot.robot.y
    for chain in snapshot.room_chains:
        if _point_in_polygon(px, py, chain.points):
            return chain.room_id
    return None


def _point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting test: True when (x, y) is inside the polygon."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _compute_room_cell_map(
    snapshot: MapSnapshot, layout: RenderLayout
) -> dict[int, list[tuple[int, int, int]]]:
    """Return RLE-encoded room cells for each room.

    Format: {room_id: [(px_row, px_col_start, run_len), ...]}
    Each tuple encodes a horizontal run of `run_len` cells (each cell is
    `layout.scale` pixels wide/tall) starting at (px_col_start, px_row).

    Positions are in PNG pixel coordinates (after crop + scale).
    """
    import numpy as np

    grid = snapshot.grid
    n = grid.width * grid.height

    # Only full-resolution grids encode room IDs (packed 2-bit grids don't).
    if len(grid.data) < n:
        return {}

    scale = layout.scale
    room_id_grid = decode_room_id_grid(grid.data, grid.width, grid.height)

    # Collect {room_id: {px_row: sorted_col_list}} for RLE compression.
    rows_by_room: dict[int, dict[int, list[int]]] = {}

    coords = np.argwhere(room_id_grid > 0)
    for grid_row, grid_col in coords:
        room_id = int(room_id_grid[grid_row, grid_col])
        if room_id < 10:
            continue
        px_col = (int(grid_col) - layout.col0) * scale
        px_row = layout.out_h - 1 - (int(grid_row) - layout.row0) * scale

        if px_col < 0 or px_row < 0 or px_col >= layout.out_w or px_row >= layout.out_h:
            continue

        room_rows = rows_by_room.setdefault(room_id, {})
        room_rows.setdefault(px_row, []).append(px_col)

    # Build RLE spans: (px_row, col_start, run_len).
    result: dict[int, list[tuple[int, int, int]]] = {}
    for room_id, row_dict in rows_by_room.items():
        spans: list[tuple[int, int, int]] = []
        for px_row in sorted(row_dict):
            cols = sorted(row_dict[px_row])
            run_start = cols[0]
            run_end = cols[0]
            for col in cols[1:]:
                if col == run_end + scale:
                    run_end = col
                else:
                    spans.append((px_row, run_start, (run_end - run_start) // scale + 1))
                    run_start = col
                    run_end = col
            spans.append((px_row, run_start, (run_end - run_start) // scale + 1))
        result[room_id] = spans
    return result
