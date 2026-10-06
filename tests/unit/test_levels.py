# SPDX-License-Identifier: MIT
"""Unit tests for the per-model level scales.

The contract: the RCV 5's numbering is the integration's own, a model on another
numbering is translated at the edge, and a level no scale describes survives a
round trip untouched instead of turning into a neighbouring level.
"""

from __future__ import annotations

import pytest
from custom_components.karcher_home_robots._levels import (
    DEFAULT_WATER,
    DEFAULT_WIND,
    UNMAPPED,
    LevelScale,
    ModelLevels,
    levels_for,
)
from custom_components.karcher_home_robots._model_profile import (
    PROFILES,
    RVF7_WATER_LEVELS,
    RVF7_WIND_LEVELS,
)
from custom_components.karcher_home_robots._types import RoomPreference
from tests.conftest import make_props

RCV5_ID = "1540149850806333440"
RVF7_COMFORT_ID = "1950097614355394560"
RVF7_ID = "1950097634462887936"

RVF7 = ModelLevels(wind=LevelScale(RVF7_WIND_LEVELS), water=LevelScale(RVF7_WATER_LEVELS))


def test_default_scales_are_the_rcv5_numbering() -> None:
    assert DEFAULT_WIND.device == (0, 1, 2, 3)
    assert DEFAULT_WATER.device == (0, 1, 2)


@pytest.mark.parametrize("raw", [0, 1, 2, 3])
def test_default_wind_is_identity(raw: int) -> None:
    assert DEFAULT_WIND.to_canonical(raw) == raw
    assert DEFAULT_WIND.to_device(raw) == raw


@pytest.mark.parametrize(("raw", "canonical"), [(1, 0), (2, 1), (3, 2), (4, 3)])
def test_rvf7_wind_is_shifted_by_one(raw: int, canonical: int) -> None:
    assert RVF7.wind.to_canonical(raw) == canonical
    assert RVF7.wind.to_device(canonical) == raw


@pytest.mark.parametrize("raw", [0, 5, 99, -1])
def test_a_level_outside_the_scale_never_collides_with_a_real_one(raw: int) -> None:
    """RVF 7 raw 0 must not read as silent: that is the whole point of UNMAPPED."""
    canonical = RVF7.wind.to_canonical(raw)

    assert canonical not in range(len(RVF7.wind.device))
    assert RVF7.wind.to_device(canonical) == raw


def test_an_unmapped_level_round_trips_through_a_preference_edit() -> None:
    """Editing another field of a row must not rewrite a level we cannot name."""
    row = [1, "Kitchen", 0, 0, 7, 1, 0, 0, 0, 0, 0, 0]
    pref = RoomPreference.from_raw(row)
    assert pref is not None

    canonical = RVF7.pref_to_canonical(pref)
    edited = RVF7.pref_to_device(canonical)

    assert edited.wind == 7
    assert canonical.wind == UNMAPPED + 7


def test_rvf7_preference_row_is_translated_both_ways() -> None:
    pref = RoomPreference.neutral(1, "Hall")

    on_the_wire = RVF7.pref_to_device(pref)

    assert pref.wind == 1
    assert on_the_wire.wind == 2
    assert RVF7.pref_to_canonical(on_the_wire) == pref


def test_params_translate_wind_and_water_and_nothing_else() -> None:
    levels = ModelLevels(wind=LevelScale((1, 2, 3, 4)), water=LevelScale((1, 2, 3)))

    out = levels.params_to_device({"wind": 3, "water": 0, "mode": 1})

    assert out == {"wind": 4, "water": 1, "mode": 1}


def test_params_without_levels_pass_through() -> None:
    assert RVF7.params_to_device({"mode": 2}) == {"mode": 2}


def test_props_round_trip_and_keep_missing_levels_missing() -> None:
    props = make_props(wind=4, water=None, mode=1)

    canonical = RVF7.props_to_canonical(props)

    assert canonical.wind == 3
    assert canonical.water is None
    assert canonical.mode == 1
    assert RVF7.props_to_device(canonical) == props


def test_props_with_nothing_to_translate_are_returned_as_is() -> None:
    """Callers compare snapshots by identity; a copy per poll would break that."""
    props = make_props(wind=2, water=1)

    assert ModelLevels().props_to_canonical(props) is props
    assert ModelLevels().props_to_device(props) is props


def test_levels_for_an_unlisted_product_is_the_rcv5_numbering() -> None:
    assert levels_for("not-a-product-id") == ModelLevels()


def test_levels_for_the_rcv5_is_the_rcv5_numbering() -> None:
    """The maintainer's robot must not move: this is the byte-identical guarantee."""
    assert levels_for(RCV5_ID) == ModelLevels()


@pytest.mark.parametrize("product_id", [RVF7_ID, RVF7_COMFORT_ID])
def test_both_rvf7_products_are_on_the_shifted_scales(product_id: str) -> None:
    levels = levels_for(product_id)

    assert levels.wind.device == RVF7_WIND_LEVELS
    assert levels.water.device == RVF7_WATER_LEVELS


def test_only_the_rvf7_has_its_own_scale_so_far() -> None:
    """Pins the rollout: a row added here changes what users' robots are sent."""
    shifted = {
        p.member_name for p in PROFILES if p.wind_levels is not None or p.water_levels is not None
    }

    assert shifted == {"RVF7", "RVF7_COMFORT"}
