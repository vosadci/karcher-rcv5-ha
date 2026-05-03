# SPDX-License-Identifier: MIT
"""HIL: send start command and observe Cleaning state within 2 s.

Run with:  KARCHER_HIL=1 RCV5_SN=<sn> RCV5_EMAIL=<e> RCV5_PASSWORD=<pw>
 pytest tests/hardware/ -v
"""

from __future__ import annotations

import asyncio

import pytest
from custom_components.karcher_home_robots._types import DeviceProperties
from custom_components.karcher_home_robots.adapter import AdapterConfig, KarcherAdapter
from custom_components.karcher_home_robots.coordinator import VacuumState, derive_vacuum_state


@pytest.mark.asyncio
async def test_start_transitions_to_cleaning(
    device_sn: str,
    hil_region: str,
    hil_email: str,
    hil_password: str,
) -> None:
    """Send start command and confirm the robot reports Cleaning within 2 s."""
    adapter = KarcherAdapter(None, AdapterConfig(region=hil_region))  # type: ignore[arg-type]
    await adapter.async_setup()
    await adapter.authenticate(hil_email, hil_password)
    devices = await adapter.get_devices()

    device = next((d for d in devices if d.sn == device_sn), None)
    if device is None:
        pytest.skip(f"device with SN={device_sn} not found on account")

    received: list[DeviceProperties] = []

    def _on_push(props: DeviceProperties) -> None:
        received.append(props)

    await adapter.subscribe(device, _on_push)

    try:
        await adapter.send_command(device, "start", {})

        deadline = asyncio.get_event_loop().time() + 2.0
        while asyncio.get_event_loop().time() < deadline:
            if received:
                break
            await asyncio.sleep(0.1)

        assert received, "No push update received within 2 s after start command"
        state = derive_vacuum_state(received[-1])
        assert state == VacuumState.CLEANING, f"Expected Cleaning, got {state}"
    finally:
        await adapter.send_command(device, "stop", {})
        await adapter.unsubscribe(device)
        await adapter.close()
