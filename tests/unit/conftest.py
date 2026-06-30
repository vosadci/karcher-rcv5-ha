# SPDX-License-Identifier: MIT
"""Shared fixtures for unit tests."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Store snapshots under snapshots/ (HA convention), matching integration tests."""
    return snapshot.use_extension(HomeAssistantSnapshotExtension)
