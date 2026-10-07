# SPDX-License-Identifier: MIT
"""Per-model suction and water level scales.

Everything above the coordinator speaks the RCV 5's numbering: suction 0-3
(silent .. turbo) and water 0-2 (low .. high). Some models number the same
levels differently on the wire — the RVF 7's suction is 1-4. The coordinator
translates at its two edges, in from the robot and out to it, so entities, the
card and users' automations never see the difference and the RCV 5 path is
byte-identical.

A level the model's scale does not describe is neither dropped nor guessed at.
It travels above the coordinator as UNMAPPED + raw, which no real level can
equal, and goes back to the robot as the raw value. A number this table has
never heard of therefore survives an edit of some other field in the same
preference row.

Pure: no HA, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from ._model_profile import profile_for

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ._types import DeviceProperties, RoomPreference

UNMAPPED = 1_000_000


def is_unmapped(level: int) -> bool:
    """Whether `level` is a robot number no scale describes (see `to_canonical`)."""
    return level >= UNMAPPED // 2


def raw_level(level: int) -> int:
    """The robot's own number for `level`: itself unless it travelled as UNMAPPED + raw."""
    return level - UNMAPPED if is_unmapped(level) else level


def attribute_level(level: int, known: int) -> int | None:
    """What the vacuum's `room_preferences` attribute carries for a level.

    A mapped level is itself. An unmapped one is the robot's own number when that
    cannot be mistaken for one of the `known` levels (0..known-1), which is what the
    attribute always carried on an RCV 5, and None when it could (an RVF 7
    reporting 0, which must not read as "silent").
    """
    if not is_unmapped(level):
        return level
    raw = raw_level(level)
    return raw if raw >= known else None


@dataclass(frozen=True)
class LevelScale:
    """The wire value of each level, in the RCV 5's level order."""

    device: tuple[int, ...]

    def to_canonical(self, raw: int) -> int:
        if raw in self.device:
            return self.device.index(raw)
        return UNMAPPED + raw

    def to_device(self, canonical: int) -> int:
        if 0 <= canonical < len(self.device):
            return self.device[canonical]
        return raw_level(canonical)


DEFAULT_WIND = LevelScale((0, 1, 2, 3))
DEFAULT_WATER = LevelScale((0, 1, 2))


@dataclass(frozen=True)
class ModelLevels:
    wind: LevelScale = DEFAULT_WIND
    water: LevelScale = DEFAULT_WATER

    def props_to_canonical(self, props: DeviceProperties) -> DeviceProperties:
        return _retarget(
            props,
            None if props.wind is None else self.wind.to_canonical(props.wind),
            None if props.water is None else self.water.to_canonical(props.water),
        )

    def props_to_device(self, props: DeviceProperties) -> DeviceProperties:
        return _retarget(
            props,
            None if props.wind is None else self.wind.to_device(props.wind),
            None if props.water is None else self.water.to_device(props.water),
        )

    def params_to_device(self, params: Mapping[str, Any]) -> dict[str, Any]:
        out = dict(params)
        if "wind" in out:
            out["wind"] = self.wind.to_device(out["wind"])
        if "water" in out:
            out["water"] = self.water.to_device(out["water"])
        return out

    def pref_to_canonical(self, pref: RoomPreference) -> RoomPreference:
        return replace(
            pref,
            wind=self.wind.to_canonical(pref.wind),
            water=self.water.to_canonical(pref.water),
        )

    def pref_to_device(self, pref: RoomPreference) -> RoomPreference:
        return replace(
            pref,
            wind=self.wind.to_device(pref.wind),
            water=self.water.to_device(pref.water),
        )


def _retarget(props: DeviceProperties, wind: int | None, water: int | None) -> DeviceProperties:
    """`props` itself when nothing changed, which is every poll on an RCV 5.

    Skips an allocation per poll, and keeps the existing identity assertions in the
    coordinator tests meaningful: a snapshot we did not alter stays the same object.
    """
    if wind == props.wind and water == props.water:
        return props
    return replace(props, wind=wind, water=water)


def levels_for(product_id: str) -> ModelLevels:
    """The scales for a product ID; the RCV 5's for any model not listed."""
    profile = profile_for(product_id)
    if profile is None:
        return ModelLevels()
    return ModelLevels(
        wind=LevelScale(profile.wind_levels) if profile.wind_levels else DEFAULT_WIND,
        water=LevelScale(profile.water_levels) if profile.water_levels else DEFAULT_WATER,
    )
