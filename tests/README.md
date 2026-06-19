# Testing

## Automated tests

### Setup

```bash
make install   # installs pytest-homeassistant-custom-component and friends
make test      # runs all tests
make test-cov  # runs tests with coverage report
```

Dependencies are declared in the `test` extra in [pyproject.toml](../pyproject.toml). The framework is `pytest-homeassistant-custom-component`, which provides a real (in-memory) Home Assistant instance for each test.

### Structure

```
tests/
├── conftest.py
├── unit/
│   ├── test_state_derivation.py     — VacuumState derivation from work_mode / charge_state / fault
│   ├── test_unique_ids.py           — entity unique_id frozen-list assertion
│   ├── test_diagnostics_redaction.py — PII redaction in diagnostics bundle
│   ├── test_consumable_sensors.py   — main brush / side brush / filter / mop pad life sensors
│   ├── test_image_entity.py         — KarcherMapImage entity (availability, bytes, content-type)
│   ├── test_map_parser.py           — Map.data protobuf dict → MapSnapshot pure parser
│   ├── test_map_render.py           — numpy + Pillow renderer (grid, rooms, paths, objects)
│   └── test_map_cell_map.py         — room_cell_map RLE span encoding
├── contract/
│   ├── test_adapter.py              — adapter public surface: authenticate, fetch_properties, commands
│   ├── test_adapter_coverage.py     — edge-case paths in adapter (close, subscribe, error mapping)
│   ├── test_prop_set_encoding.py    — mode / water / wind prop-set value encoding
│   └── test_cur_path_push.py        — cur_path MQTT push forwarding
└── integration/
    ├── conftest.py
    ├── test_config_flow.py          — config flow: region, credentials, device picker, duplicate, reauth
    ├── test_init_lifecycle.py       — setup/teardown, platform loading, subscribe ordering
    ├── test_coordinator_errors.py   — poll errors, retry, auth failure, outage threshold
    ├── test_outage_repair.py        — persistent repair issue lifecycle
    ├── test_reauth_robustness.py    — silent reauth window, attempt limits
    ├── test_entity_states.py        — entity state / attributes for all entity types
    ├── test_vacuum_commands.py      — start, pause, stop, return, fan speed, room, send_command
    ├── test_room_select.py          — room select availability, options, selection storage
    ├── test_select_availability.py  — cleaning mode disabled_options, water level availability
    └── test_map_coordinator.py      — map ID change, room refresh, snapshot update, path push
```

---

## Manual test plan

Run these scenarios against a real device. Mark each Pass / Fail / N/A.

**Prerequisites:** HA 2026.5.1+, integration installed, robot on Wi-Fi, Kärcher app on phone for reference.

### A. Integration setup

| # | Scenario | Expected |
|---|---|---|
| A1 | Add integration → wrong password | "Invalid email address or password" error, stay on form |
| A2 | Add integration → no network | "Failed to connect" error |
| A3 | Add integration → valid credentials, single device | Skips device picker, creates entry directly |
| A4 | Add integration → valid credentials, multiple devices | Device picker step shown |
| A5 | Add same device again | "This device is already configured" abort |
| A6 | Remove integration and re-add | Succeeds cleanly |

### B. Entities and state

| # | Scenario | Expected |
|---|---|---|
| B1 | Check entities after setup | vacuum, battery + area + time + current_room sensors, error binary sensor, main brush / side brush / filter / mop pad sensors (disabled by default), room / cleaning_mode / water_level selects, map image — all present |
| B2 | Battery % matches Kärcher app | ± 2% |
| B3 | State when docked | `docked` |
| B4 | State after starting | `cleaning` within ~3 s |
| B5 | State after pausing | `paused` |
| B6 | State while returning to base | `returning` |
| B7 | State when docked again | `docked` |
| B8 | Room names match Kärcher app | Identical names and count |

### C. Commands

| # | Scenario | Expected |
|---|---|---|
| C1 | Start (all rooms) | Robot leaves dock and starts cleaning all rooms |
| C2 | Pause | Robot stops in place |
| C3 | Resume (Start while paused) | Robot continues from where it stopped |
| C4 | Return to base | Robot navigates to dock |
| C5 | Stop while returning | Robot stops in place |
| C6 | Start with a specific room selected | Robot cleans that room only |
| C7 | Locate | Robot emits audible beep |

### D. Fan speed

| # | Scenario | Expected |
|---|---|---|
| D1 | Set "Silent" | Kärcher app shows Silent; suction audibly decreases |
| D2 | Set "Standard" | Kärcher app reflects change |
| D3 | Set "Medium" | Kärcher app reflects change |
| D4 | Set "Turbo" | Kärcher app shows Turbo; suction audibly increases |
| D5 | Change fan speed during cleaning | Takes effect within ~3 s |
| D6 | Set any fan speed while in Mop-only mode | Rejected with error; mode unchanged |

### E. Cleaning mode and mop attachment

| # | Scenario | Expected |
|---|---|---|
| E1 | Mop not attached — inspect cleaning_mode entity | `options: ["vacuum", "vacuum_and_mop", "mop"]`; `disabled_options: ["vacuum_and_mop", "mop"]` |
| E2 | Mop not attached — attempt to set "Vacuum & Mop" via HA | Service validation error; mode unchanged |
| E3 | Mop not attached — attempt to set "Mop" via HA | Service validation error; mode unchanged |
| E4 | Set cleaning mode "Vacuum" (mop not required) | Kärcher app shows Vacuum mode |
| E5 | Attach mop (tank_state=3, cloth_state=1) | `disabled_options` clears to `[]`; both mop modes selectable |
| E6 | Set cleaning mode "Vacuum & Mop" (mop attached) | Kärcher app shows Vacuum & Mop; mode auto-switches on attach |
| E7 | Set cleaning mode "Mop" (mop attached) | Kärcher app shows Mop; fan speed becomes unavailable |
| E8 | Remove mop while in Mop mode | `disabled_options` repopulates; mode auto-switches to Vacuum |
| E9 | Attach only mop cloth (no tank) | `disabled_options` still lists mop modes — both required |
| E10 | Attach only tank (no cloth) | `disabled_options` still lists mop modes |

### F. Water level (mop attachment required)

| # | Scenario | Expected |
|---|---|---|
| F1 | Mop not attached | Water level select entity is unavailable |
| F2 | Mop attached, mode = Vacuum | Water level select entity is unavailable |
| F3 | Mop attached, mode = Vacuum & Mop | Water level select entity becomes available |
| F4 | Mop attached, mode = Mop | Water level select entity available |
| F5 | Set water level "Low" | Kärcher app reflects low water |
| F6 | Set water level "Medium" | Kärcher app reflects medium |
| F7 | Set water level "High" | Kärcher app reflects high |

### G. Consumable sensors

| # | Scenario | Expected |
|---|---|---|
| G1 | Enable main brush sensor | Shows remaining life % (0–100); matches Kärcher app |
| G2 | Enable side brush sensor | Shows remaining life % |
| G3 | Enable filter (hypa) sensor | Shows remaining life % |
| G4 | Enable mop pad sensor | Shows remaining life % |

### H. Live floor plan map

| # | Scenario | Expected |
|---|---|---|
| H1 | Map image entity present | `image.<name>_map` entity exists |
| H2 | Map updates while cleaning | Image refreshes every ~10 s during a cleaning run |
| H3 | Map updates on dock | Image refreshes when robot docks |
| H4 | Rooms visible on map | Coloured room fills match Kärcher app layout |
| H5 | Robot position shown | Robot icon visible at correct position |
| H6 | Cleaning path shown | Path trail visible during cleaning |
| H7 | Robot icon heading | Icon points in the robot's actual facing/travel direction — no 180° flip or phi offset (regression: commits 168131d, 0263b1d) |
| H8 | Carpet areas rendered | Carpeted regions shown with distinct carpet shading matching the Kärcher app (regression: commit 1a964b7) |

### I. Custom Lovelace card

| # | Scenario | Expected |
|---|---|---|
| I1 | Card renders | Map canvas, button row, selectors, status line all present |
| I2 | Play/Pause button | Starts cleaning or pauses; icon toggles |
| I3 | Stop button | Stops robot |
| I4 | Dock button | Robot returns to base |
| I5 | Locate button | Robot beeps |
| I6 | Tap room on map | Room highlight visible; room name shown |
| I7 | Cleaning mode selector — mop not attached | Vacuum option active; Vacuum & Mop and Mop grayed out (disabled) |
| I8 | Cleaning mode selector — mop attached | All three options selectable |
| I9 | Fan speed selector in Mop-only mode | Fan speed selector disabled |
| I10 | Water level selector in Vacuum mode | Water level selector disabled |
| I11 | Status line | Shows correct state text and colour dot |
| I12 | Dark theme | Card legible in dark mode — text, icons, and selected-button colours all visible (regression: commit f09fd94) |
| I13 | Map layering | Room labels readable; cleaning path does not occlude labels; active-room overlay translucent enough to see the path through it (regression: commits 194c989, 542811f, 93e1e6e) |
| I14 | HiDPI sharpness | Map canvas renders sharp, not blurry, on a Retina / high-DPI display (regression: commit 194c989) |

> **Why I12–I14 are manual-only:** the vitest suite runs under `happy-dom`, which
> covers DOM structure and text but **not** canvas paint, layout, theming, or
> `adoptStyles`. These visual regression classes recurred ~6× in card history and
> can only be caught by a human looking at a real HA dashboard.

### J. Apple Home via HAMH

Prerequisites: [HA Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) v2.0.46+, iOS/tvOS 18.4+, HAMH configured with `cleaningModeEntity` and `mopIntensityEntity` sub-entries.

| # | Scenario | Expected |
|---|---|---|
| J1 | Robot appears in Apple Home | Vacuum tile visible with correct device name |
| J2 | Start from Apple Home | Robot starts cleaning |
| J3 | Pause from Apple Home | Robot pauses |
| J4 | Return to base from Apple Home | Robot docks |
| J5 | Battery % visible | Matches HA battery sensor ± 2% |
| J6 | Room picker visible | Room names match Kärcher map |
| J7 | Select room in Apple Home | Robot cleans that room only |
| J8 | Fan speed picker visible | Quiet / Automatic / Max |
| J9 | Change fan speed in Apple Home | Takes effect on robot; HA entity reflects new speed |
| J10 | Cleaning mode shows all three options | Vacuum / Vacuum & Mop / Mop always visible (HAMH snapshots options at startup) |
| J11 | Select mop mode with mop absent | Apple Home shows error; robot mode unchanged |
| J12 | Mop attached — mode auto-switches to Vacuum & Mop | Apple Home reflects new mode within ~3 s |
| J13 | Mop removed — mode auto-switches to Vacuum | Apple Home reflects new mode within ~3 s |
| J14 | Mop intensity visible when mop mode active | Quiet / Automatic / Max |
| J15 | Change mop intensity in Apple Home | Kärcher app reflects change |
| J16 | State change latency | Docking / cleaning transitions appear in Apple Home within ≤5 s |

### K. Resilience

| # | Scenario | Expected |
|---|---|---|
| K1 | Restart HA | Entities restore, correct state within 30 s |
| K2 | Robot goes offline (disable Wi-Fi) | Entities become unavailable after polling fails |
| K3 | Robot comes back online | State recovers automatically |
| K4 | HA restart while robot is cleaning | Correct cleaning state shown after reconnect |
| K5 | Cloud outage > 60 min | Persistent repair issue appears in HA notifications |
| K6 | Cloud recovers after outage | Repair issue dismissed automatically; entities return to available |

### L. Re-authentication

| # | Scenario | Expected |
|---|---|---|
| L1 | Change password in Kärcher app, restart HA | HA shows "re-authentication required" notification |
| L2 | Complete reauth with new credentials | Integration reloads and works |
| L3 | Reauth with wrong credentials | Error shown, original entry data unchanged |

### M. Diagnostics

| # | Scenario | Expected |
|---|---|---|
| M1 | Download diagnostics bundle from device page | Bundle downloads successfully |
| M2 | Inspect bundle for sensitive data | No email, password, token, or serial number in plain text |
