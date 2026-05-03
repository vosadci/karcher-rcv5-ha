# SPDX-License-Identifier: MIT
"""Contract tests for prop.set encoding of mode and water level."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from custom_components.karcher_home_robots.adapter import AdapterConfig, KarcherAdapter
from tests.contract.test_adapter import _RCV5_PRODUCT_ID, DEVICE, FakeKarcherClient


@pytest.fixture
def fake_client() -> FakeKarcherClient:
    return FakeKarcherClient()


@pytest.fixture
async def adapter(fake_hass: object, fake_client: FakeKarcherClient) -> KarcherAdapter:
    hass = MagicMock()

    async def async_add_executor_job(func: object, *args: object) -> object:
        return func(*args)  # type: ignore[operator]

    hass.async_add_executor_job = async_add_executor_job
    a = KarcherAdapter(
        hass=hass,
        config=AdapterConfig(),
        karcher_factory=lambda: fake_client,
    )
    await a.async_setup()
    await a.subscribe(DEVICE, lambda _: None)
    return a


async def _get_prop_set_payload(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient, params: dict[str, object]
) -> dict[str, object]:
    fake_client._mqtt.published.clear()
    await adapter.set_property(DEVICE, params)
    assert len(fake_client._mqtt.published) == 1
    _, raw = fake_client._mqtt.published[0]
    return json.loads(raw)  # type: ignore[no-any-return]


async def test_mode_vacuum_encodes_zero(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """mode=0 (Vacuum) is published via prop.set (FR-SL-4)."""
    payload = await _get_prop_set_payload(adapter, fake_client, {"mode": 0})
    assert payload["method"] == "prop.set"
    assert payload["params"]["mode"] == 0


async def test_mode_vacuum_and_mop_encodes_one(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """mode=1 (Vacuum & Mop) is published via prop.set (FR-SL-4)."""
    payload = await _get_prop_set_payload(adapter, fake_client, {"mode": 1})
    assert payload["params"]["mode"] == 1


async def test_mode_mop_encodes_two(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """mode=2 (Mop) is published via prop.set (FR-SL-4)."""
    payload = await _get_prop_set_payload(adapter, fake_client, {"mode": 2})
    assert payload["params"]["mode"] == 2


async def test_water_low_encodes_one(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """water=1 (Low) is published via prop.set (FR-SL-5)."""
    payload = await _get_prop_set_payload(adapter, fake_client, {"water": 1})
    assert payload["method"] == "prop.set"
    assert payload["params"]["water"] == 1


async def test_water_medium_encodes_two(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """water=2 (Medium) is published via prop.set (FR-SL-5)."""
    payload = await _get_prop_set_payload(adapter, fake_client, {"water": 2})
    assert payload["params"]["water"] == 2


async def test_water_high_encodes_three(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """water=3 (High) is published via prop.set (FR-SL-5)."""
    payload = await _get_prop_set_payload(adapter, fake_client, {"water": 3})
    assert payload["params"]["water"] == 3


async def test_prop_set_topic_is_correct(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """prop.set uses the property/set topic, not service/invoke (FR-SL-4)."""
    fake_client._mqtt.published.clear()
    await adapter.set_property(DEVICE, {"mode": 1})
    topic, _ = fake_client._mqtt.published[0]
    assert topic == f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/service/property/set"
