"""Adapter — the ONLY module that imports karcher or accesses private symbols.

Responsibilities (ADR-0001, spec/04-architecture.md §3):
  1. Async boundary: every blocking karcher-home call runs in the default
     executor via hass.async_add_executor_job. No synchronous vendor call
     reaches the event loop.
  2. Foreign-thread bridge: paho-mqtt delivers callbacks on its network
     thread. All re-entry into the event loop goes through
     loop.call_soon_threadsafe. Coordinator state is never mutated from
     the MQTT thread.
  3. Work-around containment: the net_stauts typo and the stale
     get_device_properties cache are patched here; the coordinator sees
     clean data.
  4. Exception translation: karcher-home exceptions are mapped to
     ClientError subclasses before leaving this module (ADR-0003).

Allowlisted private symbols used in this module (spec/03 §3.1,
mirrored in ALLOWED_PRIVATE_API in tests/tools/check_imports.py):
  _mqtt                    — bind the paho message callback
  _mqtt.on_message         — set the adapter's threadsafe bridge
  _update_device_properties — bypass the stale get_device_properties cache
  _lib_publish             — publish with library's own envelope and signing
  _lib_wait_for_reply      — wait for MQTT reply on the executor thread
  subscribe_device         — undocumented but required subscription entry-point
  net_stauts               — DeviceProperties typo field (work-around)

HA imports are TYPE_CHECKING-only at module level; no runtime
homeassistant.* import is permitted here (spec/04 §3, ADR-0002).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, cast

from karcher.karcher import KarcherHome

from ._types import KarcherHomeProtocol
from .exceptions import ClientError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


class AdapterConfig:
    """Construction parameters for KarcherAdapter."""

    def __init__(self, region: str) -> None:
        self.region = region


class Device:
    """Opaque device handle returned by get_devices()."""


class Room:
    """Opaque room handle returned by get_rooms()."""


class DeviceProperties:
    """Integration-owned frozen DTO projected from DevicePropertiesProtocol.

    Populated by the adapter from the upstream DevicePropertiesProtocol;
    the coordinator and entities never see the upstream type.
    """


class KarcherAdapter:
    """Thin async wrapper around karcher-home.

    Runs every blocking call in the default executor and bridges
    paho-mqtt foreign-thread callbacks into the event loop via
    loop.call_soon_threadsafe. Maps karcher-home exceptions into
    ClientError subclasses (ADR-0003).

    Accepts an optional karcher_factory callable so tests can inject a
    FakeKarcherClient without patching karcher.* internals
    (spec/04-architecture.md §10).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config: AdapterConfig,
        karcher_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._hass = hass
        self._config = config
        factory = karcher_factory if karcher_factory is not None else KarcherHome
        raw = factory()
        # Cast once here; every subsequent access to self._client is
        # type-checked against KarcherHomeProtocol (spec/04 §4.1.1).
        self._client: KarcherHomeProtocol = cast(KarcherHomeProtocol, raw)

    async def authenticate(self, email: str, password: str) -> None:
        """Authenticate against the 3iRobotix cloud.

        Stores credentials in memory for silent reauth (FR-A-8).
        Raises AuthError on failure.
        """
        raise NotImplementedError

    async def get_devices(self) -> list[Device]:
        """Return the list of devices registered to the account.

        Raises ClientError on failure.
        """
        raise NotImplementedError

    async def get_rooms(self, device: Device) -> list[Room]:
        """Return the room list for device.

        Raises ClientError on failure.
        """
        raise NotImplementedError

    async def subscribe(
        self,
        device: Device,
        on_push: Callable[[DeviceProperties], None],
    ) -> None:
        """Subscribe to MQTT push updates for device.

        on_push is called from the event loop (never from the MQTT thread).
        Raises ClientError on failure.
        """
        raise NotImplementedError

    async def unsubscribe(self, device: Device) -> None:
        """Unsubscribe from MQTT push updates for device."""
        raise NotImplementedError

    async def send_command(
        self,
        device: Device,
        service: str,
        params: Mapping[str, Any],
    ) -> None:
        """Send a service command (e.g. app_segment_clean) to device.

        Raises ClientError on failure.
        """
        raise NotImplementedError

    async def set_property(
        self,
        device: Device,
        params: Mapping[str, Any],
    ) -> None:
        """Send a prop.set command to device.

        Raises ClientError on failure.
        """
        raise NotImplementedError

    async def fetch_properties(self, device: Device) -> DeviceProperties:
        """Fetch current device properties, bypassing the library cache.

        Raises ClientError on failure.
        """
        raise NotImplementedError

    async def close(self) -> None:
        """Release all resources held by this adapter."""
        raise NotImplementedError


__all__ = [
    "AdapterConfig",
    "ClientError",
    "Device",
    "DeviceProperties",
    "KarcherAdapter",
    "Room",
]
