# SPDX-License-Identifier: MIT
"""Additional contract tests for Phase 1 coverage thresholds on adapter.py.

Targets uncovered branches: close exception swallow, get_rooms/subscribe/fetch
error paths, unsubscribe edge cases, mqtt publish exception, translate_exception
branches, int_or_none edge cases.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any
from unittest.mock import MagicMock

import pytest
from custom_components.karcher_home_robots._types import DeviceProperties
from custom_components.karcher_home_robots.adapter import (
    AdapterConfig,
    KarcherAdapter,
    _int_or_none,
    _translate_exception,
)
from custom_components.karcher_home_robots.exceptions import (
    BrokerDisconnect,
    ClientError,
    InvalidCredentials,
    NetworkError,
    RateLimited,
    TokenRejected,
    TransientError,
    ValidationError,
)
from karcher.exception import (
    KarcherHomeException,
    KarcherHomeInvalidAuth,
    KarcherHomeTokenExpired,
)
from tests.contract.test_adapter import (
    _RCV5_PRODUCT_ID,
    DEVICE,
    FakeKarcherClient,
)


@pytest.fixture
def fake_hass() -> MagicMock:
    hass = MagicMock()

    async def async_add_executor_job(func: Any, *args: Any) -> Any:
        return func(*args)

    hass.async_add_executor_job = async_add_executor_job
    return hass


@pytest.fixture
def fake_client() -> FakeKarcherClient:
    return FakeKarcherClient()


@pytest.fixture
async def adapter(fake_hass: MagicMock, fake_client: FakeKarcherClient) -> KarcherAdapter:
    a = KarcherAdapter(
        hass=fake_hass,
        config=AdapterConfig(),
        karcher_factory=lambda: fake_client,
    )
    await a.async_setup()
    return a


async def test_close_swallows_disconnect_exception(
    fake_hass: MagicMock, fake_client: FakeKarcherClient
) -> None:
    """close() swallows exceptions from _disconnect_sync (lines 161-162)."""

    async def bad_executor(func: Any, *args: Any) -> Any:
        raise RuntimeError("disconnect boom")

    fake_hass.async_add_executor_job = bad_executor
    a = KarcherAdapter(
        hass=fake_hass,
        config=AdapterConfig(),
        karcher_factory=lambda: fake_client,
    )
    a._client = fake_client  # type: ignore[assignment]
    await a.close()
    assert a._client is None


async def test_get_rooms_karcher_exception_raises(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """get_rooms raises ClientError on KarcherHomeException (line 233)."""
    fake_client.map_data_exc = KarcherHomeException(500, "map fail")
    with pytest.raises(ClientError):
        await adapter.get_rooms(DEVICE)


async def test_subscribe_karcher_exception_raises(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """subscribe raises ClientError on KarcherHomeException (lines 299-300)."""
    fake_client.subscribe_exc = KarcherHomeException(500, "sub fail")
    with pytest.raises(ClientError):
        await adapter.subscribe(DEVICE, lambda _: None)


async def test_subscribe_no_mqtt_skips_patch(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """subscribe works when _mqtt is None (lines 307-319 mqtt-is-None branch)."""
    fake_client._mqtt = None  # type: ignore[assignment]
    await adapter.subscribe(DEVICE, lambda _: None)


async def test_subscribe_original_on_message_called(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Patched on_message also calls the original handler (lines 314-315)."""
    original_calls: list[tuple[str, bytes]] = []

    def _original(topic: str, payload: bytes) -> None:
        original_calls.append((topic, payload))

    fake_client._mqtt.on_message = _original
    await adapter.subscribe(DEVICE, lambda _: None)

    fake_client._mqtt.on_message(
        f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/event/property/post",
        json.dumps({"params": {"work_mode": 1}}).encode(),
    )
    await asyncio.sleep(0)
    assert len(original_calls) == 1


async def test_push_ignores_wrong_event_type(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Messages on a non-property/post topic are silently dropped (lines 275, 280)."""
    received: list[DeviceProperties] = []
    await adapter.subscribe(DEVICE, received.append)

    payload = json.dumps({"params": {"work_mode": 1}}).encode()
    topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/service/other/topic"
    fake_client._mqtt.on_message(topic, payload)
    await asyncio.sleep(0)
    assert received == []


async def test_unsubscribe_when_client_none(fake_hass: MagicMock) -> None:
    """unsubscribe returns immediately when _client is None (line 324)."""
    a = KarcherAdapter(
        hass=fake_hass,
        config=AdapterConfig(),
        karcher_factory=FakeKarcherClient,
    )
    await a.unsubscribe(DEVICE)


async def test_unsubscribe_swallows_exception(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """unsubscribe swallows exceptions from unsubscribe_device (lines 331-332)."""

    def _bad_unsub(dev: Any) -> None:
        raise RuntimeError("unsub boom")

    fake_client.unsubscribe_device = _bad_unsub
    await adapter.subscribe(DEVICE, lambda _: None)
    await adapter.unsubscribe(DEVICE)


async def test_fetch_properties_karcher_exception_raises(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """fetch_properties raises ClientError on KarcherHomeException (line 407)."""
    await adapter.subscribe(DEVICE, lambda _: None)

    orig = adapter._hass.async_add_executor_job

    async def bad_fetch(func: Any, *args: Any) -> Any:
        if getattr(func, "__name__", "") == "_fetch_properties_sync":
            raise KarcherHomeException(500, "fetch fail")
        return await orig(func, *args)

    adapter._hass.async_add_executor_job = bad_fetch
    with pytest.raises(ClientError):
        await adapter.fetch_properties(DEVICE)


async def test_fetch_properties_no_props_raises_validation_error(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """Reply received but _project_properties returns None -> ValidationError."""
    await adapter.subscribe(DEVICE, lambda _: None)
    # Empty the property cache so _project_properties returns None.
    fake_client._device_props.clear()

    # Make event.wait() return True (reply "received") so we reach _project_properties.
    class _InstantReplyEvent(threading.Event):
        def wait(self, timeout: float | None = None) -> bool:  # type: ignore[override]
            return True

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.karcher_home_robots.adapter.threading.Event",
            _InstantReplyEvent,
        )
        with pytest.raises(ValidationError):
            await adapter.fetch_properties(DEVICE)


async def test_fetch_properties_timeout_raises_transient_error(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """prop.get reply not received within timeout -> TransientError.

    Covers: GAP 3.5, FR-UP-2 timeout path.
    """
    await adapter.subscribe(DEVICE, lambda _: None)
    # Publish succeeds but nobody sets the reply event, so wait() times out.
    # Patch event.wait to return False immediately (simulates instant timeout).
    original_event_class = threading.Event

    class _TimeoutEvent(original_event_class):
        def wait(self, timeout: float | None = None) -> bool:  # type: ignore[override]
            return False  # never set — timeout immediately

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("custom_components.karcher_home_robots.adapter.threading.Event", _TimeoutEvent)
        with pytest.raises(TransientError, match=r"prop\.get reply not received"):
            await adapter.fetch_properties(DEVICE)


async def test_fetch_properties_publish_error_cleans_up_event(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """If mqtt.publish raises, the wait event is removed from _wait_events (F002).

    Covers: event leak fix in _fetch_properties_sync.
    """
    await adapter.subscribe(DEVICE, lambda _: None)

    def _bad_publish(topic: str, payload: str) -> None:
        raise OSError("publish failed")

    fake_client._mqtt.publish = _bad_publish
    reply_topic = f"/mqtt/{_RCV5_PRODUCT_ID}/SN001/thing/service/property/get/reply"

    with pytest.raises(Exception):  # noqa: B017 — any exception from publish propagation
        await adapter.fetch_properties(DEVICE)

    # The event must not remain in _wait_events regardless of the publish failure.
    assert reply_topic not in fake_client._wait_events


async def test_mqtt_publish_exception_raises_broker_disconnect(
    adapter: KarcherAdapter, fake_client: FakeKarcherClient
) -> None:
    """mqtt publish wraps OS errors as BrokerDisconnect (lines 487-488)."""

    def _bad_publish(topic: str, payload: str) -> None:
        raise OSError("network gone")

    fake_client._mqtt.publish = _bad_publish
    with pytest.raises(BrokerDisconnect):
        await adapter.send_command(DEVICE, "start", {})


async def test_translate_exception_rate_limit() -> None:
    """_translate_exception maps HTTP 429 to RateLimited (line 558)."""
    exc = KarcherHomeException(429, "rate limited")
    assert isinstance(_translate_exception(exc), RateLimited)


async def test_translate_exception_generic_maps_to_network_error() -> None:
    """_translate_exception maps unknown KarcherHomeException to NetworkError (line 560)."""
    assert isinstance(_translate_exception(KarcherHomeException(500, "unknown")), NetworkError)


async def test_translate_exception_invalid_auth() -> None:
    """_translate_exception maps KarcherHomeInvalidAuth to InvalidCredentials (line 553)."""
    assert isinstance(_translate_exception(KarcherHomeInvalidAuth()), InvalidCredentials)


async def test_translate_exception_token_expired() -> None:
    """_translate_exception maps KarcherHomeTokenExpired to TokenRejected (line 555)."""
    assert isinstance(_translate_exception(KarcherHomeTokenExpired()), TokenRejected)


async def test_int_or_none_non_numeric_returns_none() -> None:
    """_int_or_none returns None for non-numeric input (line 547)."""
    assert _int_or_none("not-a-number") is None
    assert _int_or_none(None) is None
    assert _int_or_none(42) == 42
    assert _int_or_none("7") == 7
