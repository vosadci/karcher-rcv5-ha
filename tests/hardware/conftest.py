# SPDX-License-Identifier: MIT
"""Hardware-in-the-loop test fixtures.

All tests in this package are skipped unless KARCHER_HIL=1 and RCV5_SN are set.
Run manually by the maintainer at each release tag.
"""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip all HIL tests unless KARCHER_HIL=1 is set."""
    if os.environ.get("KARCHER_HIL") != "1":
        skip = pytest.mark.skip(reason="set KARCHER_HIL=1 to run hardware tests")
        for item in items:
            if "hardware" in str(item.fspath):
                item.add_marker(skip)


@pytest.fixture(scope="session")
def device_sn() -> str:
    sn = os.environ.get("RCV5_SN", "")
    if not sn:
        pytest.skip("RCV5_SN not set")
    return sn


@pytest.fixture(scope="session")
def hil_region() -> str:
    return os.environ.get("RCV5_REGION", "eu")


@pytest.fixture(scope="session")
def hil_email() -> str:
    email = os.environ.get("RCV5_EMAIL", "")
    if not email:
        pytest.skip("RCV5_EMAIL not set")
    return email


@pytest.fixture(scope="session")
def hil_password() -> str:
    password = os.environ.get("RCV5_PASSWORD", "")
    if not password:
        pytest.skip("RCV5_PASSWORD not set")
    return password
