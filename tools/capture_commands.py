"""
Kärcher command capture helper
================================
This script installs itself as the MQTT on_message handler AFTER subscribing
to your device, then logs every outgoing MQTT PUBLISH and every incoming
MQTT message in full.

Run it, manually trigger each robot action in the official app (Start, Pause,
Return to base), then check the log.  All confirmed findings are in PROTOCOL.md.

Usage
-----
    pip install python-karcher aiohttp paho-mqtt  # or your venv equivalent
    python tools/capture_commands.py

Environment variables (or edit the constants below):
    KARCHER_EMAIL      your Kärcher account email
    KARCHER_PASSWORD   your Kärcher account password
    KARCHER_COUNTRY    two-letter country code, e.g. GB, DE, US  (default: GB)
    KARCHER_DEVICE_SN  serial number of the device to target

Confirmed topic pattern (from capture 2026-03-28):
    /mqtt/{product_id}/{sn}/thing/service_invoke/{service_name}

Confirmed payload format:
    {"method": "service.{service_name}", "msgId": "<unix_ms>",
     "tenantId": "1528983614213726208", "version": "3.0", "params": {...}}

Confirmed commands:
    set_room_clean  params={"room_ids":[],"ctrl_value":1,"clean_type":0}  → start/resume
    set_room_clean  params={"room_ids":[],"ctrl_value":2,"clean_type":0}  → pause
    start_recharge  params={}                                              → return to dock
    stop_recharge   params={}                                              → cancel dock return

Note: python-karcher has a typo in DeviceProperties ('net_stauts' vs 'net_status').
The on_message handler here wraps the original call in try/except AttributeError
to prevent the crash from killing the MQTT thread.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
_LOGGER = logging.getLogger("capture")

KARCHER_EMAIL    = os.environ.get("KARCHER_EMAIL", "YOUR_EMAIL_HERE")
KARCHER_PASSWORD = os.environ.get("KARCHER_PASSWORD", "YOUR_PASSWORD_HERE")
KARCHER_COUNTRY  = os.environ.get("KARCHER_COUNTRY", "GB")
KARCHER_DEVICE_SN = os.environ.get("KARCHER_DEVICE_SN", "YOUR_DEVICE_SN_HERE")


def _patch_mqtt_client(mqtt_client):
    """Monkey-patch MqttClient to log every publish and every message."""

    original_publish = mqtt_client.publish

    def patched_publish(topic, payload):
        _LOGGER.info("[OUTGOING PUBLISH]\n  topic  : %s\n  payload: %s", topic, payload)
        try:
            parsed = json.loads(payload)
            _LOGGER.info("[OUTGOING JSON]\n%s", json.dumps(parsed, indent=2))
        except Exception:
            pass
        return original_publish(topic, payload)

    mqtt_client.publish = patched_publish

    original_on_message = mqtt_client.on_message

    def patched_on_message(topic, payload):
        _LOGGER.info(
            "[INCOMING MESSAGE]\n  topic  : %s\n  payload: %s",
            topic,
            payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload,
        )
        if original_on_message is not None:
            try:
                original_on_message(topic, payload)
            except AttributeError:
                # python-karcher has a typo: 'net_stauts' vs 'net_status'.
                # Swallow the crash so the MQTT thread keeps running.
                pass

    mqtt_client.on_message = patched_on_message


async def main():
    from karcher.karcher import KarcherHome

    _LOGGER.info("Authenticating as %s (country: %s)...", KARCHER_EMAIL, KARCHER_COUNTRY)
    client = await KarcherHome.create(country=KARCHER_COUNTRY)
    session = await client.login(KARCHER_EMAIL, KARCHER_PASSWORD)
    _LOGGER.info("Logged in  user_id=%s", session.user_id)

    devices = await client.get_devices()
    if not devices:
        _LOGGER.error("No devices found in this account.")
        return

    for i, d in enumerate(devices):
        _LOGGER.info("  [%d] %s  sn=%s  product_id=%s", i, d.nickname, d.sn, d.product_id)

    # Find the target device by SN, fall back to first device.
    dev = next((d for d in devices if d.sn == KARCHER_DEVICE_SN), devices[0])
    _LOGGER.info("Target device: %s (sn=%s)", dev.nickname, dev.sn)

    client.subscribe_device(dev)
    _patch_mqtt_client(client._mqtt)

    # Log subscription acknowledgements from broker.
    original_on_connect = client._mqtt._client.on_connect
    def _on_connect(c, userdata, flags, rc):
        _LOGGER.info("[MQTT CONNECTED] rc=%d  flags=%s", rc, flags)
        if original_on_connect:
            original_on_connect(c, userdata, flags, rc)
    client._mqtt._client.on_connect = _on_connect

    client._mqtt._client.on_subscribe = lambda c, u, mid, granted: \
        _LOGGER.info("[MQTT SUBSCRIBED] mid=%d  granted_qos=%s", mid, granted)

    # Subscribe to wildcard for every device in the account.
    for d in devices:
        wildcard = f"/mqtt/{d.product_id.value}/{d.sn}/#"
        _LOGGER.info("Subscribing wildcard: %s", wildcard)
        client._mqtt._client.subscribe(wildcard, 0)

    # Request an initial property update.
    _LOGGER.info("Requesting initial property update for %s...", dev.nickname)
    client.request_device_update(dev)
    for d in devices[1:]:
        _LOGGER.info("Requesting initial property update for %s...", d.nickname)
        client._device_props[d.sn] = __import__('karcher.device', fromlist=['DeviceProperties']).DeviceProperties()
        client.request_device_update(d)

    _LOGGER.info(
        "\n"
        "========================================================\n"
        "  Listening for MQTT messages.  Now use the Kärcher app\n"
        "  and press: Start, Pause, Return to base, Stop.\n"
        "  All MQTT traffic will be logged above.\n"
        "  Press Ctrl-C to stop.\n"
        "========================================================"
    )

    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    loop.add_signal_handler(signal.SIGINT, stop.set_result, None)
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)

    await stop
    _LOGGER.info("Shutting down...")
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
