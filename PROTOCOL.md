# Kärcher RCV5 Protocol Notes

Captured via mitmproxy + Android emulator traffic interception (2026-03-28).

## Cloud Architecture

- **REST API**: `https://eu-appaiot.3irobotix.net` — authentication, device listing
- **MQTT broker**: `eu-gamqttaiot.3irobotix.net:8883` — all real-time state and commands
- **Platform**: 3irobotix (not Tuya)
- **Tenant ID**: `1528983614213726208`

## MQTT Topic Patterns

```
# Robot publishes state:
/mqtt/{product_id}/{sn}/thing/event/property/post

# App requests current state:
/mqtt/{product_id}/{sn}/thing/service/property/get
# Robot replies:
/mqtt/{product_id}/{sn}/thing/service/property/get_reply

# App sends a command:
/mqtt/{product_id}/{sn}/thing/service_invoke/{service_name}
# Robot replies:
/mqtt/{product_id}/{sn}/thing/service_invoke/{service_name}_reply
```

## Command Payloads (Confirmed)

```json
// Start cleaning (from dock or idle) / Resume after pause
Topic: .../thing/service_invoke/set_room_clean
{
  "method": "service.set_room_clean",
  "msgId": "<unix_ms_timestamp>",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": {"room_ids": [], "ctrl_value": 1, "clean_type": 0}
}

// Pause during cleaning
Topic: .../thing/service_invoke/set_room_clean
{
  "method": "service.set_room_clean",
  "msgId": "<unix_ms_timestamp>",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": {"room_ids": [], "ctrl_value": 2, "clean_type": 0}
}

// Return to dock
Topic: .../thing/service_invoke/start_recharge
{
  "method": "service.start_recharge",
  "msgId": "<unix_ms_timestamp>",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": {}
}

// Cancel dock return (leaves robot on floor / HA "stop")
Topic: .../thing/service_invoke/stop_recharge
{
  "method": "service.stop_recharge",
  "msgId": "<unix_ms_timestamp>",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": {}
}
```

## State Fields

- `work_mode` — primary state signal (NOT `mode`, which always stays 0)
- `status` — secondary; 4 = docked
- `charge_state` — non-zero when docked/charging
- `fault` — non-zero on error (can coexist with normal operation for minor warnings)
- `quantity` — battery level (0–100)
- `wind` — suction level
- `water` — water level (mop models)
- `cleaning_time` — seconds elapsed in current session
- `cleaning_area` — m² cleaned in current session

### work_mode → HA State Mapping

| work_mode values | HA state |
|---|---|
| 1, 7, 25, 30, 36, 81 | cleaning |
| 4, 9, 27, 31, 37, 82 | paused |
| 5, 10, 11, 12, 21, 26, 32, 38, 47 | returning (+ docked if status=4 or charge_state>0) |
| 0, 14, 23, 29, 35, 40, 85 | idle (+ docked if status=4 or charge_state>0) |

## Local Control Investigation

### TLS / Certificate Pinning

The robot uses MQTT over TLS (port 8883). The real broker cert is:
- Self-signed wildcard: `CN=*.3irobotix.net`
- EC P-256, valid until 2031-11-29
- The robot pins this specific cert (extracted from `server.bks` in the app APK)

The app APK (`KHR_1.4.32_APKPure.apk`) contains:
- `assets/server.bks` — trust store, password `sc2021`. Contains the pinned broker cert.
- `assets/iot_dev.p12` — client cert for REST API mutual TLS, password `hj2WtyHYYEvBTxDb`.
  (Different cert from the broker cert; private key available but not useful for broker impersonation.)

### What Was Tried

1. DNS override: `eu-gamqttaiot.3irobotix.net` → Mac LAN IP (confirmed working via dig + tcpdump)
2. Self-signed server cert (CN + SAN = `eu-gamqttaiot.3irobotix.net`) via Mosquitto
3. TLS spy script: robot completes TLS handshake, then sends **0 bytes** and closes

**Conclusion**: the robot validates the server cert at the application layer after TLS handshake.
It trusts only the cert in `server.bks`; any other cert is rejected silently.

### Path to Local Control

Root access to the robot is required. Options:

1. **UART serial console** (most reliable): RV1126 SoC, UART at 115200 baud.
   Once rooted: add CA cert to `/etc/ssl/certs/` and update MQTT client config to use it,
   or patch the MQTT client binary to skip cert verification.

2. **OTA firmware extraction**: `https://ota.3irobotix.net:8001/service-publish/open/upgrade/try_upgrade`
   Download OTA image, extract rootfs, patch cert store or MQTT config, repack and flash.

3. **No local TCP services**: nmap confirms no open ports. Robot is a pure MQTT client.
