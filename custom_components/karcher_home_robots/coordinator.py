# SPDX-License-Identifier: MIT
"""Coordinator -- state ownership and push/poll reconciliation.

Vacuum-state derivation lives in state.py; pure map post-processing in
map_render.py. This module owns the live state and the timing/race rules
around it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.issue_registry import IssueSeverity
from homeassistant.helpers.update_coordinator import TimestampDataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ._outage import OutageTracker
from ._path import PathProjection
from ._repairs import RepairAction
from ._room_names import RoomNameWatcher
from ._types import DeviceProperties, RoomPreference
from .const import DOMAIN, POLL_INTERVAL_SECONDS, WORK_MODE_ZONE_CLEAN
from .exceptions import (
    AuthError,
    PermanentError,
    ProtocolError,
    TokenRejected,
    TransientError,
    ValidationError,
)
from .map_data import MapSnapshot, RoomInfo
from .map_render import (
    OBJECT_TYPE_CARPET,
    DerivedMapState,
    RenderLayout,
    derive_map_state,
    pixel_to_world,
    room_id_for_world_point,
    world_to_pixel,
)
from .state import VacuumState, derive_vacuum_state

if TYPE_CHECKING:
    from .adapter import Device, KarcherAdapter, Room

_LOGGER = logging.getLogger(__name__)

# Single poll failure does not immediately surface as UpdateFailed.
_FAILURE_THRESHOLD = 2

# Persistent repair issue is created after this duration of continuous cloud outage.
OUTAGE_REPAIR_THRESHOLD = timedelta(hours=1)

# Map grid refresh interval while the robot is moving (cleaning or returning).
_MAP_REFRESH_INTERVAL_ACTIVE = 10.0

# External preference / prefer_mode changes (Kärcher app, robot panel) are
# picked up by re-fetching get_preference during polls at most this often.
# Setup, map changes, and HA-side writes bypass the throttle.
_PREFERENCE_REFRESH_INTERVAL = 300.0
# Minimum spacing for responsive, trigger-driven preference refetches (custom_type
# push change, card "fresh on look") so rapid triggers can't hammer the robot.
_PREFERENCE_REFRESH_MIN_INTERVAL = 5.0

# Consecutive cleaning points required in a new room before current_room_name switches.
# Suppresses brief doorway incursions without delaying genuine room transitions.
_ROOM_CHANGE_HYSTERESIS = 5

# Room-name change detection runs off the map snapshot. A relocalization blip can
# briefly report inconsistent (or blank) room names before the map settles; only
# fire the repair once a differing set has persisted across this many consecutive
# refreshes, so a transient blip doesn't. The repair clears when names revert.
_ROOM_NAMES_CONFIRM_TICKS = 3


def _is_real_map_id(map_id: str | None) -> bool:
    """False for the transient 'no active map' the robot reports while relocalizing
    (current_map_id 0 → "0") and before any map exists (None / "")."""
    return bool(map_id) and map_id != "0"


# MQTT commands are QoS 0 (fire-and-forget, no broker delivery confirmation).
# async_send_command waits up to this long for work_mode to change in
# response before logging a WARNING, as a best-effort silent-packet-loss
# check. Module-level so tests can monkeypatch it instead of sleeping the
# real duration.
_COMMAND_VERIFY_TIMEOUT = 5.0

# Commands that do not change work_mode in normal operation (e.g. a locate
# beep) — verifying these against work_mode would always time out and log a
# false-positive WARNING, so they skip verification entirely.
_COMMAND_VERIFY_SKIP = frozenset({"find_device"})


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
        self._init_command_state()
        self._init_outage_state()
        self._init_map_state()
        self._init_render_state()

    def _init_command_state(self) -> None:
        self.rooms: list[Room] = []
        self.room_preferences: list[RoomPreference] = []
        self.prefer_mode: str = "standard"  # "standard" | "customise"
        # Last custom_type seen in the property push; a change means Standard/Customise
        # was switched (app or robot panel) → refetch preferences immediately.
        self._last_custom_type: int | None = None
        self._selected_room_ids: set[int] = set()
        self._consecutive_failures: int = 0
        # loop.time() of the last push received; used to discard a poll result
        # that was already in flight when a newer push landed.
        self._last_push_receipt_ts: float = 0.0
        self._current_map_id: str | None = None
        self._room_retry_task: asyncio.Task[None] | None = None
        self._push_tasks: set[asyncio.Task[None]] = set()

    def _init_outage_state(self) -> None:
        # Tracks cloud reachability: decides when a prolonged outage earns the
        # persistent repair, and how often to log while it lasts.
        self._outage = OutageTracker(OUTAGE_REPAIR_THRESHOLD.total_seconds())

    def _init_map_state(self) -> None:
        # Map state.
        self.map_snapshot: MapSnapshot | None = None
        # Bumped on every map_snapshot reassignment. KarcherMapImage keys its
        # PNG cache on this — id(snapshot) is unsafe because CPython reuses
        # addresses after GC, which can serve a stale render.
        self.map_snapshot_seq: int = 0
        self.image_last_updated: datetime | None = None
        # The traced path and its pixel projection. Owns the history seed, the
        # raw-buffer cap, and the incremental projection cache (see _path.py).
        self._path = PathProjection()
        # Whether the next non-cleaning→cleaning transition continues the paused
        # clean (keep the path) or starts a fresh one (clear it). Both Pause and
        # Stop leave the robot paused, so the device telemetry alone can't tell a
        # Resume apart from a Stop→new-clean; the entity command layer records the
        # intent here at dispatch time via set_resume_intent().
        self._resume_intent: bool = False
        self._last_map_refresh_ts: float = 0.0
        # Serialises _refresh_map: push side-effects run as concurrent tasks and
        # the poll also refreshes, so two calls can otherwise interleave at the
        # get_map_snapshot / executor awaits and assign derived state out of order
        # (an older snapshot overwriting a newer one, double seq bumps).
        self._map_refresh_lock = asyncio.Lock()
        # Serialises get_preference round-trips for this device. force=True fetches
        # (setup, map change) bypass the _last_pref_fetch_ts throttle, so two can
        # otherwise be in flight at once and collide on the adapter's topic-keyed
        # reply dispatch (_reply_listeners), orphaning one waiter.
        self._pref_fetch_lock = asyncio.Lock()
        self.current_room_name: str | None = None
        # loop.time() of the last get_preference round-trip (poll-path throttle).
        self._last_pref_fetch_ts: float = 0.0
        # Most recent robot pose from path stream (x, y, phi); None until first path push.
        # Updated at path-push frequency — used instead of the cloud snapshot robot pose
        # so that robot_px in extra_state_attributes stays in sync with the path line.
        self.current_robot_pose: tuple[float, float, float] | None = None
        # Hysteresis for current_room_name: require 5 consecutive cleaning points in a
        # candidate room before committing a change (suppresses doorway incursions).
        self._room_candidate: str | None = None
        self._room_candidate_count: int = 0
        # Room IDs sent in the last set_room_clean command; empty = no filter.
        self._active_clean_room_ids: set[int] = set()
        # Rect (image px) sent to the last zone clean; None = no active zone clean.
        # Mirrored so the card can recover its area box after a reload, exactly as
        # _active_clean_room_ids does for the room highlight. Self-authored (the rect
        # WE sent), so it never lags like the robot's areas_info echo would.
        self._active_clean_zone_px: list[float] | None = None

    def _init_render_state(self) -> None:
        # Grid-based room cell data for the Lovelace card.
        # {room_id: [[col, row], ...]} pixel positions in the rendered image.
        self.room_cell_map: dict[int, list[tuple[int, int, int]]] = {}
        self.render_image_size: tuple[int, int, int] | None = None  # (width, height, cell_size)
        # Dynamic-legend summary for the card (zone/object counts + carpet flag).
        self.map_legend: dict[str, Any] | None = None
        self.render_layout: RenderLayout | None = None
        # Decoded room-ID grid for cur_path → room lookup (None until first map fetch).
        # Shape: (grid.height, grid.width), dtype int16; 0 = no room.
        self._room_id_grid: Any = None
        # Map overlays projected to rendered-image pixels. Computed centrally
        # (not in the entity) because the projection needs render_layout + grid,
        # which live here; entities read these finished values. The path's own
        # projection lives with the path itself, in self._path.
        self.robot_px: dict[str, float] | None = None  # {x, y, phi}
        self.charger_px: dict[str, float] | None = None  # {x, y}
        # Detected AI-object markers in image pixels: [{x, y, type_id}, ...].
        # Snapshot-derived like charger_px (not accumulated); the card draws the
        # icons on its canvas overlay. Carpet detections (OBJECT_TYPE_CARPET) are
        # excluded — they duplicate the carpet area already drawn from grid bytes.
        self.object_px: list[dict[str, float]] | None = None
        # Per-room cleaned-cell area in m², keyed by room_id; recomputed only on
        # map refresh (depends solely on _room_id_grid), not on every path push.
        self.room_areas_m2: dict[int, float] = {}
        # Detects room renames from the map snapshot (see _check_room_names).
        # Reset on a map switch — new segmentation is not a rename.
        self._room_names = RoomNameWatcher(_ROOM_NAMES_CONFIRM_TICKS)
        # UTC wall-clock time when the robot last transitioned to DOCKED.
        # None until the first observed dock transition in this session.
        self.last_clean_finished_at: datetime | None = None

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
        await self._fetch_preference(force=True)

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
        # A push is definitive proof of reachability, so it must end an outage the
        # same way a successful poll does — otherwise the robot stays "unreachable"
        # and the repair issue is never cleared until a poll happens to succeed.
        self._handle_outage_end()
        self._last_push_receipt_ts = self.hass.loop.time()
        self.async_set_updated_data(props)
        task = self.hass.async_create_task(self._push_side_effects(props, prev_state))
        self._push_tasks.add(task)
        task.add_done_callback(self._push_tasks.discard)

    async def _push_side_effects(
        self, props: DeviceProperties, prev_state: VacuumState | None
    ) -> None:
        new_state = derive_vacuum_state(props)
        await self._handle_state_transition(prev_state, new_state)

        await self._maybe_refresh_rooms(props)
        await self._maybe_refetch_preferences(props)

    async def _handle_state_transition(
        self, prev_state: VacuumState | None, new_state: VacuumState
    ) -> None:
        transitioning_to_docked = (
            prev_state is not None
            and prev_state != VacuumState.DOCKED
            and new_state == VacuumState.DOCKED
        )
        transitioning_to_returning = (
            prev_state == VacuumState.CLEANING and new_state == VacuumState.RETURNING
        )
        transitioning_to_cleaning = (
            prev_state != VacuumState.CLEANING and new_state == VacuumState.CLEANING
        )
        if transitioning_to_docked:
            # The path is intentionally NOT cleared: the completed clean's path
            # stays visible while docked (matches the Kärcher app). It is cleared
            # on the next clean start or map change.
            self.last_clean_finished_at = dt_util.utcnow()
            self._last_map_refresh_ts = 0.0
            self._active_clean_room_ids = set()
            self._active_clean_zone_px = None
            self._reset_room_tracking()
            await self._refresh_map()
        elif transitioning_to_returning:
            self._last_map_refresh_ts = self.hass.loop.time()
            await self._refresh_map()
        elif transitioning_to_cleaning:
            if not self._resume_intent:
                # Fresh clean — a normal start from idle/dock, or a Stop→new-clean
                # dispatched while the robot was still paused. Clear the previous
                # path so it can't bleed into the new run. A Resume (set_resume_intent
                # True) skips this and keeps the in-progress path and room context.
                self._path.clear()
                self._reset_room_tracking()
            self._resume_intent = False
            self._last_map_refresh_ts = 0.0
            await self._refresh_map()
        elif new_state in (VacuumState.CLEANING, VacuumState.RETURNING):
            now = self.hass.loop.time()
            if now - self._last_map_refresh_ts >= _MAP_REFRESH_INTERVAL_ACTIVE:
                self._last_map_refresh_ts = now
                await self._refresh_map()

    async def _maybe_refetch_preferences(self, props: DeviceProperties) -> None:
        # A custom_type change in the push means Standard/Customise was switched
        # externally (app / robot panel). Refetch preferences so prefer_mode and
        # per-room values update immediately instead of waiting for the poll.
        if props.custom_type is not None:
            if self._last_custom_type is not None and props.custom_type != self._last_custom_type:
                await self.async_refresh_preferences()
            self._last_custom_type = props.custom_type

    async def async_refresh_preferences(self) -> None:
        """Force a responsive preference refetch (Standard/Customise + per-room).

        Short-throttled so bursts of triggers (push change, card focus) collapse
        to one round-trip; updates listeners so entities/card reflect the result.
        """
        await self._fetch_preference(min_interval=_PREFERENCE_REFRESH_MIN_INTERVAL)
        self.async_update_listeners()

    async def _maybe_refresh_rooms(self, props: DeviceProperties) -> None:
        """Re-fetch rooms and map snapshot if current_map_id changed."""
        new_map_id = props.current_map_id
        if new_map_id == self._current_map_id:
            return
        _LOGGER.debug("Map ID changed %s → %s; refreshing rooms", self._current_map_id, new_map_id)
        self._current_map_id = new_map_id
        self._path.clear()
        self._active_clean_room_ids = set()
        self._active_clean_zone_px = None
        self._reset_room_tracking()
        self.rooms = []
        self.room_preferences = []
        self._selected_room_ids = set()
        # Map change means new segmentation — reset the name baseline so a
        # name-change repair fired before the map switch doesn't persist, and
        # the new map's names become the reference point (re-seeded on the next
        # map refresh below).
        self._reset_room_name_baseline()
        self.async_update_listeners()

        if not _is_real_map_id(new_map_id):
            # "0" is the transient no-map id the robot reports while relocalizing
            # (and None is no map at all): don't fetch rooms or seed a name
            # baseline from it — the map data is mid-rebuild. The baseline was just
            # reset above and is re-seeded when a real map id returns.
            return
        try:
            self.rooms = await self._adapter.get_rooms(self._device)
        except Exception as exc:
            _LOGGER.warning("Room refresh after map change failed: %s", exc)
        finally:
            self.async_update_listeners()

        await self._refresh_map()
        await self._fetch_preference(force=True)

    async def _fetch_preference(
        self, *, force: bool = False, min_interval: float | None = None
    ) -> None:
        """Fetch and cache room preferences from the robot.

        Requires map_id to be known; silently skips if not yet available.
        Non-fatal: a timeout or missing reply leaves room_preferences empty.

        Poll-path calls are throttled to _PREFERENCE_REFRESH_INTERVAL — the
        fetch exists to pick up external changes (Kärcher app, robot panel)
        and does not need to ride every 30 s poll. force=True (setup, map
        change) bypasses the throttle. `min_interval` overrides the throttle
        window for responsive triggers (custom_type push, card refresh).
        """
        map_id_str = self._current_map_id
        if map_id_str is None:
            return
        throttle = min_interval if min_interval is not None else _PREFERENCE_REFRESH_INTERVAL
        now = self.hass.loop.time()
        if not force and now - self._last_pref_fetch_ts < throttle:
            return
        # Stamp before the round-trip so a robot that times out (5 s executor
        # wait) is not re-asked on every subsequent poll.
        self._last_pref_fetch_ts = now
        async with self._pref_fetch_lock:
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
                # available immediately.
                prefs = [RoomPreference.neutral(r.room_id, r.name) for r in self.rooms]
                _LOGGER.debug(
                    "No stored preferences; synthesised defaults for %d rooms", len(prefs)
                )

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
        poll_started = self.hass.loop.time()
        try:
            props = await self._fetch_with_reauth()
        except AuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except PermanentError as exc:
            raise ConfigEntryError(str(exc)) from exc
        except ValidationError as exc:
            _LOGGER.debug("Missed poll update: %s", exc)
            if self.data is not None:
                return self.data
            raise UpdateFailed(str(exc)) from exc
        except ProtocolError as exc:
            # WARNING per the error taxonomy (ARCHITECTURE.md): structurally
            # valid but semantically unsupported payloads point at a firmware
            # or protocol change and should be visible without debug logging.
            _LOGGER.warning("Missed poll update (unsupported payload): %s", exc)
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
        return await self._reconcile_poll_result(props, poll_started)

    async def _reconcile_poll_result(
        self, props: DeviceProperties, poll_started: float
    ) -> DeviceProperties:
        # Push/poll reconciliation: pushes are delivered on the event loop and
        # are inherently ordered; only a poll can race them. If a push landed
        # while this poll's round-trip was in flight, the poll snapshot is
        # older than coordinator.data — keep the push data instead.
        if self._last_push_receipt_ts > poll_started and self.data is not None:
            _LOGGER.debug("Poll result superseded by push received mid-flight; discarding")
            props = self.data

        if (
            not self.rooms
            and props.current_map_id is not None
            and (self._room_retry_task is None or self._room_retry_task.done())
        ):
            self._room_retry_task = self.hass.async_create_task(self._retry_room_fetch())

        if derive_vacuum_state(props) in (VacuumState.CLEANING, VacuumState.PAUSED):
            self._last_map_refresh_ts = self.hass.loop.time()
            await self._refresh_map()

        await self._fetch_preference()

        return props

    def _repair_issue_id(self, key: str) -> str:
        entry_id = self.config_entry.entry_id if self.config_entry else "unknown"
        return f"{key}_{entry_id}"

    def _create_repair(self, key: str, *, persistent: bool) -> None:
        """Create a WARNING repair issue; `key` doubles as the translation key."""
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._repair_issue_id(key),
            is_fixable=False,
            is_persistent=persistent,
            severity=IssueSeverity.WARNING,
            translation_key=key,
        )

    def _delete_repair(self, key: str) -> None:
        # async_delete_issue is a no-op when the issue does not exist.
        ir.async_delete_issue(self.hass, DOMAIN, self._repair_issue_id(key))

    def _apply_outage_repair(self, action: RepairAction) -> None:
        """Apply an OutageTracker decision to the cloud_outage_persistent issue."""
        if action is RepairAction.CREATE:
            self._create_repair("cloud_outage_persistent", persistent=True)
        elif action is RepairAction.CLEAR:
            self._delete_repair("cloud_outage_persistent")

    def _handle_outage_start(self, exc: Exception) -> None:
        """Record a failed reach. The threshold and log throttle live in OutageTracker."""
        self._apply_outage_repair(self._outage.observe_failure(self.hass.loop.time(), exc))

    def _handle_outage_end(self) -> None:
        """Record a successful reach (poll or push), dismissing the repair on recovery."""
        self._apply_outage_repair(self._outage.observe_success(self.hass.loop.time()))

    @property
    def is_robot_reachable(self) -> bool:
        """True when the last poll succeeded (no active outage)."""
        return self._outage.is_healthy and self._consecutive_failures == 0

    def _apply_room_names_repair(self, action: RepairAction) -> None:
        """Apply a RoomNameWatcher decision to the room_names_changed issue."""
        if action is RepairAction.CREATE:
            self._create_repair("room_names_changed", persistent=False)
        elif action is RepairAction.CLEAR:
            self._delete_repair("room_names_changed")

    def _reset_room_name_baseline(self) -> None:
        """Drop the name baseline and clear any active repair (map switch)."""
        self._apply_room_names_repair(self._room_names.reset())

    def _check_room_names(self, rooms: list[RoomInfo]) -> None:
        """Detect room-name changes from the map snapshot and manage the repair.

        Runs on the serialised map-refresh path (not the get_rooms fetch paths),
        so two concurrent fetches cannot race and fire a spurious repair. The
        debounce and revert rules live in RoomNameWatcher.
        """
        self._apply_room_names_repair(self._room_names.observe(rooms))

    async def _retry_room_fetch(self) -> None:
        try:
            rooms = await self._adapter.get_rooms(self._device)
        except Exception as exc:
            _LOGGER.debug("Room fetch retry failed: %s", exc)
            return
        if rooms:
            self.rooms = rooms
            self.async_update_listeners()

    def _reset_room_tracking(self) -> None:
        """Clear the room-transition hysteresis and the path-stream robot pose."""
        self._room_candidate = None
        self._room_candidate_count = 0
        self.current_robot_pose = None

    def _world_to_px(self, wx: float, wy: float) -> dict[str, float] | None:
        layout = self.render_layout
        snapshot = self.map_snapshot
        if layout is None or snapshot is None:
            return None
        grid = snapshot.grid
        px, py = world_to_pixel(
            wx,
            wy,
            layout=layout,
            grid_width=grid.width,
            grid_height=grid.height,
            resolution=grid.resolution,
            min_x=grid.min_x,
            min_y=grid.min_y,
        )
        return {"x": px, "y": py}

    def _compute_robot_px(self, snapshot: MapSnapshot | None) -> dict[str, float] | None:
        """Robot pose in pixels: path stream (lowest latency) over cloud snapshot,
        except while docked — see _project_overlays docstring for why docked is
        special-cased ahead of the path stream."""
        docked = self.data is not None and derive_vacuum_state(self.data) == VacuumState.DOCKED
        if docked and snapshot is not None and snapshot.charger is not None:
            charger = snapshot.charger
            rx = charger.x + math.cos(charger.phi) * 0.15
            ry = charger.y + math.sin(charger.phi) * 0.15
            robot_px = self._world_to_px(rx, ry)
            if robot_px is not None:
                robot_px["phi"] = charger.phi + math.pi
            return robot_px
        if self.current_robot_pose is not None:
            rx, ry, rphi = self.current_robot_pose
            robot_px = self._world_to_px(rx, ry)
            if robot_px is not None:
                robot_px["phi"] = rphi
            return robot_px
        if snapshot is not None and snapshot.robot is not None:
            robot_px = self._world_to_px(snapshot.robot.x, snapshot.robot.y)
            if robot_px is not None:
                robot_px["phi"] = snapshot.robot.phi
            return robot_px
        return None

    def _project_overlays(self) -> None:
        """Reproject path, robot, and charger to image pixels against the live layout.

        The robot pose while docked is derived from charge_station, not current_pose:
        current_pose is unreliable while docked (root cause of the recurring "backward
        at dock" bug — a constant ±π offset on it only matched one map orientation and
        broke on others). The official app distrusts it too: for this model it ignores
        current_pose entirely while charging and derives the displayed pose from
        charge_station instead — position offset 0.15m along the charger's own phi,
        heading = charger phi + π (RobotMapApi.parseRobotPoseInfo, gated on isRobot350,
        true for KaercherRCV5). Charger phi rotates with the map frame, so this is
        robust where a constant offset on current_pose was not. See _compute_robot_px.

        Called on every path push and every map refresh. The robot pose prefers the
        path stream (lowest latency) over the cloud snapshot. The path's projection
        is cached and grown incrementally — those rules live in _path.py.
        """
        snapshot = self.map_snapshot
        layout = self.render_layout

        self.robot_px = self._compute_robot_px(snapshot)

        charger_px: dict[str, float] | None = None
        if snapshot is not None and snapshot.charger is not None:
            charger_px = self._world_to_px(snapshot.charger.x, snapshot.charger.y)
        self.charger_px = charger_px

        object_px: list[dict[str, float]] | None = None
        if snapshot is not None and snapshot.objects:
            object_px = []
            for obj in snapshot.objects:
                if obj.type_id == OBJECT_TYPE_CARPET:
                    continue
                px = self._world_to_px(obj.x, obj.y)
                if px is not None:
                    object_px.append({**px, "type_id": obj.type_id})
        self.object_px = object_px

        self._path.project(snapshot, layout)

    @property
    def cur_path_px(self) -> list[int]:
        """The traced path in image pixels, flat [x0, y0, x1, y1, ...]."""
        return self._path.pixels

    async def _refresh_map(self) -> None:
        """Fetch the current map snapshot from the cloud and notify listeners."""
        async with self._map_refresh_lock:
            await self._refresh_map_locked()

    async def _refresh_map_locked(self) -> None:
        try:
            snapshot = await self._adapter.get_map_snapshot(self._device)
        except Exception as exc:
            _LOGGER.warning("Map refresh failed: %s", exc)
            return
        if snapshot is None:
            _LOGGER.debug("Map snapshot unavailable (robot has no map loaded yet)")
            return
        # One-shot startup recovery only — history_pose still carries the previous
        # clean's path at clean start, so seeding on every refresh would resurrect
        # it into a live clean.
        self._path.seed_from_history(snapshot.path)
        # CPU-bound post-processing (numpy decode + Python-level RLE over up to
        # width*height cells) runs in the executor — this path fires every 10 s
        # while cleaning and must not stall the event loop.
        derived = await self.hass.async_add_executor_job(derive_map_state, snapshot)
        self._apply_derived_map_state(snapshot, derived)
        if self.data is not None and _is_real_map_id(self.data.current_map_id):
            # Skip while relocalizing (current_map_id "0"): the snapshot's rooms are
            # mid-rebuild, so comparing/seeding names against them would churn the
            # baseline and could fire a spurious repair.
            self._check_room_names(snapshot.rooms)
        self._update_current_room_after_refresh(snapshot)
        self.async_update_listeners()

    def _apply_derived_map_state(self, snapshot: MapSnapshot, derived: DerivedMapState) -> None:
        layout = derived.layout
        # Assign all derived state in one synchronous block (no awaits) so a
        # reader can never observe the new snapshot paired with a stale layout.
        self.map_snapshot = snapshot
        self.map_snapshot_seq += 1
        self.image_last_updated = dt_util.utcnow()
        self.render_image_size = (layout.out_w, layout.out_h, layout.scale)
        self.render_layout = layout
        self.room_cell_map = derived.room_cell_map
        self._room_id_grid = derived.room_id_grid
        self.map_legend = derived.legend
        self.room_areas_m2 = derived.room_areas_m2
        # render_layout may have shifted (explored grid grew) — reproject overlays.
        self._project_overlays()

    def _update_current_room_after_refresh(self, snapshot: MapSnapshot) -> None:
        grid = snapshot.grid
        if self.vacuum_state == VacuumState.CLEANING:
            # Fallback: set room from robot pose so the sensor isn't blank after a restart
            # mid-clean (when the path is empty and no path push has arrived yet).
            if self.current_room_name is None and snapshot.robot is not None:
                room_id = room_id_for_world_point(
                    snapshot.robot.x, snapshot.robot.y, grid, self._room_id_grid
                )
                if room_id is not None and (
                    not self._active_clean_room_ids or room_id in self._active_clean_room_ids
                ):
                    self.current_room_name = self.room_name_for_id(room_id)
        else:
            self.current_room_name = None
            self._room_candidate = None
            self._room_candidate_count = 0

    def _handle_path_push(self, points: list[tuple[float, float, float, int]]) -> None:
        """Called from event loop via call_soon_threadsafe when property/post delivers cur_path."""
        self._path.extend(points)
        # Track robot pose from the last point in the batch regardless of flag — the path
        # stream is the lowest-latency source of position and orientation.
        if points:
            last_x, last_y, last_phi, _flag = points[-1]
            self.current_robot_pose = (last_x, last_y, last_phi)
        self._track_room_transition(points)
        self._project_overlays()
        self.async_update_listeners()

    def _track_room_transition(self, points: list[tuple[float, float, float, int]]) -> None:
        """Update current_room_name from cleaning points (flag != 0; flag == 0 = transit).

        Source: MqttMessageParser.java:65, APK PathMap.java:72.
        Hysteresis: require _ROOM_CHANGE_HYSTERESIS consecutive cleaning points in a
        new room before committing a change — suppresses brief doorway incursions
        without delaying genuine transitions.
        """
        snapshot = self.map_snapshot
        if self.vacuum_state != VacuumState.CLEANING or snapshot is None:
            return
        for x, y, _phi, flag in points:
            if flag == 0:
                continue
            room_id = room_id_for_world_point(x, y, snapshot.grid, self._room_id_grid)
            if room_id is None:
                continue
            if self._active_clean_room_ids and room_id not in self._active_clean_room_ids:
                continue
            candidate = self.room_name_for_id(room_id)
            if candidate == self.current_room_name:
                self._room_candidate = None
                self._room_candidate_count = 0
            elif candidate == self._room_candidate:
                self._room_candidate_count += 1
                if self._room_candidate_count >= _ROOM_CHANGE_HYSTERESIS:
                    self.current_room_name = candidate
                    self._room_candidate = None
                    self._room_candidate_count = 0
            else:
                self._room_candidate = candidate
                self._room_candidate_count = 1

    def _require_map_id(self, action: str) -> int:
        if self._current_map_id is None:
            raise ServiceValidationError(f"No map loaded; cannot {action}")
        return int(self._current_map_id)

    async def _write_preferences(self, map_id: int, ordered: list[RoomPreference]) -> None:
        """Send the full preference list, then update the local cache immediately
        so entities reflect the change without a get_preference round-trip."""
        await self._adapter.set_preference(self._device, map_id, [p.to_raw() for p in ordered])
        self.room_preferences = ordered
        self.async_update_listeners()

    async def async_set_room_preference(self, room_id: int, updated: RoomPreference) -> None:
        """Write a single room's preference, preserving all other rooms' settings.

        Rebuilds the full room_preference list from the cached coordinator state,
        replacing the entry for room_id with `updated`. Falls back to the room
        list if no cached preferences exist yet (e.g. get_preference timed out).
        """
        map_id = self._require_map_id("set room preference")

        # Preserve the ordering from the cached preferences; append rooms that
        # have no preference entry yet (they get the updated object only if it
        # is the target room, otherwise fall back to a neutral default).
        ordered = [updated if p.room_id == room_id else p for p in self.room_preferences]
        seen = {p.room_id for p in self.room_preferences}
        for room in self.rooms:
            if room.room_id in seen:
                continue
            seen.add(room.room_id)
            if room.room_id == room_id:
                ordered.append(updated)
            else:
                ordered.append(RoomPreference.neutral(room.room_id, room.name))

        await self._write_preferences(map_id, ordered)

    async def async_set_room_order(self, ordered_ids: list[int]) -> None:
        """Reorder rooms by sending preference list in requested ID sequence.

        Preserves existing per-room settings for known rooms; synthesises
        neutral defaults for any room_id not yet in the cached preferences.
        """
        map_id = self._require_map_id("reorder rooms")

        rooms_by_id = {r.room_id: r for r in self.rooms}
        prefs_by_id = {p.room_id: p for p in self.room_preferences}
        ordered: list[RoomPreference] = []
        for rid in ordered_ids:
            pref = prefs_by_id.get(rid)
            if pref is None:
                room = rooms_by_id.get(rid)
                pref = RoomPreference.neutral(rid, room.name if room else "")
            ordered.append(pref)

        await self._write_preferences(map_id, ordered)

    async def async_set_preference_type(self, prefer_type: int) -> None:
        """Switch Standard (0) or Custom (1) cleaning mode and persist on the robot."""
        await self._adapter.set_preference_type(self._device, prefer_type)
        self.prefer_mode = "customise" if prefer_type == 1 else "standard"
        self.async_update_listeners()
        # Switching into Customise: pull fresh per-room values so the panel that
        # is about to open reflects edits made elsewhere (app / robot panel).
        if prefer_type == 1:
            await self.async_refresh_preferences()

    async def async_send_command(self, service: str, params: Mapping[str, Any]) -> None:
        work_mode_before = self.data.work_mode if self.data is not None else None
        await self._adapter.send_command(self._device, service, params)
        if service in _COMMAND_VERIFY_SKIP:
            return
        # Detached: verification must not delay the service-call return. Tracked
        # in _push_tasks (same pattern as _push_side_effects) so async_shutdown
        # cancels it on unload instead of leaving it orphaned.
        task = self.hass.async_create_task(
            self._verify_command_effect(service, work_mode_before),
            name=f"karcher_verify_{service}",
        )
        self._push_tasks.add(task)
        task.add_done_callback(self._push_tasks.discard)

    async def _verify_command_effect(self, service: str, work_mode_before: int | None) -> None:
        """Best-effort QoS 0 delivery check.

        MQTT commands carry no broker-level delivery confirmation, so a dropped
        publish would otherwise be reported to the HA user as a successful
        service call. This does not validate the *exact* semantically-correct
        work_mode for `service` — only that the robot visibly reacted to
        *something* within _COMMAND_VERIFY_TIMEOUT. Observes self.data only
        through the existing DataUpdateCoordinator listener mechanism (push
        and poll both call async_update_listeners()); no out-of-band fetch and
        no interaction with _resume_intent or the poll/push race logic.

        No retry: resending an already-dispatched command is not obviously
        safe for every service in this set (e.g. set_zone_clean, which is not
        obviously idempotent if the first publish actually landed), so a
        lightweight fix logs a WARNING and leaves any retry to the user.
        """
        if self.data is not None and self.data.work_mode != work_mode_before:
            # Already changed by the time this task started running (e.g. an
            # unrelated push landed while `send_command` was awaiting the
            # publish) — nothing to wait for.
            return

        confirmed = asyncio.Event()

        @callback
        def _on_update() -> None:
            if self.data is not None and self.data.work_mode != work_mode_before:
                confirmed.set()

        remove_listener = self.async_add_listener(_on_update)
        try:
            await asyncio.wait_for(confirmed.wait(), timeout=_COMMAND_VERIFY_TIMEOUT)
        except TimeoutError:
            _LOGGER.warning(
                "No work_mode change observed within %.0fs after '%s' command; "
                "the robot may not have received it (MQTT QoS 0 has no delivery guarantee)",
                _COMMAND_VERIFY_TIMEOUT,
                service,
            )
        finally:
            remove_listener()

    async def async_zone_clean(self, rect_px: tuple[float, float, float, float]) -> None:
        """Start an area clean for one rectangle given in rendered-image pixels.

        Converts the two opposite corners to world metres (inverting the map
        projection), sends the rectangle as zone_points, then starts the clean.
        The projection is axis-aligned, so two opposite corners fully define the
        world-space rectangle. See doc/PROTOCOL.md (set_zone_points / set_zone_clean).
        """
        layout = self.render_layout
        snapshot = self.map_snapshot
        if layout is None or snapshot is None:
            raise ServiceValidationError("Map not loaded yet — cannot start area clean")
        grid = snapshot.grid
        px0, py0, px1, py1 = rect_px
        ax, ay = pixel_to_world(
            px0,
            py0,
            layout=layout,
            resolution=grid.resolution,
            min_x=grid.min_x,
            min_y=grid.min_y,
        )
        bx, by = pixel_to_world(
            px1,
            py1,
            layout=layout,
            resolution=grid.resolution,
            min_x=grid.min_x,
            min_y=grid.min_y,
        )
        x_lo, x_hi = sorted((ax, bx))
        y_lo, y_hi = sorted((ay, by))
        # Four corners, clockwise from bottom-left in world space.
        zone_points = [x_lo, y_lo, x_lo, y_hi, x_hi, y_hi, x_hi, y_lo]
        await self._adapter.send_command(
            self._device, "set_zone_points", {"zone_points": zone_points}
        )
        # Fresh area clean (a Resume routes through async_start → set_zone_clean
        # directly): clear any stale path on the upcoming cleaning transition.
        self._resume_intent = False
        # A zone clean targets no rooms — clear the room set so a stale value from a
        # prior room clean can't linger (the card re-seeds its highlight from this).
        # Symmetrically, record the sent rect so the card can recover its area box
        # after a reload (exposed as the active_clean_zone_px attribute).
        self._active_clean_room_ids = set()
        self._active_clean_zone_px = list(rect_px)
        await self._adapter.send_command(self._device, "set_zone_clean", {"ctrl_value": 1})

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

    def set_resume_intent(self, resume: bool) -> None:
        """Record whether the upcoming cleaning transition is a Resume of the
        paused clean (keep the path) or a fresh start (clear it). The entity
        command layer sets this at dispatch time, where the device state still
        distinguishes a Resume (vacuum.start while paused) from a Stop→new-clean
        (a fresh set_room_clean dispatched while paused) — by the time the
        cleaning push arrives, both look identical."""
        self._resume_intent = resume

    @property
    def active_clean_is_zone(self) -> bool:
        """True when the robot's current task is an area (zone) clean.

        Decided from the live work_mode (the robot's zone-clean family), mirroring
        the app's IotBase.getCleanMode == 6 routing — so pause/resume stays correct
        across HA restarts and zone cleans started from the Kärcher app.
        """
        data: DeviceProperties | None = self.data
        return data is not None and data.work_mode in WORK_MODE_ZONE_CLEAN

    @property
    def device(self) -> Device:
        return self._device

    def get_selected_room_id(self) -> int | None:
        """Single-selection view of the selection set.

        Returns the only selected room id when exactly one is selected, else None.
        Used by the single-room dropdown entity (KarcherRoomSelect) and diagnostics.
        """
        if len(self._selected_room_ids) == 1:
            return next(iter(self._selected_room_ids))
        return None

    def set_selected_room_id(self, room_id: int | None) -> None:
        """Single-selection setter. None clears, an id replaces the set with {id}."""
        if room_id is None:
            self._selected_room_ids = set()
        else:
            self._selected_room_ids = {room_id}

    def get_selected_room_ids(self) -> set[int]:
        return set(self._selected_room_ids)

    def set_selected_room_ids(self, room_ids: Iterable[int]) -> None:
        self._selected_room_ids = {int(r) for r in room_ids}
        self.async_update_listeners()

    def set_active_clean_rooms(self, room_ids: list[int]) -> None:
        """Record which rooms are being cleaned so current_room_name ignores others."""
        self._active_clean_room_ids = set(room_ids)
        # A room clean targets no zone — drop any rect from a prior zone clean so the
        # card can't recover a stale area box (mirror of the clear in async_zone_clean).
        self._active_clean_zone_px = None

    @property
    def active_clean_room_ids(self) -> list[int]:
        """Rooms the current clean is targeting (empty = whole-home or none active).

        Exposed so the card can recover the map highlight / target note after a
        reload, when its in-memory selection is gone but a room clean is still
        running. Cleared on dock and map change like the backing set."""
        return sorted(self._active_clean_room_ids)

    @property
    def active_clean_zone_px(self) -> list[float] | None:
        """Rect (image px) of the running zone clean, or None.

        Exposed so the card can recover its area box after a reload, when its
        in-memory _zoneRect is gone but a zone clean is still running. Holds the rect
        the card sent (never the robot's lagging areas_info echo), and is mutually
        exclusive with active_clean_room_ids — cleared on a room clean, dock, and
        map change. Only set for card-initiated zone cleans (app-initiated ones
        never route through async_zone_clean, matching the Kärcher app's own UI)."""
        return self._active_clean_zone_px

    def default_clean_room_ids(self) -> list[int]:
        """Resolve the room_ids list for set_room_clean per Standard/Custom rules.

        - Custom mode: only rooms with check==1, in preference order. Raises
          ServiceValidationError when nothing is checked (mirrors the Kärcher
          app at ControlMainActivity.java:2420-2425).
        - Standard mode: rooms in preference order, filtered by the current
          map-tap selection set when non-empty.
        - Preferences not yet loaded: fall back to coordinator.rooms order,
          filtered by selection when non-empty.

        The robot honours the order of room_ids in set_room_clean
        (ControlMainActivity.java:2410-2419), so preference order on the wire
        is what makes the user-arranged order actually take effect.
        """
        selected = self._selected_room_ids
        if not self.room_preferences:
            if selected:
                return [r.room_id for r in self.rooms if r.room_id in selected]
            return [r.room_id for r in self.rooms]

        pref_order = [p.room_id for p in self.room_preferences]
        if self.prefer_mode == "customise":
            checked = [p.room_id for p in self.room_preferences if p.check == 1]
            if not checked:
                raise ServiceValidationError("No rooms checked for Custom clean")
            return checked
        if selected:
            return [rid for rid in pref_order if rid in selected]
        return pref_order

    def consume_clean_room_ids(self) -> list[int]:
        """Resolve room_ids for a new clean and clear the one-shot selection.

        The dropdown / map-tap selection is consumed by exactly one clean
        dispatch. Without this, a stale selection silently turns every later
        parameterless start — including HAMH's whole-home dispatch from
        Apple Home, which arrives as a plain ``vacuum.start`` — into a
        single-room clean.
        """
        room_ids = self.default_clean_room_ids()
        if self._selected_room_ids:
            self._selected_room_ids = set()
            self.async_update_listeners()
        return room_ids

    def preference_for_id(self, room_id: int) -> RoomPreference | None:
        for p in self.room_preferences:
            if p.room_id == room_id:
                return p
        return None

    def room_name_for_id(self, room_id: int | None) -> str | None:
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
