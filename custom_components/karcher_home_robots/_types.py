# SPDX-License-Identifier: MIT
"""Integration-owned Protocol types and DTOs for the karcher-home surface.

karcher-home 0.5.1 ships no py.typed marker and no .pyi stubs; mypy
resolves every import as Any. Rather than vendoring stubs that would
drift silently against a dormant upstream, the adapter declares the
surface it uses as Protocol classes here and applies a single cast()
at construction time (spec/04-architecture.md §4.1.1, ADR-0001).

These Protocols mirror two sources of truth:
  - Public methods: the adapter calls documented in spec/04 §4.1.
  - Private surface: ALLOWED_PRIVATE_API in tests/tools/check_imports.py
    and the table in spec/03-constraints-and-deltas.md §3.1.

If karcher upstream ships py.typed in a future release, remove these
Protocols and the cast() in adapter.py in the same PR that bumps the pin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Integration-owned DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeviceProperties:
    """Integration-owned frozen snapshot of one robot's telemetry.

    Projected from DevicePropertiesProtocol by the adapter; the
    coordinator and entities never see the upstream type (ADR-0001,
    spec/04 §4.1).

    All fields are optional: the adapter sets a field to None when the
    upstream value is absent or fails validation, rather than raising.
    Entities handle None by returning unavailable (FR-SE-4).

    Units:
      battery       - percent, 0-100
      cleaning_area — raw units of 0.01 m²; divide by 100 for m²
                      (doc/PROTOCOL.md §6, confirmed 2026-03-28)
      cleaning_time — minutes
      wind          — 0 Silent, 1 Standard, 2 Medium, 3 Turbo
                      (doc/PROTOCOL.md §5, confirmed 2026-03-28)
      water         — 0 Inactive, 1 Low, 2 Medium, 3 High
      mode          — cleaning type: 0 Vacuum, 1 Vacuum & Mop, 2 Mop
                      (doc/PROTOCOL.md §5, confirmed 2026-03-29)
      work_mode     — see const.py WORK_MODE_* sets
      status        — 4 = docked; other values undocumented
      charge_state  — 0 = not charging; >0 = charging / docked
      fault         — 0 = no fault; non-zero = fault code
      current_map_id — active map identifier
    """

    battery: int | None = None
    cleaning_area: int | None = None
    cleaning_time: int | None = None
    work_mode: int | None = None
    status: int | None = None
    charge_state: int | None = None
    fault: int | None = None
    wind: int | None = None
    water: int | None = None
    mode: int | None = None
    current_map_id: str | None = None


# ---------------------------------------------------------------------------
# Structural types for the karcher-home upstream surface
# ---------------------------------------------------------------------------


class DevicePropertiesProtocol(Protocol):
    """Structural type for karcher-home's DeviceProperties dataclass.

    Fields are drawn from observed MQTT payloads documented in
    doc/PROTOCOL.md. Only the fields the adapter projects into the
    integration-owned DeviceProperties DTO are listed here.
    """

    battery: int | None
    cleaning_area: int | None
    cleaning_time: int | None
    work_mode: int | None
    status: int | None
    charge_state: int | None
    fault: int | None
    wind: int | None
    water: int | None
    mode: int | None
    current_map_id: str | int | None
    # Upstream typo in the library — field is named net_stauts, not net_status.
    # Access through the adapter's work-around; see spec/03 §3.1.
    net_stauts: Any


class KarcherHomeProtocol(Protocol):
    """Structural type for the upstream KarcherHome client.

    Mirrors the public + allowlisted-private surface the adapter uses.
    The private surface is pinned in spec/03-constraints-and-deltas.md §3.1
    and mirrored in ALLOWED_PRIVATE_API in tests/tools/check_imports.py.
    Both must stay in sync with this Protocol.
    """

    # ------------------------------------------------------------------
    # Public methods the adapter calls
    # ------------------------------------------------------------------

    async def login(self, email: str, password: str) -> Any: ...  # pragma: no cover

    async def get_devices(self) -> list[Any]: ...  # pragma: no cover

    async def get_map_data(self, dev: Any, map: int = ...) -> Any: ...  # pragma: no cover

    async def close(self) -> None: ...  # pragma: no cover

    # ------------------------------------------------------------------
    # Allowlisted private surface (spec/03 §3.1, ADR-0001)
    # ------------------------------------------------------------------

    # _mqtt — paho MqttClient wrapper; no public accessor exists.
    _mqtt: Any

    # _base_url — REST base URL resolved during KarcherHome.create(); read
    # after authenticate() to build the region endpoint snapshot (FR-RG-2).
    _base_url: str

    # _mqtt_url — MQTT broker URL resolved during KarcherHome.create(); read
    # after authenticate() to build the region endpoint snapshot (FR-RG-2).
    _mqtt_url: str | None

    # _device_props — internal dict[sn, DeviceProperties]; used by
    # _project_properties() to snapshot the cached telemetry.
    _device_props: dict[str, Any]

    # _wait_events — internal dict[topic, threading.Event]; used by
    # fetch_properties_sync to register a reply-wait event.
    _wait_events: dict[str, Any]

    def _update_device_properties(self, sn: str, data: dict[str, Any]) -> Any:  # pragma: no cover
        # Work-around: get_device_properties() returns stale cache once
        # subscribed; this internal updater bypasses the cache.
        ...

    def subscribe_device(self, dev: Any) -> None:  # pragma: no cover
        # Public-looking name but undocumented upstream; pinned in the
        # allowlist so any future renaming is caught at check time rather
        # than at runtime.
        ...

    def unsubscribe_device(self, dev: Any) -> None: ...  # pragma: no cover
