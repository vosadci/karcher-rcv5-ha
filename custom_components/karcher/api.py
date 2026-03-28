"""Async wrapper around the python-karcher library."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from karcher.consts import Language, TENANT_ID
from karcher.device import Device, DeviceProperties
from karcher.exception import KarcherHomeAccessDenied
from karcher.karcher import KarcherHome
from karcher.utils import get_timestamp_ms

_LOGGER = logging.getLogger(__name__)

# Confirmed via traffic capture (2026-03-28):
# Topic:   /mqtt/{product_id}/{sn}/thing/service_invoke/{service_name}
# Method:  service.{service_name}
# Payload: {"method": "service.{svc}", "msgId": "...", "params": {...},
#           "tenantId": "...", "version": "3.0"}
_TOPIC_SERVICE_INVOKE = "/mqtt/{product_id}/{sn}/thing/service_invoke/{service}"


class KarcherApi:
    """Thin async wrapper around KarcherHome.

    - KarcherHome.create(), login(), get_devices() are async coroutines and
      are awaited directly.
    - subscribe_device(), request_device_update(), send_command() are
      synchronous (blocking) and are dispatched via run_in_executor.
    """

    def __init__(self, country: str) -> None:
        self._country = country.upper()
        self._client: KarcherHome | None = None
        # Per-device push callbacks: sn → callable(DeviceProperties)
        self._push_callbacks: dict[str, Callable[[DeviceProperties], None]] = {}

    async def authenticate(self, email: str, password: str) -> None:
        """Authenticate and initialise the KarcherHome instance."""
        self._client = await KarcherHome.create(
            country=self._country, language=Language.EN
        )
        await self._client.login(email, password)

    async def get_devices(self) -> list[Device]:
        """Return all devices registered to the account."""
        assert self._client is not None
        return await self._client.get_devices()

    def subscribe_device(
        self,
        dev: Device,
        push_callback: Callable[[DeviceProperties], None],
    ) -> None:
        """Subscribe to MQTT push updates for a device (synchronous).

        Call this from an executor thread via async_add_executor_job.

        Wraps the library's on_message handler so that every processed
        property update also fires ``push_callback(DeviceProperties)``.

        push_callback is called from the paho-mqtt thread — callers are
        responsible for bridging back to the HA event loop via
        hass.loop.call_soon_threadsafe.
        """
        assert self._client is not None

        self._push_callbacks[dev.sn] = push_callback
        # Library call: starts MQTT connection if needed and subscribes topics.
        self._client.subscribe_device(dev)

        # Patch on_message to fire our callback after property updates.
        original_on_message = self._client._mqtt.on_message

        def _patched_on_message(topic: str, payload: bytes) -> None:
            # Library processes first (updates _device_props cache for get_reply).
            original_on_message(topic, payload)

            # The library ignores thing/event/property/post payloads entirely —
            # it sets a wait-event and returns without calling _update_device_properties.
            # Parse and apply the data ourselves so push updates (battery, state, etc.)
            # actually reach the coordinator.
            if "thing/event/property/post" in topic:
                try:
                    data = json.loads(payload)
                    params = data.get("params", {})
                    for sn in self._push_callbacks:
                        if f"/{sn}/" in topic:
                            self._client._update_device_properties(sn, params)
                            break
                except Exception:
                    pass

            # Fire our push callback after property posts/replies.
            if (
                "thing/event/property/post" in topic
                or "thing/service/property/get_reply" in topic
            ):
                for sn, cb in self._push_callbacks.items():
                    if f"/{sn}/" in topic:
                        props = self._client._device_props.get(sn)
                        if props is not None:
                            cb(props)
                        break

        self._client._mqtt.on_message = _patched_on_message

    def request_update(self, dev: Device) -> None:
        """Publish a property-get request (synchronous, run via executor)."""
        assert self._client is not None
        self._client.request_device_update(dev)

    def fetch_properties(self, dev: Device) -> DeviceProperties:
        """Request a full property refresh and block until the reply arrives.

        Unlike KarcherHome.get_device_properties(), this always sends a fresh
        prop.get request even when the device is already subscribed — the library's
        method returns stale cached data immediately in that case.
        """
        assert self._client is not None
        from karcher.mqtt import get_device_topic_property_get_reply
        self._client.request_device_update(dev)
        self._client._wait_for_topic(
            get_device_topic_property_get_reply(dev.product_id, dev.sn),
            timeout=5,
        )
        props = self._client._device_props.get(dev.sn)
        if props is None:
            raise RuntimeError("No device data after property refresh")
        return props

    def send_command(self, dev: Device, service: str, params: dict[str, Any]) -> None:
        """Send a named service command via MQTT (synchronous, run via executor).

        Confirmed topic/payload format from traffic capture (2026-03-28):
          topic:   /mqtt/{product_id}/{sn}/thing/service_invoke/{service}
          payload: {"method": "service.{service}", "msgId": "...",
                    "params": {...}, "tenantId": "...", "version": "3.0"}
        """
        assert self._client is not None
        if self._client._mqtt is None:
            raise KarcherHomeAccessDenied("MQTT not connected")

        topic = _TOPIC_SERVICE_INVOKE.format(
            product_id=dev.product_id.value, sn=dev.sn, service=service
        )
        payload = json.dumps(
            {
                "method": f"service.{service}",
                "msgId": str(get_timestamp_ms()),
                "tenantId": TENANT_ID,
                "version": "3.0",
                "params": params,
            }
        )
        _LOGGER.debug("send_command topic=%s payload=%s", topic, payload)
        self._client._mqtt.publish(topic, payload)

    async def get_rooms(self, dev: Device) -> list[dict]:
        """Return rooms from the stored map as [{id, name}, ...].

        Returns an empty list if no map exists or the map has no rooms yet.
        """
        assert self._client is not None
        try:
            map_data = await self._client.get_map_data(dev, map=1)
            _LOGGER.debug("Map data keys: %s", list(map_data.data.keys()))
            room_data = map_data.data.get("room_data_info", [])
            _LOGGER.debug("Raw room_data_info: %s", room_data)
            rooms = [
                {"id": r["room_id"], "name": r.get("room_name") or f"Room {r['room_id']}"}
                for r in room_data
                if r.get("room_id")
            ]
            _LOGGER.info("Loaded %d rooms: %s", len(rooms), rooms)
            return rooms
        except Exception as err:
            _LOGGER.warning("Could not fetch room list: %s", err)
            return []

    async def async_send_command(self, dev: Device, service: str, params: dict[str, Any]) -> None:
        """Dispatch send_command to the executor (async, HA-safe)."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.send_command, dev, service, params)

    async def close(self) -> None:
        """Close underlying connections."""
        if self._client is not None:
            await self._client.close()
            self._client = None
