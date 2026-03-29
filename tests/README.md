# Testing

## Automated tests

### Setup

```bash
make install   # installs pytest-homeassistant-custom-component and friends
make test      # runs all tests
make test-cov  # runs tests with coverage report
```

Dependencies are listed in [requirements_test.txt](../requirements_test.txt). The framework is `pytest-homeassistant-custom-component`, which provides a real (in-memory) Home Assistant instance for each test.

### Structure

```
tests/
├── conftest.py          — shared fixtures (mock device, API, config entry, coordinator)
├── test_config_flow.py  — config flow: region, credentials, device picker, duplicate prevention, reauth
├── test_coordinator.py  — polling, error handling, MQTT push, vacuum state derivation
├── test_init.py         — integration setup/teardown, platform loading, subscribe ordering
├── test_select.py       — room, cleaning mode, and water level select entities
├── test_sensor.py       — battery sensor
└── test_vacuum.py       — vacuum entity states, commands, fan speed, room control
```

### Test cases

#### `test_config_flow.py`

| Test | What it verifies |
|---|---|
| `test_user_step_shows_region_form` | First step renders the region selector form |
| `test_credentials_step_shows_form` | After picking region, credentials form is shown |
| `test_credentials_invalid_auth` | `KarcherHomeInvalidAuth` → `invalid_auth` error on form |
| `test_credentials_cannot_connect` | `KarcherHomeException` → `cannot_connect` error on form |
| `test_single_device_creates_entry` | 1 device on account → skips picker, creates entry |
| `test_multiple_devices_shows_picker` | 2+ devices → device picker step shown |
| `test_device_selection_creates_entry` | Selecting a device from picker creates entry with correct data |
| `test_duplicate_prevented` | Adding same device_id twice → `already_configured` abort |
| `test_reauth_updates_credentials` | Reauth flow replaces email + password in config entry |
| `test_reauth_invalid_credentials` | Reauth with bad creds → `invalid_auth` error, entry unchanged |

#### `test_coordinator.py`

| Test | What it verifies |
|---|---|
| `test_update_data_returns_properties` | `_async_update_data` calls `fetch_properties` and returns it |
| `test_update_data_token_expired` | `KarcherHomeTokenExpired` → `ConfigEntryAuthFailed` |
| `test_update_data_access_denied` | `KarcherHomeAccessDenied` → `ConfigEntryAuthFailed` |
| `test_update_data_generic_error` | Any other exception → `UpdateFailed` |
| `test_mqtt_push_updates_data` | `handle_mqtt_push(props)` updates `coordinator.data` |
| `test_derive_state_cleaning` | `work_mode` in WORK_MODE_CLEANING → `VacuumState.Cleaning` |
| `test_derive_state_paused` | `work_mode` in WORK_MODE_PAUSE → `VacuumState.Paused` |
| `test_derive_state_returning` | `work_mode` in WORK_MODE_GO_HOME, not docked → `VacuumState.Returning` |
| `test_derive_state_docked_via_status` | idle work_mode + `status=STATUS_DOCKED` → `VacuumState.Docked` |
| `test_derive_state_docked_via_charge_state` | idle work_mode + `charge_state=1` → `VacuumState.Docked` |
| `test_derive_state_error` | idle work_mode + `fault≠0` → `VacuumState.Error` |
| `test_derive_state_go_home_then_docked` | go-home work_mode + `status=STATUS_DOCKED` → `VacuumState.Docked` |

#### `test_init.py`

| Test | What it verifies |
|---|---|
| `test_setup_entry_success` | Coordinator in `hass.data[DOMAIN]`, vacuum + sensor entities registered |
| `test_setup_entry_auth_failed` | `KarcherHomeInvalidAuth` during auth → entry state `SETUP_ERROR` |
| `test_setup_entry_not_ready` | `KarcherHomeException` during auth → entry state `SETUP_RETRY` |
| `test_setup_entry_device_not_found` | Device missing from account → entry state `SETUP_RETRY` |
| `test_unload_entry` | Unload removes coordinator from `hass.data` and calls `api.close()` |
| `test_subscribe_after_first_refresh` | `subscribe_device` is called after first coordinator refresh, not before |

#### `test_select.py`

| Test | What it verifies |
|---|---|
| `test_room_options` | Options = `["All rooms", "Living Room", "Kitchen"]` |
| `test_room_default_all` | Default selection is `"All rooms"` |
| `test_room_select_updates_coordinator` | Selecting "Kitchen" sets `coordinator.selected_room_id = 2` |
| `test_room_select_all_clears_id` | Selecting "All rooms" sets `coordinator.selected_room_id = None` |
| `test_cleaning_mode_options` | Options = `["Vacuum", "Vacuum & Mop", "Mop"]` |
| `test_cleaning_mode_current` | `mode=0` → `"Vacuum"` |
| `test_cleaning_mode_select_mop` | Selecting "Mop" → `set_property({mode: 2})` |
| `test_cleaning_mode_select_vacuum_mop` | Selecting "Vacuum & Mop" → `set_property({mode: 1})` |
| `test_water_level_options` | Options = `["Low", "Medium", "High"]` |
| `test_water_level_current` | `water=2` → `"Medium"` |
| `test_water_level_select_high` | Selecting "High" → `set_property({water: 3})` |
| `test_water_level_select_low` | Selecting "Low" → `set_property({water: 1})` |

#### `test_sensor.py`

| Test | What it verifies |
|---|---|
| `test_battery_value` | `quantity=100` → state `"100"` |
| `test_battery_zero` | `quantity=0` → state `"0"` (not `None`) |
| `test_battery_device_class` | `device_class == SensorDeviceClass.BATTERY` |
| `test_battery_unit` | `unit_of_measurement == "%"` |
| `test_battery_unavailable_when_coordinator_fails` | Coordinator update failure → entity becomes unavailable |

#### `test_vacuum.py`

| Test | What it verifies |
|---|---|
| `test_vacuum_state_docked` | Mock props (docked) → HA state `"docked"` |
| `test_vacuum_state_cleaning` | `work_mode` set to cleaning → HA state `"cleaning"` |
| `test_vacuum_fan_speed` | `wind=1` → `fan_speed == "Standard"` |
| `test_vacuum_fan_speed_list` | Returns all 4 speeds: Silent, Standard, Medium, Turbo |
| `test_vacuum_rooms_in_roborock_format` | `extra_state_attributes["rooms"]` = `"1=Living Room, 2=Kitchen"` |
| `test_async_start_no_room` | `start()` with no room → `set_room_clean({room_ids: [], ctrl_value: 1})` |
| `test_async_start_with_room` | `selected_room_id=1` → `set_room_clean({room_ids: [1], ctrl_value: 1})` |
| `test_async_pause` | `pause()` → `set_room_clean({ctrl_value: 2})` |
| `test_async_stop` | `stop()` → `stop_recharge` command |
| `test_async_return_to_base` | `return_to_base()` → `start_recharge` command |
| `test_async_set_fan_speed_silent` | `set_fan_speed("Silent")` → `set_property({wind: 0})` |
| `test_async_set_fan_speed_turbo` | `set_fan_speed("Turbo")` → `set_property({wind: 3})` |
| `test_async_set_fan_speed_unknown` | Unknown speed → warning logged, no command sent |
| `test_send_command_app_segment_clean` | `app_segment_clean` with `[2]` → `set_room_clean({room_ids: [2]})` |

---

## Manual test plan

Run these scenarios against a real device to confirm end-to-end behaviour. Mark each Pass / Fail / N/A.

### A. Integration setup

| # | Scenario | Expected |
|---|---|---|
| A1 | Add integration — wrong password | "Invalid email address or password" error, stay on form |
| A2 | Add integration — no network | "Failed to connect" error |
| A3 | Add integration — valid credentials | Proceeds to next step |
| A4 | Add integration — single device on account | Skips device picker, creates entry directly |
| A5 | Add integration — try to add same device again | "This device is already configured" abort |
| A6 | Remove integration and re-add | Succeeds cleanly |

### B. State and entities

| # | Scenario | Expected |
|---|---|---|
| B1 | Check all entities after setup | vacuum, battery sensor, 3 select entities all present |
| B2 | Battery % matches Kärcher app | ± 2% |
| B3 | State when docked | `docked` |
| B4 | State after starting | `cleaning` within ~3 seconds |
| B5 | State after pausing | `paused` |
| B6 | State while returning to base | `returning` |
| B7 | State when docked again | `docked` |
| B8 | Rooms match Kärcher app | Names are identical |

### C. Commands

| # | Scenario | Expected |
|---|---|---|
| C1 | Start (all rooms) | Robot leaves dock and starts cleaning |
| C2 | Pause | Robot stops in place |
| C3 | Resume (Start while paused) | Robot continues cleaning |
| C4 | Return to base | Robot navigates to dock |
| C5 | Stop (while returning) | Robot stops in place |
| C6 | Start with a specific room selected | Robot cleans only that room |

### D. Fan speed

| # | Scenario | Expected |
|---|---|---|
| D1 | Set "Silent" | Robot suction decreases; Kärcher app shows "Silent" |
| D2 | Set "Standard" | Kärcher app reflects change |
| D3 | Set "Medium" | Kärcher app reflects change |
| D4 | Set "Turbo" | Robot suction increases; Kärcher app shows "Turbo" |
| D5 | Change fan speed during cleaning | Takes effect immediately |

### E. Cleaning mode and water level (mop attachment required)

| # | Scenario | Expected |
|---|---|---|
| E1 | Set cleaning mode "Vacuum" | Mop disabled in Kärcher app |
| E2 | Set cleaning mode "Vacuum & Mop" | Combined mode shown in Kärcher app |
| E3 | Set cleaning mode "Mop" | Vacuum off, mop on in Kärcher app |
| E4 | Set water level "Low" | Kärcher app reflects low water |
| E5 | Set water level "Medium" | Kärcher app reflects medium water |
| E6 | Set water level "High" | Kärcher app reflects high water |

### F. Apple Home (requires HAMH setup)

| # | Scenario | Expected |
|---|---|---|
| F1 | Robot appears in Apple Home | Vacuum tile visible |
| F2 | Start from Apple Home | Robot starts cleaning |
| F3 | Stop from Apple Home | Robot pauses |
| F4 | Return to base from Apple Home | Robot docks |
| F5 | Battery % visible | Matches HA sensor |
| F6 | Room picker visible | Rooms listed |
| F7 | Select room in Apple Home | Robot cleans that room |
| F8 | Fan speed picker visible | Quiet / Automatic / Max |
| F9 | Change fan speed in Apple Home | Takes effect on robot |
| F10 | Cleaning mode visible | Vacuum / Mop / Vacuum & Mop |
| F11 | Change cleaning mode in Apple Home | Kärcher app reflects change |
| F12 | Mop intensity visible (when mop mode active) | Quiet / Automatic / Max |
| F13 | Change mop intensity in Apple Home | Kärcher app reflects change |

### G. Resilience

| # | Scenario | Expected |
|---|---|---|
| G1 | Restart HA | Entities restore, state correct within 30 s |
| G2 | Robot goes offline (disable Wi-Fi) | Entities become unavailable after polling fails |
| G3 | Robot comes back online | State recovers automatically |
| G4 | HA restart while robot is cleaning | Correct state shown after reconnect |
| G5 | Multiple robots (same account) | Both appear as separate entries, independently controlled |
| G6 | Multiple robots (different accounts) | Both appear as separate entries, independently controlled |

### H. Re-authentication

| # | Scenario | Expected |
|---|---|---|
| H1 | Change password in Kärcher app, restart HA | HA shows "re-authentication required" notification |
| H2 | Complete reauth with new credentials | Integration reloads and works |
| H3 | Reauth with wrong credentials | Error shown, original entry data unchanged |
