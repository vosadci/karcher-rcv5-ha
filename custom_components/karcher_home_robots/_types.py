# SPDX-License-Identifier: MIT
"""Integration-owned DTOs for the karcher-home surface.

karcher-home ships no py.typed marker and no .pyi stubs; the adapter types its
client as Any and uses getattr() for private-API access. If upstream ships
py.typed, add proper annotations then.
"""

from __future__ import annotations

from dataclasses import dataclass


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
