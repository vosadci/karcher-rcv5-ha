# API Gap Analysis — Integration vs. App

Compares the REST and MQTT calls the **HA integration** actually makes against
the **app's startup + control workflow** as seen in the APK decompilation.

Source of truth for the integration:
- `adapter.py` (all karcher-home calls)
- `karcher/karcher.py` (library internals)
- `__init__.py` and `coordinator.py` (call sites)

Source of truth for the app:
- `SplashVm.java` / `SplashActivity.java` (startup)
- `LoginActivity.java` (login)
- `ControlMainActivity.java` (vacuum control)
- All `ApiService.java` / `CommonApiService.java` Retrofit interfaces

---

## App startup + control workflow (what the app does)

### Phase 1: Splash / domain discovery
1. **`GET /network-service/domains/list`** (`tenantId`, `productModeCode`, `version`, `zone`)
   — Resolves region-specific base URLs and MQTT broker hostname.
   Response is AES-encrypted; app decrypts to get `TargetUrls`.

### Phase 2: Authentication
2. **`POST /user-center/auth/login/token`** (stored `auth` token + `userId`)
   — Re-authenticates from cached token on app restart.
   OR on first login / credential change:
   **`POST /user-center/auth/login`** (email + AES-encrypted password)
   — Returns `LoginEntity` containing `auth_token`, `mqtt_token`, `userId`.

### Phase 3: Home screen — device list
3. **`GET /smart-home-service/smartHome/user/getDeviceInfoByUserId/{userId}`**
   — Fetches all devices bound to the account.

### Phase 4: Device control screen (ControlMainActivity)
4. **MQTT CONNECT** to `eu-gamqttaiot.3irobotix.net:8883` using `userId` + `mqtt_token`.
5. **MQTT SUBSCRIBE** to device topics (`property/post`, `cur_path/post`, etc.).
6. **MQTT PUBLISH** `prop.get` to get initial state snapshot.
7. **`POST /storage-management/storage/aws/getAccessUrl`** (to get map CDN URL)
   then **GET `<cdn_url>`** — Downloads the map binary (QuickLZ protobuf).

### Phase 5: Commands (all MQTT, no REST)
- Start/pause/resume: `service_invoke/set_room_clean`
- Return to dock: `service_invoke/start_recharge`
- Cancel dock return: `service_invoke/stop_recharge`
- Set wind/water/mode: `thing/service/property/set` (prop.set)
- Get live path: `service_invoke/get_cur_path` (on demand) or subscribe `cur_path/post`

---

## Integration workflow (what we do)

### Setup / config flow
1. **`GET /network-service/domains/list`** — via `KarcherHome.create()` → `get_urls()`.
2. **`POST /user-center/auth/login`** — via `adapter.authenticate()` → `client.login()`.
3. **`GET /smart-home-service/smartHome/user/getDeviceInfoByUserId/{userId}`** — via
   `adapter.get_devices()` → `client.get_devices()`.

### Coordinator startup (per device, on HA boot / entry reload)
4. Same as #1–3 above (credentials stored, re-login on each HA restart).
5. **MQTT CONNECT + SUBSCRIBE** — via `adapter.subscribe()` → `client.subscribe_device()`.
6. **MQTT PUBLISH `prop.get`** — via `adapter.fetch_properties()` for initial state.
7. **`POST /storage-management/storage/aws/getAccessUrl`** + **GET `<cdn_url>`** —
   via `adapter.get_rooms()` and `adapter.get_map_snapshot()` → `client.get_map_data()`.

### Runtime
8. **MQTT push received** — handled by `_dispatcher` in `adapter.py`.
9. **MQTT PUBLISH** for commands — `adapter.send_command()` / `adapter.set_property()`.
10. **`POST /storage-management/storage/aws/getAccessUrl`** + CDN download — repeated on
    `current_map_id` change or on `has_new_map`.

---

## Gap table

### REST / HTTP

| Endpoint | App does it | We do it | Notes |
|---|---|---|---|
| `GET /network-service/domains/list` | ✅ Phase 1 | ✅ `KarcherHome.create()` | Identical. |
| `POST /user-center/auth/login` | ✅ Phase 2 (first login) | ✅ `client.login()` | Identical. |
| `POST /user-center/auth/login/token` | ✅ Phase 2 (app restart, cached token) | ❌ Not used | **Gap (acceptable).** We store email+password, re-login from scratch each HA restart rather than caching the token. Slightly more network traffic at HA restart; functionally equivalent. Token caching would require persisting the token across HA restarts and handling token expiry — higher complexity for minimal gain. |
| `GET /smart-home-service/smartHome/user/getDeviceInfoByUserId/{userId}` | ✅ Phase 3 | ✅ `client.get_devices()` | Identical. |
| `POST /storage-management/storage/aws/getAccessUrl` + CDN GET | ✅ Phase 4 (map) | ✅ `client.get_map_data()` | Identical. |
| `POST /user-center/auth/logout` | ✅ On sign-out | ❌ Not called | **Gap (intentional).** We never call logout. HA entries are long-lived; the session token expires naturally. Calling logout would invalidate the token and break the session for any shared state. Acceptable. |
| `GET /user-center/app/user/profile` | ✅ After login | ❌ Not called | **Gap (irrelevant to function).** App fetches user profile for display. We don't show a user profile anywhere in HA; device info comes from `get_devices()`. Not needed. |
| Any family/room/share/notification/content/log/firmware endpoint | ✅ Various | ❌ None | **Gap (by design).** These are app-management endpoints (home/room CRUD, sharing, push notifications, FAQ, etc.) that have no equivalent in a HA integration. We only need device state and commands. |

### MQTT

| MQTT operation | App does it | We do it | Notes |
|---|---|---|---|
| CONNECT (userId + mqtt_token, TLS) | ✅ | ✅ via karcher-home | Identical. |
| SUBSCRIBE device topics (`property/post`, `cur_path/post`, etc.) | ✅ | ✅ `subscribe_device()` | Identical. |
| PUBLISH `prop.get` (initial state) | ✅ | ✅ `fetch_properties()` | Identical. Library's `request_device_update()` only requests `ROBOT_PROPERTIES`; our `_fetch_properties_sync` extends the list with `main_brush`, `side_brush`, `hypa`, `mop_life`, `tank_state`, `cloth_state`. **We request more fields than the app's default.** |
| PUBLISH `set_room_clean` (start/pause) | ✅ | ✅ `send_command()` | Identical. |
| PUBLISH `start_recharge` | ✅ | ✅ `send_command()` | Identical. |
| PUBLISH `stop_recharge` | ✅ | ✅ `send_command()` | Identical. |
| PUBLISH `prop.set` (wind / water / mode) | ✅ | ✅ `set_property()` | Identical. |
| PUBLISH `get_cur_path` (on-demand) | ✅ in ControlMainActivity | ❌ Not called | **Gap (minor).** App requests the current path on screen open. We only receive `cur_path/post` push messages. This means after an HA restart during a clean we won't reconstruct the path until the robot sends the next incremental update. Acceptable — the path accumulates quickly during an active clean. |
| RECEIVE `cur_path/post` (push) | ✅ | ✅ `_dispatch_cur_path` | Identical. |
| RECEIVE `property/post` (state push) | ✅ | ✅ `_dispatch_property_post` | Identical. Note: library ignores this event; we patch it with `_update_device_properties`. |
| RECEIVE `upload_by_maptype` / `upload_by_mapid` reply | ✅ MQTT map download path | ❌ Not used | **Gap (different approach).** App can receive the map binary via MQTT reply (`upload_by_maptype`). We use the REST CDN path (`aws/getAccessUrl` → CDN download) via `get_map_data()`. Both result in the same protobuf; the REST path is more reliable (no MQTT size limit). |
| PUBLISH `upload_by_mapid` (request map via MQTT) | ✅ | ❌ Not called | Follows from above — we use CDN instead. |

---

## Summary

**No functional gaps** in the core control loop (start, pause, stop, dock, fan speed,
water level, cleaning mode, state push, battery, consumables, map).

**Three minor gaps worth noting:**

1. **Token re-login vs. credential re-login** — We use credentials on every HA restart
   instead of cached tokens. More network round-trips at startup, but functionally
   equivalent and simpler to implement correctly.

2. **No `get_cur_path` on startup** — After an HA restart mid-clean, the live path
   overlay starts empty and fills as `cur_path/post` pushes arrive. Cosmetic only;
   state transitions are unaffected.

3. **MQTT map download path not used** — We always fetch the map via CDN. The app
   has an alternate MQTT-based download path. No impact in practice.

**No extra/wrong calls**: every call we make is on the critical path — domain
discovery, login, device list, map download, MQTT control. Nothing spurious.
