# SPDX-License-Identifier: MIT
"""Contract tests for the cur_path/post MQTT push path and get_map_snapshot."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from custom_components.karcher_home_robots.adapter import (
    AdapterConfig,
    KarcherAdapter,
    _parse_cur_path,
)
from custom_components.karcher_home_robots.map_data import MapSnapshot
from karcher.exception import KarcherHomeException
from tests.contract.test_adapter import (
    _RCV5_PRODUCT_ID,
    DEVICE,
    FakeKarcherClient,
)


@pytest.fixture
def fake_client() -> FakeKarcherClient:
    return FakeKarcherClient()


@pytest.fixture
def fake_hass() -> MagicMock:
    hass = MagicMock()

    async def async_add_executor_job(func: Any, *args: Any) -> Any:
        return func(*args)

    hass.async_add_executor_job = async_add_executor_job
    return hass


@pytest.fixture
async def adapter(fake_hass: MagicMock, fake_client: FakeKarcherClient) -> KarcherAdapter:
    a = KarcherAdapter(
        hass=fake_hass,
        config=AdapterConfig(),
        karcher_factory=lambda: fake_client,
    )
    await a.async_setup()
    return a


# ---------------------------------------------------------------------------
# _parse_cur_path unit tests
# ---------------------------------------------------------------------------


def test_parse_cur_path_basic() -> None:
    # Wire format: [startPoseId, x0, y0, phi0, flag0, x1, y1, phi1, flag1, endMarker]
    # len=10, (10-2)%4==0, n_points=2
    raw = [0, 1.0, 2.0, 0.0, 0, 3.0, 4.0, 0.0, 1, 99]
    assert _parse_cur_path(raw) == [(1.0, 2.0, 0.0, 0), (3.0, 4.0, 0.0, 1)]


def test_parse_cur_path_single_point() -> None:
    # Wire format: [startPoseId, x0, y0, phi0, flag0, endMarker] → len=6, (6-2)%4==0, n_points=1
    raw = [0, 5.0, 6.0, 0.0, 1, 99]
    result = _parse_cur_path(raw)
    assert len(result) == 1
    assert result[0] == (5.0, 6.0, 0.0, 1)


def test_parse_cur_path_too_short() -> None:
    # len=5 < MIN_LEN(6)
    assert _parse_cur_path([0, 1.0, 2.0, 0.0, 0]) == []


def test_parse_cur_path_wrong_stride() -> None:
    # len=8: (8-2)%4 == 2 ≠ 0
    assert _parse_cur_path([0, 1.0, 2.0, 0.0, 0, 3.0, 4.0, 99]) == []


def test_parse_cur_path_non_list() -> None:
    assert _parse_cur_path(None) == []  # type: ignore[arg-type]
    assert _parse_cur_path("bad") == []  # type: ignore[arg-type]


def test_parse_cur_path_coerces_floats() -> None:
    # Wire format with end marker
    raw = [0, "1.5", "2.5", 0.0, 0, 99]
    result = _parse_cur_path(raw)
    assert result == [(1.5, 2.5, 0.0, 0)]


# ---------------------------------------------------------------------------
# subscribe on_path callback integration tests
# ---------------------------------------------------------------------------


async def test_cur_path_post_invokes_on_path(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """cur_path/post MQTT message triggers on_path callback with correct points."""
    received: list[list[tuple[float, float, float, int]]] = []
    await adapter.subscribe(DEVICE, lambda _: None, on_path=received.append)

    cur_path = [0, 1.0, 2.0, 0.0, 0, 3.0, 4.0, 0.0, 1, 99]
    payload = json.dumps({"params": {"cur_path": cur_path}}).encode()
    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/cur_path/post"

    def fire() -> None:
        fake_client._mqtt.on_message(topic, payload)

    thread = threading.Thread(target=fire)
    thread.start()
    thread.join()
    await asyncio.sleep(0)

    assert len(received) == 1
    assert received[0] == [(1.0, 2.0, 0.0, 0), (3.0, 4.0, 0.0, 1)]


async def test_cur_path_post_ignored_when_no_on_path(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """cur_path/post is silently ignored when no on_path callback is registered."""
    await adapter.subscribe(DEVICE, lambda _: None)  # no on_path

    cur_path = [0, 1.0, 2.0, 0.0, 0, 3.0, 4.0, 0.0, 0, 99]
    payload = json.dumps({"params": {"cur_path": cur_path}}).encode()
    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/cur_path/post"

    fake_client._mqtt.on_message(topic, payload)
    await asyncio.sleep(0)
    # No assertion needed — just must not raise.


async def test_cur_path_post_invalid_payload_no_crash(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Malformed cur_path/post payload does not crash the adapter."""
    received: list[Any] = []
    await adapter.subscribe(DEVICE, lambda _: None, on_path=received.append)

    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/cur_path/post"
    fake_client._mqtt.on_message(topic, b"not-json")
    await asyncio.sleep(0)
    assert received == []


async def test_cur_path_post_wrong_stride_not_delivered(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """cur_path array with wrong stride is silently dropped."""
    received: list[Any] = []
    await adapter.subscribe(DEVICE, lambda _: None, on_path=received.append)

    # len=5: too short (< 6)
    payload = json.dumps({"params": {"cur_path": [0, 1.0, 2.0, 0.0, 0]}}).encode()
    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/cur_path/post"
    fake_client._mqtt.on_message(topic, payload)
    await asyncio.sleep(0)
    assert received == []


async def test_cur_path_post_different_sn_ignored(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """cur_path/post for a different device SN is not delivered."""
    received: list[Any] = []
    await adapter.subscribe(DEVICE, lambda _: None, on_path=received.append)

    # Valid payload but for a different device SN.
    payload = json.dumps({"params": {"cur_path": [0, 1.0, 2.0, 0.0, 0, 99]}}).encode()
    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/OTHER_SN/thing/event/cur_path/post"
    fake_client._mqtt.on_message(topic, payload)
    await asyncio.sleep(0)
    assert received == []


async def test_property_post_with_cur_path_invokes_on_path(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """cur_path embedded in property/post params triggers on_path callback."""
    received: list[list[tuple[float, float, float, int]]] = []
    await adapter.subscribe(DEVICE, lambda _: None, on_path=received.append)

    cur_path = [0, 1.0, 2.0, 0.0, 1, 99]
    payload = json.dumps({"params": {"cur_path": cur_path}}).encode()
    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/property/post"

    def fire() -> None:
        fake_client._mqtt.on_message(topic, payload)

    thread = threading.Thread(target=fire)
    thread.start()
    thread.join()
    await asyncio.sleep(0)

    assert len(received) == 1
    assert received[0] == [(1.0, 2.0, 0.0, 1)]


async def test_property_post_cur_path_no_callback_no_crash(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """property/post with cur_path but no on_path callback is silently ignored."""
    await adapter.subscribe(DEVICE, lambda _: None)  # no on_path

    cur_path = [0, 1.0, 2.0, 0.0, 1, 99]
    payload = json.dumps({"params": {"cur_path": cur_path}}).encode()
    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/property/post"
    fake_client._mqtt.on_message(topic, payload)
    await asyncio.sleep(0)
    # must not raise


async def test_property_post_without_cur_path_not_delivered(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """property/post with no cur_path key does not invoke on_path callback."""
    received: list[Any] = []
    await adapter.subscribe(DEVICE, lambda _: None, on_path=received.append)

    payload = json.dumps({"params": {"work_mode": 1}}).encode()
    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/property/post"

    def fire() -> None:
        fake_client._mqtt.on_message(topic, payload)

    thread = threading.Thread(target=fire)
    thread.start()
    thread.join()
    await asyncio.sleep(0)
    assert received == []


async def test_property_post_invalid_cur_path_not_delivered(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """property/post with a cur_path that fails validation is not delivered."""
    received: list[Any] = []
    await adapter.subscribe(DEVICE, lambda _: None, on_path=received.append)

    # len=5 → too short, parses to []
    payload = json.dumps({"params": {"cur_path": [0, 1.0, 2.0, 0.0, 0]}}).encode()
    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/property/post"

    def fire() -> None:
        fake_client._mqtt.on_message(topic, payload)

    thread = threading.Thread(target=fire)
    thread.start()
    thread.join()
    await asyncio.sleep(0)
    assert received == []


# ---------------------------------------------------------------------------
# get_map_snapshot
# ---------------------------------------------------------------------------


async def test_get_map_snapshot_returns_snapshot(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """get_map_snapshot returns a MapSnapshot when the client has map data."""
    map_mock = MagicMock()
    map_mock.data = {
        "map_head": {"resolution": 0.05, "sizeX": 120, "sizeY": 120, "minX": 0.0, "minY": 0.0},
        "map_data": b"\x00" * 3600,
        "history_pose": {"points": []},
        "current_pose": {"x": 1.0, "y": 1.0, "phi": 0.0},
        "charge_station": {"x": 0.0, "y": 0.0},
    }
    fake_client.map_data_result = map_mock

    snap = await adapter.get_map_snapshot(DEVICE)
    assert isinstance(snap, MapSnapshot)
    assert snap.grid.width == 120
    assert snap.robot is not None


async def test_get_map_snapshot_returns_none_on_exception(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """get_map_snapshot returns None when get_map_data raises an unexpected error."""
    fake_client.map_data_exc = RuntimeError("no map yet")
    snap = await adapter.get_map_snapshot(DEVICE)
    assert snap is None


async def test_get_map_snapshot_raises_on_karcher_exception(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """KarcherHomeException from get_map_data is translated and re-raised."""
    from custom_components.karcher_home_robots.exceptions import NetworkError

    fake_client.map_data_exc = KarcherHomeException(503, "unavailable")
    with pytest.raises(NetworkError):
        await adapter.get_map_snapshot(DEVICE)


async def test_get_map_snapshot_debug_log_on_success(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """get_map_snapshot emits a DEBUG log (snap is not None branch) on successful parse."""
    map_mock = MagicMock()
    map_mock.data = {
        "map_head": {"resolution": 0.05, "sizeX": 10, "sizeY": 10, "minX": 0.0, "minY": 0.0},
        "map_data": b"\x00" * 100,
        "history_pose": {},
        "current_pose": {"x": 0.1, "y": 0.1, "phi": 0.0},
        "charge_station": None,
    }
    fake_client.map_data_result = map_mock

    with patch("custom_components.karcher_home_robots.adapter._LOGGER") as mock_log:
        snap = await adapter.get_map_snapshot(DEVICE)

    assert snap is not None
    mock_log.debug.assert_called()
    # Confirm the debug call that fires when snap is not None was reached.
    calls = [str(c) for c in mock_log.debug.call_args_list]
    assert any("parsed" in c for c in calls)


async def test_get_map_snapshot_returns_none_when_parse_fails(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """get_map_snapshot returns None when _parse_map cannot parse the response."""
    map_mock = MagicMock()
    map_mock.data = {}  # missing map_data key → _parse_map returns None
    fake_client.map_data_result = map_mock

    snap = await adapter.get_map_snapshot(DEVICE)
    assert snap is None


def test_parse_cur_path_bad_float_skipped() -> None:
    """Non-convertible values inside a valid-length array are skipped."""
    # Wire format: [startPoseId, x0, y0, phi0, flag0, endMarker] → len=6.
    # Use None as x — float(None) raises TypeError.
    raw: list[Any] = [0, None, 2.0, 0.0, 1, 99]
    result = _parse_cur_path(raw)
    assert result == []
