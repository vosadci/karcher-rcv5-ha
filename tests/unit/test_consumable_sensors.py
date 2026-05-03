# SPDX-License-Identifier: MIT
"""Unit tests for consumable-sensor percent formula edge cases."""

from __future__ import annotations

import pytest
from custom_components.karcher_home_robots._types import DeviceProperties
from custom_components.karcher_home_robots.sensor import _SENSORS

_BY_KEY = {desc.key: desc for desc in _SENSORS}

_MAIN_BRUSH_TOTAL = 21600  # 360 h in minutes
_OTHER_TOTAL = 10800  # 180 h in minutes


@pytest.mark.parametrize(
    "key,total",
    [
        ("main_brush", _MAIN_BRUSH_TOTAL),
        ("side_brush", _OTHER_TOTAL),
        ("hypa", _OTHER_TOTAL),
        ("mop_life", _OTHER_TOTAL),
    ],
)
def test_new_consumable_is_100(key: str, total: int) -> None:
    props = DeviceProperties(**{key: 0})
    assert _BY_KEY[key].value_fn(props) == 100


@pytest.mark.parametrize(
    "key,total",
    [
        ("main_brush", _MAIN_BRUSH_TOTAL),
        ("side_brush", _OTHER_TOTAL),
        ("hypa", _OTHER_TOTAL),
        ("mop_life", _OTHER_TOTAL),
    ],
)
def test_fully_elapsed_is_0(key: str, total: int) -> None:
    props = DeviceProperties(**{key: total})
    assert _BY_KEY[key].value_fn(props) == 0


@pytest.mark.parametrize(
    "key,total",
    [
        ("main_brush", _MAIN_BRUSH_TOTAL),
        ("side_brush", _OTHER_TOTAL),
        ("hypa", _OTHER_TOTAL),
        ("mop_life", _OTHER_TOTAL),
    ],
)
def test_over_limit_clamps_to_0(key: str, total: int) -> None:
    props = DeviceProperties(**{key: total + 1000})
    assert _BY_KEY[key].value_fn(props) == 0


def test_main_brush_half_life() -> None:
    props = DeviceProperties(main_brush=_MAIN_BRUSH_TOTAL // 2)
    assert _BY_KEY["main_brush"].value_fn(props) == 50


def test_none_returns_none() -> None:
    props = DeviceProperties()
    for key in ("main_brush", "side_brush", "hypa", "mop_life"):
        assert _BY_KEY[key].value_fn(props) is None
