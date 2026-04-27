# SPDX-License-Identifier: MIT
"""HIL: app_segment_clean with a real room ID.

Requires at least one room stored on the robot's map. A full cleaning
cycle must have been run at least once to generate the map.

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
async def test_room_clean_starts_cleaning(
    device_sn: str,
    hil_country: str,
    hil_email: str,
    hil_password: str,
) -> None:
    """Send app_segment_clean for the first available room and confirm Cleaning state.

    Covers: FR-V-3 (room clean command end-to-end)
    """
    adapter = KarcherAdapter(None, AdapterConfig(country=hil_country))  # type: ignore[arg-type]
    await adapter.async_setup()
    await adapter.authenticate(hil_email, hil_password)
    devices = await adapter.get_devices()

    device = next((d for d in devices if d.sn == device_sn), None)
    if device is None:
        pytest.skip(f"device with SN={device_sn} not found on account")

    rooms = await adapter.get_rooms(device)
    if not rooms:
        pytest.skip("No rooms on device map — run a full clean first")

    room_id = rooms[0].room_id
    received: list[DeviceProperties] = []

    def _on_push(props: DeviceProperties) -> None:
        received.append(props)

    await adapter.subscribe(device, _on_push)

    try:
        await adapter.send_command(
            device,
            "app_segment_clean",
            {"segments": [room_id], "repeat": 1},
        )

        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            if received:
                state = derive_vacuum_state(received[-1])
                if state == VacuumState.CLEANING:
                    break
            await asyncio.sleep(0.2)

        assert received, "No push update received within 5 s after room clean command"
        final_state = derive_vacuum_state(received[-1])
        assert final_state == VacuumState.CLEANING, f"Expected Cleaning, got {final_state}"
    finally:
        await adapter.send_command(device, "stop", {})
        await adapter.unsubscribe(device)
        await adapter.close()
