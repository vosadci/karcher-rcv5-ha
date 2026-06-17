# SPDX-License-Identifier: MIT
"""Property-based tests for the pure room-ID grid decoder.

``decode_room_id_grid`` is a vectorised numpy implementation of a piecewise
byte → room_id mapping (documented in its docstring / doc/MAP_DATA.md §4.2).
Vectorised mask logic is exactly where an off-by-one at a range boundary hides
without any single fixture noticing. These tests pin it down two ways:

* exhaustively over every one of the 256 byte values (boundary-proof), and
* via hypothesis over arbitrary grid shapes and data lengths, cross-checked
  against an independent scalar reference.
"""

from __future__ import annotations

import numpy as np
from custom_components.karcher_home_robots.map_render import decode_room_id_grid
from hypothesis import given, settings
from hypothesis import strategies as st


def _ref_room_id(byte: int) -> int:
    """Scalar reference for the documented byte → room_id mapping."""
    if 10 <= byte <= 59:
        return byte
    if 60 <= byte <= 127:
        return byte - 50
    if 147 <= byte <= 196:
        return 206 - byte
    return 0


def test_decode_all_byte_values_match_spec() -> None:
    """Every byte value 0-255 decodes per the reference (all boundaries)."""
    data = bytes(range(256))
    grid = decode_room_id_grid(data, width=256, height=1)
    expected = np.array([_ref_room_id(b) for b in range(256)], dtype=np.int16)
    assert np.array_equal(grid[0], expected)


@st.composite
def _grid_and_data(draw: st.DrawFn) -> tuple[int, int, bytes]:
    width = draw(st.integers(min_value=1, max_value=16))
    height = draw(st.integers(min_value=1, max_value=16))
    # At least width*height bytes (decoder reads the first width*height); allow
    # a few trailing bytes to exercise the truncation slice.
    n = width * height
    data = draw(st.binary(min_size=n, max_size=n + 8))
    return width, height, data


@given(_grid_and_data())
@settings(deadline=None, max_examples=300)
def test_decode_matches_scalar_reference(args: tuple[int, int, bytes]) -> None:
    """Vectorised decode equals the scalar reference for arbitrary shapes."""
    width, height, data = args
    grid = decode_room_id_grid(data, width, height)

    assert grid.shape == (height, width)
    assert grid.dtype == np.int16

    expected = np.array([_ref_room_id(b) for b in data[: width * height]], dtype=np.int16).reshape(
        height, width
    )
    assert np.array_equal(grid, expected)


@given(st.binary(min_size=1, max_size=64))
@settings(deadline=None, max_examples=200)
def test_decoded_room_ids_are_non_negative(data: bytes) -> None:
    """No byte ever decodes to a negative room_id (a Y-flip / mask sign bug)."""
    grid = decode_room_id_grid(data, width=len(data), height=1)
    assert (grid >= 0).all()
