# SPDX-License-Identifier: MIT
"""Coordinator -- state ownership, push/poll reconciliation, state derivation.

Responsibilities (spec/04-architecture.md §4.2, §5, §6):
  - Own DeviceProperties for one config entry.
  - Derive VacuumState from raw properties via derive_vacuum_state().
  - Reconcile push and poll updates using monotonic receipt timestamps
    so that an older poll never overwrites a newer push (FR-UP-5, NFR-R-5).
  - Propagate unavailability to entities when the cloud is unreachable
    (FR-OF-1).
  - Hold the selected room ID for the vacuum entity (FR-SL-3).

The coordinator never imports adapter.py directly; it receives an
adapter instance via dependency injection in async_setup().
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time  # wall-clock monotonic for outage duration; hass.loop.time() for update ordering
from collections.abc import Mapping
from datetime import timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.issue_registry import IssueSeverity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

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

if TYPE_CHECKING:
    from .adapter import Device, KarcherAdapter, Room

_LOGGER = logging.getLogger(__name__)

# status value meaning "robot is on the dock".
# Source: doc/PROTOCOL.md §6, confirmed 2026-03-28.
_STATUS_DOCKED = 4

# After this many consecutive poll failures the coordinator raises UpdateFailed
# (FR-OF-5 — prevents single-failure flapping).
_FAILURE_THRESHOLD = 2

# Persistent repair issue is created after this duration of continuous cloud
# outage (FR-OF-6).
OUTAGE_REPAIR_THRESHOLD = timedelta(hours=1)

# Log throttle constants (FR-OF-8):
# After this many seconds in an outage, switch to periodic logging.
_LOG_THROTTLE_AFTER = 300.0  # 5 minutes
# Once throttled, emit one log line per this interval.
_LOG_THROTTLE_INTERVAL = 600.0  # 10 minutes


class VacuumState(Enum):
    """HA-visible vacuum states derived from raw device telemetry.

    Maps to homeassistant.components.vacuum.VacuumActivity values in
    the entity layer; the coordinator is decoupled from HA enums so
    derive_vacuum_state() is testable without an HA environment.
    """

    CLEANING = "cleaning"
    PAUSED = "paused"
    RETURNING = "returning"
    DOCKED = "docked"
    IDLE = "idle"
    ERROR = "error"
    UNKNOWN = "unknown"


def _is_docked(props: DeviceProperties) -> bool:
    """Return True when the robot is physically on the charging dock."""
    return props.status == _STATUS_DOCKED or bool(props.charge_state)


def derive_vacuum_state(props: DeviceProperties) -> VacuumState:
    """Derive the HA vacuum state from a DeviceProperties snapshot.

    Derivation rules (spec/04-architecture.md §5, doc/PROTOCOL.md §6):
      1. work_mode in WORK_MODE_CLEANING -> Cleaning.
      2. work_mode in WORK_MODE_GO_HOME:
           docked  -> Docked; else -> Returning.
      3. work_mode in WORK_MODE_PAUSE -> Paused.
      4. work_mode in WORK_MODE_IDLE:
           docked  -> Docked;
           fault   -> Error;
           else    -> Idle.
      5. Unknown work_mode (logged at DEBUG):
           docked  -> Docked; else -> Unknown.

    "Docked" means status == 4 OR charge_state > 0.

    FR-BS-1: Error is only set when the robot is idle AND faulted AND
    not docked -- transient faults during cleaning or returning do not
    surface as Error (FR-BS-2).

    Args:
        props: Frozen snapshot of device telemetry from the adapter.

    Returns:
        The derived VacuumState.
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
    """Return the state for a robot whose work_mode is in WORK_MODE_IDLE."""
    if docked:
        return VacuumState.DOCKED
    if props.fault:
        return VacuumState.ERROR
    return VacuumState.IDLE


class KarcherCoordinator(DataUpdateCoordinator[DeviceProperties]):
    """Coordinator for one Kärcher device config entry.

    Owns a KarcherAdapter instance and runs push/poll reconciliation
    with monotonic receipt timestamps (FR-UP-5). Entities read
    coordinator.data (DeviceProperties) and coordinator.vacuum_state.
    """

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
        # Monotonic timestamp of the last accepted update (FR-UP-5).
        self._last_update_ts: float = 0.0
        # Lock prevents a poll response from overwriting a newer push (NFR-R-5).
        self._update_lock: asyncio.Lock = asyncio.Lock()
        # Consecutive poll failures counter (FR-OF-5).
        self._consecutive_failures: int = 0
        # Track map ID so we can detect changes (FR-SL-7).
        self._current_map_id: str | None = None
        # Room retry task — tracked so it can be cancelled on shutdown.
        self._room_retry_task: asyncio.Task[None] | None = None
        # Outage tracking (FR-OF-6, FR-OF-7, FR-OF-8).
        # Wall-clock time when the current outage started (None = not in outage).
        self._outage_start: float | None = None
        # Whether the persistent repair issue has been created this outage.
        self._outage_repair_created: bool = False
        # Wall-clock time of the last throttled log emission.
        self._last_throttled_log: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Subscribe to push, load rooms, and perform the first refresh.

        Called from async_setup_entry in __init__.py after the adapter is
        already set up and authenticated.
        """
        # Wire the push callback before the first poll so no push is missed
        # (FR-UP-3).
        await self._adapter.subscribe(self._device, self._handle_push)
        try:
            self.rooms = await self._adapter.get_rooms(self._device)
        except Exception as exc:
            _LOGGER.warning("Initial room fetch failed (will retry on map change): %s", exc)
        await self.async_config_entry_first_refresh()
        # Capture the initial map ID so _maybe_refresh_rooms can detect changes.
        if self.data is not None:  # pragma: no branch — first_refresh raises on None data
            self._current_map_id = self.data.current_map_id

    async def async_shutdown(self) -> None:
        """Tear down the adapter and cancel any scheduled refreshes."""
        if self._room_retry_task is not None:
            self._room_retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._room_retry_task
        await self._adapter.unsubscribe(self._device)
        await self._adapter.close()
        await super().async_shutdown()

    # ------------------------------------------------------------------
    # Push path (FR-UP-1)
    # ------------------------------------------------------------------

    def _handle_push(self, props: DeviceProperties) -> None:
        """Receive a push update from the adapter (event loop, not mqtt thread).

        The adapter guarantees this is called from the event loop via
        loop.call_soon_threadsafe (FR-UP-4).
        """
        ts = self.hass.loop.time()
        self.hass.async_create_task(self._apply_update(props, ts))

    async def _apply_update(self, props: DeviceProperties, ts: float) -> None:
        """Apply props if ts is newer than the last accepted update (FR-UP-5)."""
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
            self.async_set_updated_data(props)

        await self._maybe_refresh_rooms(props)

    async def _maybe_refresh_rooms(self, props: DeviceProperties) -> None:
        """Re-fetch rooms if current_map_id changed (FR-SL-7).

        Clears the room list and resets the selected room immediately so the
        room select becomes unavailable during the fetch, then repopulates.
        """
        new_map_id = props.current_map_id
        if new_map_id == self._current_map_id:
            return
        _LOGGER.debug("Map ID changed %s → %s; refreshing rooms", self._current_map_id, new_map_id)
        self._current_map_id = new_map_id
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

    # ------------------------------------------------------------------
    # Poll path (FR-UP-2)
    # ------------------------------------------------------------------

    async def _fetch_with_reauth(self) -> DeviceProperties:
        """Fetch properties, performing one silent reauth on TokenRejected (FR-A-8)."""
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
        """Fetch fresh properties from the device (DataUpdateCoordinator hook).

        Raises UpdateFailed, ConfigEntryAuthFailed, or ConfigEntryError
        per the error taxonomy in spec/04 §8.
        Implements FR-OF-5: a single failure does not immediately
        surface as UpdateFailed.
        Implements FR-A-8/FR-A-8a: on TokenRejected, attempt silent reauth
        before surfacing ConfigEntryAuthFailed.
        """
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
        """Record an outage tick and emit throttled logs (FR-OF-8).

        Creates the persistent repair issue after OUTAGE_REPAIR_THRESHOLD (FR-OF-6).
        """
        now = time.monotonic()
        if self._outage_start is None:
            # First failure — transition online→offline.
            self._outage_start = now
            self._last_throttled_log = now
            _LOGGER.warning(
                "Cloud unreachable: %s. Entities will become unavailable.",
                exc,
            )
            return

        outage_duration = now - self._outage_start
        # Create repair issue after the threshold (FR-OF-6).
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

        # Throttled logging (FR-OF-8).
        if outage_duration < _LOG_THROTTLE_AFTER:
            # In the first 5 minutes: INFO per failure.
            _LOGGER.info("Cloud still unreachable: %s", exc)
        elif now - self._last_throttled_log >= _LOG_THROTTLE_INTERVAL:
            # After 5 minutes: one line per 10 minutes.
            self._last_throttled_log = now
            _LOGGER.info(
                "Cloud unreachable for %.0f min: %s",
                outage_duration / 60,
                exc,
            )

    def _handle_outage_end(self) -> None:
        """Dismiss the repair issue and log the recovery transition (FR-OF-7, FR-OF-8)."""
        if self._outage_start is None:
            return
        # Transition offline→online.
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
        """Re-attempt room fetch when rooms list is empty but a map exists."""
        try:
            rooms = await self._adapter.get_rooms(self._device)
        except Exception as exc:
            _LOGGER.debug("Room fetch retry failed: %s", exc)
            return
        if rooms:
            self.rooms = rooms
            self.async_update_listeners()

    # ------------------------------------------------------------------
    # Commands (delegated to adapter)
    # ------------------------------------------------------------------

    async def async_send_command(self, service: str, params: Mapping[str, Any]) -> None:
        """Send a service_invoke command to the device."""
        await self._adapter.send_command(self._device, service, params)

    async def async_set_property(self, params: Mapping[str, Any]) -> None:
        """Send a prop.set command to the device."""
        await self._adapter.set_property(self._device, params)

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    @property
    def vacuum_state(self) -> VacuumState:
        """Return the derived vacuum state (computed from self.data)."""
        data: DeviceProperties | None = self.data
        if data is None:
            return VacuumState.UNKNOWN
        return derive_vacuum_state(data)

    # ------------------------------------------------------------------
    # Device handle
    # ------------------------------------------------------------------

    @property
    def device(self) -> Device:
        """Return the device this coordinator manages."""
        return self._device

    # ------------------------------------------------------------------
    # Room selection (FR-SL-3)
    # ------------------------------------------------------------------

    def get_selected_room_id(self) -> int | None:
        """Return the currently selected room ID, or None for all rooms."""
        return self._selected_room_id

    def set_selected_room_id(self, room_id: int | None) -> None:
        """Set the room to clean next; None means all rooms."""
        self._selected_room_id = room_id
