# SPDX-License-Identifier: MIT
"""HIL: kill the TCP session and confirm push updates resume within 30 s.

The test closes the adapter (which disconnects MQTT), re-creates it, and
verifies that a fresh subscribe + fetch_properties succeeds — simulating
broker reconnect after a network interruption.

Run with:  KARCHER_HIL=1 RCV5_SN=<sn> RCV5_EMAIL=<e> RCV5_PASSWORD=<pw>
 pytest tests/hardware/ -v

Covers: FR-UP-6 (resync on reconnect), FR-OF-1 (recovery after outage)
"""

from __future__ import annotations

import asyncio

import pytest
from custom_components.karcher_home_robots._types import DeviceProperties
from custom_components.karcher_home_robots.adapter import AdapterConfig, KarcherAdapter


@pytest.mark.asyncio
async def test_reconnect_resumes_push(
    device_sn: str,
    hil_country: str,
    hil_email: str,
    hil_password: str,
) -> None:
    """After close + re-setup the adapter delivers push updates again within 30 s."""
    config = AdapterConfig(country=hil_country)

    async def _make_adapter() -> KarcherAdapter:
        a = KarcherAdapter(None, config)  # type: ignore[arg-type]
        await a.async_setup()
        await a.authenticate(hil_email, hil_password)
        return a

    # First connection
    adapter = await _make_adapter()
    devices = await adapter.get_devices()
    device = next((d for d in devices if d.sn == device_sn), None)
    if device is None:
        await adapter.close()
        pytest.skip(f"device with SN={device_sn} not found on account")

    # Simulate disconnect
    await adapter.close()

    # Re-connect (simulates coordinator recovery after BrokerDisconnect)
    adapter2 = await _make_adapter()
    devices2 = await adapter2.get_devices()
    device2 = next((d for d in devices2 if d.sn == device_sn), None)
    assert device2 is not None

    received: list[DeviceProperties] = []

    def _on_push(props: DeviceProperties) -> None:
        received.append(props)

    await adapter2.subscribe(device2, _on_push)

    try:
        # A fetch triggers a prop.get → property/post reply which the push bridge
        # delivers to our callback within 30 s per the spec
        props = await adapter2.fetch_properties(device2)
        assert props is not None, "fetch_properties returned None after reconnect"

        # If the push bridge is wired correctly the callback fires during fetch
        deadline = asyncio.get_event_loop().time() + 30.0
        while asyncio.get_event_loop().time() < deadline:
            if received:
                break
            await asyncio.sleep(0.5)

        assert received, "No push update received within 30 s after reconnect"
    finally:
        await adapter2.unsubscribe(device2)
        await adapter2.close()
