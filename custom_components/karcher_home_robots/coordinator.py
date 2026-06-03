# SPDX-License-Identifier: MIT
"""Coordinator -- state ownership, push/poll reconciliation, state derivation."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Mapping
from dataclasses import replace as _dataclass_replace
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.issue_registry import IssueSeverity
from homeassistant.helpers.update_coordinator import TimestampDataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ._types import DeviceProperties, RoomPreference
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
from .map_data import MapGrid, MapSnapshot
from .map_render import (
    RenderLayout,
    compute_render_layout,
    compute_room_cell_map,
    decode_room_id_grid,
)

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


class KarcherCoordinator(TimestampDataUpdateCoordinator[DeviceProperties]):
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
        self.room_preferences: list[RoomPreference] = []
        self.prefer_mode: str = "standard"  # "standard" | "customise"
        self._selected_room_id: int | None = None
        self._consecutive_failures: int = 0
        self._current_map_id: str | None = None
        self._room_retry_task: asyncio.Task[None] | None = None
        self._push_tasks: set[asyncio.Task[None]] = set()
        # Wall-clock time when the current outage started (None = healthy).
        self._outage_start: float | None = None
        self._outage_repair_created: bool = False
        self._last_throttled_log: float = 0.0
        # Map state.
        self.map_snapshot: MapSnapshot | None = None
        self.image_last_updated: datetime | None = None
        self._cur_path: list[tuple[float, float, int]] = []
        self._last_map_refresh_ts: float = 0.0
        self.current_room_name: str | None = None
        # Grid-based room cell data for the Lovelace card.
        # {room_id: [[col, row], ...]} pixel positions in the rendered image.
        self.room_cell_map: dict[int, list[tuple[int, int, int]]] = {}
        self.render_image_size: tuple[int, int, int] | None = None  # (width, height, cell_size)
        self.render_layout: RenderLayout | None = None
        # Decoded room-ID grid for cur_path → room lookup (None until first map fetch).
        # Shape: (grid.height, grid.width), dtype int16; 0 = no room.
        self._room_id_grid: Any = None

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
        await self._fetch_preference()

    async def async_shutdown(self) -> None:
        for task in list(self._push_tasks):
            task.cancel()
        if self._push_tasks:
            await asyncio.gather(*self._push_tasks, return_exceptions=True)
        if self._room_retry_task is not None:
            self._room_retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._room_retry_task
        await self._adapter.unsubscribe(self._device)
        # adapter.close() is NOT called here — the adapter may be shared with
        # other coordinators; __init__.py manages its lifetime via refcounting.
        await super().async_shutdown()

    def _handle_push(self, props: DeviceProperties) -> None:
        # Called from event loop via call_soon_threadsafe; never from the MQTT thread.
        # Capture prev_state before overwriting self.data.
        prev_state = derive_vacuum_state(self.data) if self.data is not None else None
        self._consecutive_failures = 0
        self.async_set_updated_data(props)
        task = self.hass.async_create_task(self._push_side_effects(props, prev_state))
        self._push_tasks.add(task)
        task.add_done_callback(self._push_tasks.discard)

    async def _push_side_effects(
        self, props: DeviceProperties, prev_state: VacuumState | None
    ) -> None:
        new_state = derive_vacuum_state(props)
        transitioning_to_docked = (
            prev_state is not None
            and prev_state != VacuumState.DOCKED
            and new_state == VacuumState.DOCKED
        )
        if transitioning_to_docked:
            self._cur_path = []
            self._last_map_refresh_ts = 0.0
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
        self.room_preferences = []
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
        await self._fetch_preference()

    async def _fetch_preference(self) -> None:
        """Fetch and cache room preferences from the robot.

        Requires map_id to be known; silently skips if not yet available.
        Non-fatal: a timeout or missing reply leaves room_preferences empty.
        """
        map_id_str = self._current_map_id
        if map_id_str is None:
            return
        try:
            result = await self._adapter.get_preference(self._device, int(map_id_str))
        except Exception as exc:
            _LOGGER.debug("get_preference failed: %s", exc)
            return

        raw = result.get("rooms", [])
        prefer_on = result.get("prefer_on", 0)
        self.prefer_mode = "customise" if prefer_on == 1 else "standard"

        prefs: list[RoomPreference] = []
        for row in raw:
            pref = RoomPreference.from_raw(row)
            if pref is not None:
                prefs.append(pref)

        if not prefs and self.rooms:
            # Robot has no stored preferences yet (set_preference never called).
            # Synthesise neutral defaults from the room list so entities are
            # available immediately — mirrors the app's installCustomData fallback
            # (ControlVM.java:1331: dataRoom.size() <= 0 branch).
            prefs = [
                RoomPreference(
                    room_id=r.room_id,
                    room_name=r.name,
                    mode=0,
                    wind=1,
                    water=2,
                    repeat=0,
                    check=0,
                    carpet_avoidance=0,
                )
                for r in self.rooms
            ]
            _LOGGER.debug("No stored preferences; synthesised defaults for %d rooms", len(prefs))

        self.room_preferences = prefs
        _LOGGER.debug("Loaded %d room preferences", len(prefs))

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

        self._consecutive_failures = 0
        self._handle_outage_end()

        if (
            not self.rooms
            and props.current_map_id is not None
            and (self._room_retry_task is None or self._room_retry_task.done())
        ):
            self._room_retry_task = self.hass.async_create_task(self._retry_room_fetch())

        if derive_vacuum_state(props) in (VacuumState.CLEANING, VacuumState.PAUSED):
            self._last_map_refresh_ts = self.hass.loop.time()
            await self._refresh_map()

        return props

    def _handle_outage_start(self, exc: Exception) -> None:
        """Record an outage tick, emit throttled logs, create repair issue when prolonged."""
        now = self.hass.loop.time()
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
        duration = self.hass.loop.time() - self._outage_start
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

    def _cur_path_xy(self) -> list[tuple[float, float]]:
        return [(x, y) for x, y, _ in self._cur_path]

    async def _refresh_map(self) -> None:
        """Fetch the current map snapshot from the cloud and notify listeners."""
        try:
            snapshot = await self._adapter.get_map_snapshot(self._device, self._cur_path_xy())
        except Exception as exc:
            _LOGGER.warning("Map refresh failed: %s", exc)
            return
        if snapshot is None:
            _LOGGER.debug("Map snapshot unavailable (robot has no map loaded yet)")
            return
        self.map_snapshot = snapshot
        self.image_last_updated = dt_util.utcnow()
        layout = compute_render_layout(snapshot)
        self.render_image_size = (layout.out_w, layout.out_h, layout.scale)
        self.render_layout = layout
        self.room_cell_map = compute_room_cell_map(snapshot, layout)
        grid = snapshot.grid
        if len(grid.data) >= grid.width * grid.height:
            self._room_id_grid = decode_room_id_grid(grid.data, grid.width, grid.height)
        else:
            self._room_id_grid = None
        if self.vacuum_state == VacuumState.CLEANING:
            # Fallback: set room from robot pose so the sensor isn't blank after a restart
            # mid-clean (when _cur_path is empty and no path push has arrived yet).
            if self.current_room_name is None and snapshot.robot is not None:
                room_id = _room_id_for_world_point(
                    snapshot.robot.x, snapshot.robot.y, grid, self._room_id_grid
                )
                if room_id is not None:
                    self.current_room_name = self._room_name_for_id(room_id)
        else:
            self.current_room_name = None
        self.async_update_listeners()

    def _handle_path_push(self, points: list[tuple[float, float, int]]) -> None:
        """Called from event loop via call_soon_threadsafe when property/post delivers cur_path."""
        self._cur_path.extend(points)
        existing = self.map_snapshot
        if existing is not None:
            self.map_snapshot = _dataclass_replace(existing, cur_path=self._cur_path_xy())
        # Update current room from the last cleaning point (flag != 0 = actively cleaning,
        # flag == 0 = transit). Source: MqttMessageParser.java:65, APK PathMap.java:72.
        if self.vacuum_state == VacuumState.CLEANING and existing is not None:
            cleaning_pts = [(x, y) for x, y, flag in points if flag != 0]
            if cleaning_pts:
                last_x, last_y = cleaning_pts[-1]
                room_id = _room_id_for_world_point(
                    last_x, last_y, existing.grid, self._room_id_grid
                )
                if room_id is not None:
                    self.current_room_name = self._room_name_for_id(room_id)
        self.image_last_updated = dt_util.utcnow()
        self.async_update_listeners()

    async def async_set_room_preference(self, room_id: int, updated: RoomPreference) -> None:
        """Write a single room's preference, preserving all other rooms' settings.

        Rebuilds the full room_preference list from the cached coordinator state,
        replacing the entry for room_id with `updated`. Falls back to the room
        list if no cached preferences exist yet (e.g. get_preference timed out).
        """
        map_id_str = self._current_map_id
        if map_id_str is None:
            raise ServiceValidationError("No map loaded; cannot set room preference")

        prefs_by_id = {p.room_id: p for p in self.room_preferences}
        prefs_by_id[room_id] = updated

        # Preserve the ordering from the cached preferences; append rooms that
        # have no preference entry yet (they get the updated object only if it
        # is the target room, otherwise fall back to a neutral default).
        ordered: list[RoomPreference] = []
        seen: set[int] = set()
        for pref in self.room_preferences:
            ordered.append(prefs_by_id[pref.room_id])
            seen.add(pref.room_id)
        for room in self.rooms:
            if room.room_id not in seen:
                if room.room_id == room_id:
                    ordered.append(updated)
                else:
                    ordered.append(
                        RoomPreference(
                            room_id=room.room_id,
                            room_name=room.name,
                            mode=0,
                            wind=1,
                            water=2,
                            repeat=0,
                            check=0,
                            carpet_avoidance=0,
                        )
                    )
                seen.add(room.room_id)

        raw = [p.to_raw() for p in ordered]
        await self._adapter.set_preference(self._device, int(map_id_str), raw)
        # Update local cache immediately so entities reflect the change without
        # waiting for a get_preference round-trip.
        self.room_preferences = ordered
        self.async_update_listeners()

    async def async_set_room_order(self, ordered_ids: list[int]) -> None:
        """Reorder rooms by sending preference list in requested ID sequence.

        Preserves existing per-room settings for known rooms; synthesises
        neutral defaults for any room_id not yet in the cached preferences.
        """
        map_id_str = self._current_map_id
        if map_id_str is None:
            raise ServiceValidationError("No map loaded; cannot reorder rooms")

        rooms_by_id = {r.room_id: r for r in self.rooms}
        prefs_by_id = {p.room_id: p for p in self.room_preferences}
        ordered: list[RoomPreference] = []
        for rid in ordered_ids:
            if rid in prefs_by_id:
                ordered.append(prefs_by_id[rid])
            else:
                room = rooms_by_id.get(rid)
                ordered.append(
                    RoomPreference(
                        room_id=rid,
                        room_name=room.name if room else "",
                        mode=0,
                        wind=1,
                        water=2,
                        repeat=0,
                        check=0,
                        carpet_avoidance=0,
                    )
                )

        raw = [p.to_raw() for p in ordered]
        await self._adapter.set_preference(self._device, int(map_id_str), raw)
        self.room_preferences = ordered
        self.async_update_listeners()

    async def async_set_preference_type(self, prefer_type: int) -> None:
        """Switch Standard (0) or Custom (1) cleaning mode and persist on the robot."""
        await self._adapter.set_preference_type(self._device, prefer_type)
        self.prefer_mode = "customise" if prefer_type == 1 else "standard"
        self.async_update_listeners()

    async def async_send_command(self, service: str, params: Mapping[str, Any]) -> None:
        await self._adapter.send_command(self._device, service, params)

    async def async_set_property(self, params: Mapping[str, Any]) -> None:
        await self._adapter.set_property(self._device, params)

    async def async_reset_consumable(self, consumable_type: int) -> None:
        await self._adapter.send_command(
            self._device, "reset_consumable", {"consumable": consumable_type}
        )

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


def _room_id_for_world_point(
    wx: float,
    wy: float,
    grid: MapGrid,
    room_id_grid: Any,
) -> int | None:
    """Return the room_id for world-coord (wx, wy) using the decoded grid, or None."""
    if room_id_grid is None:
        return None
    col = int((wx - grid.min_x) / grid.resolution)
    row = int((wy - grid.min_y) / grid.resolution)
    if 0 <= row < grid.height and 0 <= col < grid.width:
        rid = int(room_id_grid[row, col])
        return rid if rid > 0 else None
    return None
