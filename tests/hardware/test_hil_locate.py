# SPDX-License-Identifier: MIT
"""HIL: locate command — robot should beep (manual attestation required).

Run with:  KARCHER_HIL=1 RCV5_SN=<sn> RCV5_EMAIL=<e> RCV5_PASSWORD=<pw>
 pytest tests/hardware/ -v -s

You must be within earshot to hear the beep. The test passes if the command
is accepted without an exception; auditory confirmation is manual.

"""

from __future__ import annotations

import pytest
from custom_components.karcher_home_robots.adapter import AdapterConfig, KarcherAdapter


@pytest.mark.asyncio
async def test_locate_accepted(
    device_sn: str,
    hil_region: str,
    hil_email: str,
    hil_password: str,
) -> None:
    """Locate command is accepted without exception.

    Auditory confirmation (robot beeps) is manual.
    """
    adapter = KarcherAdapter(None, AdapterConfig(region=hil_region))  # type: ignore[arg-type]
    await adapter.async_setup()
    await adapter.authenticate(hil_email, hil_password)
    devices = await adapter.get_devices()

    device = next((d for d in devices if d.sn == device_sn), None)
    if device is None:
        pytest.skip(f"device with SN={device_sn} not found on account")

    try:
        # send_command must not raise; actual beep is verified by the tester
        await adapter.send_command(device, "find_me", {})
    finally:
        await adapter.close()
