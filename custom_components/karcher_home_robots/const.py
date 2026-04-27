# SPDX-License-Identifier: MIT
"""Constants for the Kärcher Home Robots integration."""

from __future__ import annotations

DOMAIN = "karcher_home_robots"

POLL_INTERVAL_SECONDS = 30

# work_mode values grouped by derived HA vacuum state.
# Source: doc/PROTOCOL.md §6, traffic capture 2026-03-28.
WORK_MODE_CLEANING: frozenset[int] = frozenset({1, 7, 25, 30, 36, 81})
WORK_MODE_GO_HOME: frozenset[int] = frozenset({5, 10, 11, 12, 21, 26, 32, 38, 47})
WORK_MODE_PAUSE: frozenset[int] = frozenset({4, 9, 27, 31, 37, 82})
WORK_MODE_IDLE: frozenset[int] = frozenset({0, 14, 23, 29, 35, 40, 85})
