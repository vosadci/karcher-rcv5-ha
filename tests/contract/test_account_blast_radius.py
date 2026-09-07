# SPDX-License-Identifier: MIT
"""One unknown robot must not take down every other robot on the account.

This is the failure nothing else in the suite could reach. `tests/conftest.py`'s
FakeAdapter bypasses the library entirely, and `test_adapter.py`'s
FakeUpstreamDevice bypasses the real `Device.__init__` — so neither can execute
the eager `Product(product_id)` coercion that caused the bug.

The fake client here mimics upstream's own list comprehension
(`karcher/karcher.py`: `[Device(**d) for d in ...]`) over the **real**
`karcher.device.Device`, so `Product()`, `DeviceStatus()` and
`json.loads(versions)` all actually run. That is the whole point: the blast
radius came from that comprehension having no per-device isolation.

Scoped deliberately to enum behaviour. Display names are asserted in the model
table tests, so this file stays valid independent of what the table says.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from custom_components.karcher_home_robots.adapter import (
    AdapterConfig,
    KarcherAdapter,
    _device_topic,
)
from custom_components.karcher_home_robots.exceptions import UnsupportedDeviceError
from karcher.device import Device

_RCV5 = "1540149850806333440"
# Not in the pinned library's enum, not in our own model table: the case a
# next-generation robot added to a user's account produces. doc/PROTOCOL.md §16.3
# records that the cloud applies no app filter, so we are handed it regardless.
_UNKNOWN = "9999999999999999999"


def _raw(product_id: str, sn: str, versions: str = "[]") -> dict[str, Any]:
    """One device dict shaped as the cloud returns it."""
    return {
        "deviceId": f"dev-{sn}",
        "sn": sn,
        "productId": product_id,
        "nickname": f"robot-{sn}",
        "mac": "00:11:22:33:44:55",
        "status": 1,
        "versions": versions,
    }


class UpstreamLikeClient:
    """Fake cloud client that builds real Devices the way upstream does."""

    def __init__(self, raw_devices: list[dict[str, Any]]) -> None:
        self._raw = raw_devices
        self._base_url = "https://eu.api.example.com"
        self._mqtt_url = "mqtts://eu.mqtt.example.com:8883"
        self._country = "GB"
        self._language = MagicMock()

    async def login(self, *_args: Any, **_kwargs: Any) -> MagicMock:
        return MagicMock()

    async def get_devices(self) -> list[Device]:
        # Deliberately the same shape as karcher/karcher.py: one comprehension,
        # no per-device try. Reproducing it is the test.
        return [Device(**d) for d in self._raw]

    async def close(self) -> None:
        return None


@pytest.fixture
def fake_hass() -> MagicMock:
    hass = MagicMock()

    async def run(func: Any, *args: Any) -> Any:
        return func(*args)

    hass.async_add_executor_job = run
    return hass


async def _adapter_over(raw: list[dict[str, Any]], hass: MagicMock) -> KarcherAdapter:
    adapter = KarcherAdapter(
        hass=hass,
        config=AdapterConfig(),
        karcher_factory=lambda: UpstreamLikeClient(raw),
    )
    await adapter.async_setup()
    return adapter


async def test_unknown_model_does_not_hide_the_working_robot(fake_hass: MagicMock) -> None:
    """The regression this whole change exists to prevent.

    Before `_missing_`, an account holding one unrecognised robot raised
    ValueError inside upstream's comprehension before *any* device was
    returned — so a user's already-working RCV 5 stopped setting up because
    they bought a second, newer robot.
    """
    adapter = await _adapter_over([_raw(_RCV5, "SN-RCV5"), _raw(_UNKNOWN, "SN-NEW")], fake_hass)

    devices = await adapter.get_devices()

    assert [d.sn for d in devices] == ["SN-RCV5", "SN-NEW"]
    assert [d.product_id for d in devices] == [_RCV5, _UNKNOWN]


async def test_unknown_model_is_usable_not_merely_returned(fake_hass: MagicMock) -> None:
    """Being in the list is not enough — the pseudo-member has to behave like a
    product ID everywhere the integration uses one. It is concatenated into MQTT
    topics, and karcher/utils.py reads `.value`."""
    adapter = await _adapter_over([_raw(_UNKNOWN, "SN-NEW")], fake_hass)

    (device,) = await adapter.get_devices()

    assert _device_topic(device.product_id, device.sn, "service") == (
        f"/mqtt/{_UNKNOWN}/SN-NEW/thing/service"
    )
    assert str(device.product_id) == _UNKNOWN


async def test_order_does_not_matter(fake_hass: MagicMock) -> None:
    """The unknown robot first must not strand the ones behind it — the original
    bug was position-independent because the comprehension aborted outright."""
    adapter = await _adapter_over([_raw(_UNKNOWN, "SN-NEW"), _raw(_RCV5, "SN-RCV5")], fake_hass)

    devices = await adapter.get_devices()

    assert [d.sn for d in devices] == ["SN-NEW", "SN-RCV5"]


async def test_a_malformed_payload_still_fails_loudly(fake_hass: MagicMock) -> None:
    """`_missing_` must not turn into a blanket swallow of upstream ValueErrors.

    `Device.__init__` also runs `json.loads(versions)`, which raises for reasons
    that have nothing to do with unknown models. That still has to surface as
    UnsupportedDeviceError rather than being silently tolerated.
    """
    adapter = await _adapter_over([_raw(_RCV5, "SN-RCV5", versions="not-json")], fake_hass)

    with pytest.raises(UnsupportedDeviceError):
        await adapter.get_devices()


async def test_empty_product_id_still_raises(fake_hass: MagicMock) -> None:
    """The `_missing_` hook returns None for an empty string, so a device with no
    product ID stays an error instead of minting a nonsense member."""
    adapter = await _adapter_over([_raw("", "SN-BAD")], fake_hass)

    with pytest.raises(UnsupportedDeviceError):
        await adapter.get_devices()
