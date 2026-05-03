# SPDX-License-Identifier: MIT
"""Integration-owned DTOs and Protocol types for the karcher-home surface.

karcher-home ships no py.typed marker and no .pyi stubs; mypy resolves every
import as Any. These Protocol classes declare the surface the adapter uses and
allow a single cast() at construction time instead of scattering type: ignore.
If upstream ships py.typed, remove these Protocols and the cast() together.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class DeviceProperties:
    """Integration-owned frozen snapshot of one robot's telemetry.

    All fields are optional; the adapter sets None when a value is absent or
    fails validation. Entities return unavailable on None.

    Units:
      battery       — percent 0-100
      cleaning_area — raw units of 0.01 m²; divide by 100 for m² (doc/PROTOCOL.md §6)
      cleaning_time — minutes
      wind          — 0 Silent, 1 Standard, 2 Medium, 3 Turbo (doc/PROTOCOL.md §5)
      water         — 0 Inactive, 1 Low, 2 Medium, 3 High
      mode          — 0 Vacuum, 1 Vacuum & Mop, 2 Mop (doc/PROTOCOL.md §5)
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


class DevicePropertiesProtocol(Protocol):
    """Structural type for karcher-home's DeviceProperties dataclass."""

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
    # Upstream typo — field is net_stauts, not net_status.
    net_stauts: Any


class KarcherHomeProtocol(Protocol):
    """Structural type for the upstream KarcherHome client.

    Mirrors the public + allowlisted-private surface the adapter uses.
    Private symbols are pinned in ALLOWED_PRIVATE_API in tests/tools/check_imports.py.
    """

    async def login(self, email: str, password: str) -> Any: ...  # pragma: no cover

    async def get_devices(self) -> list[Any]: ...  # pragma: no cover

    async def get_map_data(self, dev: Any, map: int = ...) -> Any: ...  # pragma: no cover

    async def close(self) -> None: ...  # pragma: no cover

    # private-api: _mqtt — paho MqttClient wrapper; no public accessor exists.
    _mqtt: Any

    # private-api: _base_url / _mqtt_url — resolved during KarcherHome.create().
    _base_url: str
    _mqtt_url: str | None

    # private-api: _device_props — internal dict[sn, DeviceProperties].
    _device_props: dict[str, Any]

    # private-api: _wait_events — internal dict[topic, threading.Event].
    _wait_events: dict[str, Any]

    def _update_device_properties(self, sn: str, data: dict[str, Any]) -> Any:  # pragma: no cover
        # Bypasses the stale get_device_properties cache.
        ...

    def subscribe_device(self, dev: Any) -> None: ...  # pragma: no cover

    def unsubscribe_device(self, dev: Any) -> None: ...  # pragma: no cover
