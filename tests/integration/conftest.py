# SPDX-License-Identifier: MIT
"""Shared fixtures for integration tests."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in all integration tests."""


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Use Home Assistant's serializer so States and registry entries render."""
    return snapshot.use_extension(HomeAssistantSnapshotExtension)
