# SPDX-License-Identifier: MIT
"""Integration-owned DTOs for the karcher-home surface.

karcher-home ships no py.typed marker and no .pyi stubs; the adapter types its
client as Any and uses getattr() for private-API access. If upstream ships
py.typed, add proper annotations then.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Robot replies with 9-element arrays; we send 12-element arrays (APK wire format).
# Minimum required to parse: indices 0-8 (through check field).
_PREF_ARRAY_MIN = 9
_PREF_ARRAY_LEN = 12  # full send format


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
      tank_state    — water tank presence: 3 = seated; other values = absent/unknown
      cloth_state   — mop cloth presence: 1 = installed; 0 = absent
      main_brush    — minutes of use elapsed; full life 360 h (21 600 min)
      side_brush    — minutes of use elapsed; full life 180 h (10 800 min)
      hypa          — minutes of use elapsed; full life 180 h (10 800 min)
      mop_life      — minutes of use elapsed; full life 180 h (10 800 min)
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
    tank_state: int | None = None
    cloth_state: int | None = None
    current_map_id: str | None = None
    main_brush: int | None = None
    side_brush: int | None = None
    hypa: int | None = None
    mop_life: int | None = None


@dataclass(frozen=True)
class RoomPreference:
    """Per-room cleaning preference as stored on the robot.

    Parsed from the 12-element array returned by get_preference (APK: GetPreferenceResp).
    Array layout: [roomId, roomName, materialId, mode, wind, water, repeat,
                   carpet, check, 0, 0, carpetAvoidance]
    """

    room_id: int
    room_name: str
    mode: int  # 0=Vacuum 1=Vacuum+Mop 2=Mop
    wind: int  # 0=Silent 1=Standard 2=Medium 3=Turbo
    water: int  # 1=Low 2=Medium 3=High
    repeat: int  # 0=single 1=double 2=triple
    check: int  # 1=custom settings active for this room
    carpet_avoidance: int  # 0=off 1=on
    # Pass-through fields: parsed from the reply and serialised back verbatim
    # so a partial edit (one room's mode) cannot zero them robot-side.
    material_id: int = 0  # index 2 — room floor material
    carpet: int = 0  # index 7 — carpet flag

    @classmethod
    def from_raw(cls, row: list[Any]) -> RoomPreference | None:
        """Parse a preference array from the robot reply.

        The robot returns 9-element arrays; we send 12-element arrays.
        carpetAvoidance (index 11) is absent in the reply — default to 0.
        """
        if not isinstance(row, list) or len(row) < _PREF_ARRAY_MIN:
            return None
        try:
            return cls(
                room_id=int(row[0]),
                room_name=str(row[1]) if row[1] is not None else "",
                material_id=int(row[2]),
                mode=int(row[3]),
                wind=int(row[4]),
                water=int(row[5]),
                repeat=int(row[6]),
                carpet=int(row[7]),
                check=int(row[8]),
                carpet_avoidance=int(row[11]) if len(row) >= _PREF_ARRAY_LEN else 0,
            )
        except TypeError, ValueError, IndexError:
            return None

    def to_raw(self) -> list[Any]:
        """Serialise back to the 12-element wire format for set_preference."""
        return [
            self.room_id,
            self.room_name,
            self.material_id,
            self.mode,
            self.wind,
            self.water,
            self.repeat,
            self.carpet,
            self.check,
            0,
            0,
            self.carpet_avoidance,
        ]
