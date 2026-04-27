# Kärcher Home Robots — Gap Analysis

> Documents where the implementation diverged from the original intent, where decisions were made implicitly rather than explicitly, and where behaviour is undefined or untested.

---

## 1. Divergences from Original Intent

### 1.1 `coordinator.async_setup()` is stated as pending in the plan but is implemented

The session summary and plan file mark "SRP Fix 2 — coordinator.async_setup()" as pending. The actual code in `coordinator.py` includes a fully implemented `async_setup()` and `async_shutdown()`, and `__init__.py` calls `await coordinator.async_setup()`. The plan was not updated to reflect this completion. The implementation is correct; the plan is stale.

**Status:** Implementation ahead of plan. No action required on code; plan should be updated.

---

### 1.2 `conftest.py` mock structure inconsistency

The session summary notes that `conftest.py` was left in an inconsistent state after a mid-stream edit failure. The current `conftest.py` correctly mocks `get_mqtt_adapter()` returning a mock with `subscribe` and `set_callback`. The test files use this interface. This is resolved in the committed code.

**Status:** Resolved. No action required.

---

### 1.3 Room list not persisted across restarts

The original plan (M2-T4) specified that rooms should be stored in `hass.helpers.storage.Store` under `karcher_home_robots.{sn}.rooms` and loaded before first refresh, so that the room picker is available immediately after a restart without waiting for a map fetch.

The current implementation fetches rooms at every startup via `await api.get_rooms(device)` in `__init__.py`, with no persistence layer. If the robot is offline or the map fetch fails, `coordinator.rooms = []` and the room picker is unavailable until the next successful fetch.

**Status:** Intentional simplification or oversight — not documented as a decision. The persistence requirement was in the plan but never implemented. The impact is a degraded experience after HA restart: the room select entity is unavailable until the first successful map fetch.

---

### 1.4 Map image entity not implemented

The original plan included Milestone 6 (map image entity) as a planned feature. This is correctly marked as deferred in the plan and in the README. All prerequisite research is complete (protobuf schema, coordinate transform, renderer design). No divergence — the deferral is intentional and documented.

**Status:** Deferred, documented. No action required.

---

### 1.5 Diagnostics entity not implemented

The original plan (M4-T3) specified a `diagnostics.py` with `async_get_config_entry_diagnostics()` returning redacted config data, raw coordinator data, MQTT status, and room list. This is not implemented. No mention in commits or changelog.

**Status:** Planned, not implemented, not documented as dropped. Low user-visible impact but affects HACS quality scale requirements.

---

### 1.6 MQTT reconnect with exponential backoff not implemented

The plan (M2-T2) specified MQTT reconnect with exponential backoff (30s → 60s → 120s → cap 300s). The current implementation relies entirely on python-karcher's reconnect behaviour, which is not documented and not configurable from outside the library. There is no custom reconnect logic in the integration.

**Status:** Planned, not implemented. The 30-second polling fallback partially mitigates this — after an MQTT disconnect, state will be refreshed by polling within 30 seconds — but the MQTT connection itself may not reconnect promptly depending on library behaviour.

---

### 1.7 `quality_scale: "silver"` in manifest is optimistic

`manifest.json` declares `quality_scale: "silver"`. Silver scale in HA requires diagnostics support, complete test coverage, and reauthentication flow. Diagnostics is not implemented (see 1.5). The quality scale claim is premature.

**Status:** Manifest should declare `"bronze"` or omit the field until diagnostics is implemented.

---

## 2. Implicit Decisions (not recorded in ADRs)

### 2.1 `room_ids = []` fallback when rooms list is empty

When `coordinator.rooms` is empty and the user starts a clean, `async_start()` passes `room_ids = []`. Per PROTOCOL.md §5, an empty list causes the firmware to pick one room semi-randomly — this is known incorrect behaviour. The decision to fall back to this (rather than, e.g., blocking the start or showing an error) was not recorded as a decision.

**Recommendation:** Document in ADR-008 (already covers the explicit list case) and consider surfacing a warning to the user in the HA log.

---

### 2.2 `tls_insecure_set(True)` accepted without comment

The paho-mqtt connection uses `tls_insecure_set(True)` (inherited from python-karcher), which disables server certificate verification on the app side. This is documented in PROTOCOL.md but not in the code comment on the relevant path. The robot does its own cert pinning, so this doesn't create a security gap for device control — but it means the HA integration could be MITM'd between HA and the 3iRobotix broker.

**Recommendation:** Add a code comment at the TLS configuration site explaining the constraint.

---

### 2.3 `device_id` used as unique ID but config entry stores `sn` separately

The config entry stores both `CONF_DEVICE_ID` (used as unique ID for deduplication) and `CONF_DEVICE_SN` (used for MQTT topic construction). The relationship between these two fields is not documented. `device_id` is the 3iRobotix platform identifier; `sn` is the physical serial number printed on the device. They are different values and are not interchangeable.

**Recommendation:** Document in const.py or a comment in config_flow.py.

---

### 2.4 `model = device.product_id.name` exposes library internals in device info

`entity.py` uses `device.product_id.name` as the HA device model string. This exposes the python-karcher `ProductId` enum name (e.g. `"RCV5"`) directly in the UI. If the library renames the enum value, the model string changes for existing users (HA would create a new device entry).

**Recommendation:** Hardcode `model = "RCV5"` in the integration, or map `product_id` values to human-readable strings in `const.py`.

---

### 2.5 Fan speed not included in `extra_state_attributes` deduplication logic

`vacuum.py:extra_state_attributes` includes `wind` (raw int) alongside `fan_speed` on the vacuum entity. Both convey the same information in different formats. The raw `wind` value is useful for debugging but not for end users. No decision was made about whether to include both.

---

### 2.6 `CMD_LOCATE` is defined in `const.py` but its test coverage is absent

`CMD_LOCATE = {"service": "find_device", "params": {}}` is defined and `async_locate()` is implemented in `vacuum.py`. No test asserts that `async_locate()` calls `async_send_command("find_device", {})`. The `find_device` service was confirmed from APK static analysis but not from traffic capture — it has not been verified against the physical robot.

**Recommendation:** Add test for `async_locate()`. Mark as unverified against hardware in PROTOCOL.md.

---

### 2.7 Error sensor behaviour when `fault != 0` during cleaning is implicit

`binary_sensor.py` returns `False` when `fault != 0` but `work_mode` is in the cleaning set. This means transient warnings that the robot emits during normal operation do not trigger the error sensor. This is the correct behaviour per PROTOCOL.md §6, but the logic in `binary_sensor.py` does not reference the work_mode cleaning set directly — it uses a combination of `work_mode in WORK_MODE_IDLE` and `status != STATUS_DOCKED`. The logic is correct but non-obvious.

---

## 3. Behaviour That Is Undefined or Untested

### 3.1 `current_map_id` change handling

The plan specified that a `current_map_id` change should invalidate the stored room list and mark the room select unavailable. This logic is not implemented. If the robot rebuilds its map (new `current_map_id`), the room picker will continue showing the old room names with old IDs — commands using stale room IDs may be silently accepted by the firmware or ignored.

**Severity:** Medium. Map rebuilds are infrequent but do occur (e.g. after factory reset). The only recovery is a manual HA restart.

---

### 3.2 Multiple simultaneous MQTT pushes

The `_subscribed` guard in `MqttAdapter` prevents double-patching of `on_message`. However, if two `subscribe()` calls race (e.g. two coordinators for two robots on the same account), the second call's callback replaces the first's `_push_callbacks` entry before the guard fires. This is likely safe in practice (one coordinator per config entry, config entries load sequentially) but is not tested.

---

### 3.3 Robot with no stored map at first setup

If the robot has never completed a mapping run, `get_map_data()` returns no rooms. `coordinator.rooms = []`. The room select shows "All rooms" only. `async_start()` falls back to `room_ids = []` (firmware picks a room). None of this path is tested — `mock_api.get_rooms` always returns two rooms in fixtures.

**Recommendation:** Add a test fixture with `get_rooms = AsyncMock(return_value=[])` and assert entity behaviour.

---

### 3.4 Reauth with device no longer on account

If the user removes the robot from their Kärcher account and then completes reauth, `__init__.py` will fail with "device not found" (`SETUP_RETRY`). This is handled, but the user experience is poor — the integration will retry indefinitely without a user-facing explanation that the device was removed from the account.

---

### 3.5 `fetch_properties()` timeout behaviour

`api.fetch_properties()` sends `request_device_update()` and waits up to 5 seconds for the `get_reply` topic. If the reply does not arrive within 5 seconds (e.g. robot is powered off), the method's timeout behaviour is not tested. It is unclear whether the library raises, returns stale data, or hangs beyond the timeout.

---

### 3.6 OTA check timing and content

The robot performs an OTA version check to `ota.3irobotix.net:8001` on every cloud connection. This is documented in PROTOCOL.md but no handling exists in the integration for an OTA-triggered firmware update occurring mid-session (which would likely disconnect the MQTT session and cause the robot to restart). The impact on coordinator state is undefined.

---

### 3.7 `clean_type` field in `set_room_clean`

All commands set `clean_type: 0`. PROTOCOL.md notes this is "always 0 in captures; possibly 0=auto, others=specific mode." Non-zero values have never been tested. The field's full semantics are unknown.

---

## 4. Test Coverage Gaps

| Gap | Risk |
|---|---|
| `async_locate()` not tested | Low — fire-and-forget command |
| No-rooms startup path not tested | Medium — `room_ids=[]` fallback is implicit |
| `fetch_properties()` timeout not tested | Medium — could cause integration to hang |
| `current_map_id` change not tested | Medium — stale rooms would cause silent command failures |
| Error sensor in cleaning+fault state not covered | Low — covered by logic but no dedicated test |
| Multiple config entries (two robots) not tested | Low — each entry is independent by design |
| `binary_sensor.py` with `None` coordinator data not tested | Low — same pattern as sensors, but not verified |

---

## 5. Documentation Gaps

| Gap | Location |
|---|---|
| `find_device` service not confirmed by traffic capture | PROTOCOL.md should note it is APK-inferred only |
| `room_ids=[]` empty-list firmware behaviour not linked to start logic | ADR-008 cross-reference missing from vacuum.py comment |
| `clean_type` field semantics undocumented | PROTOCOL.md §5 has a note; const.py CMD_START does not |
| `device_id` vs `sn` distinction not explained in code | Only in PROTOCOL.md |
| `quality_scale: "silver"` claim in manifest not justified | manifest.json should be corrected |
