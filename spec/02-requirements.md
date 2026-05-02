# 02 — Requirements (SRS)

Requirement IDs are stable across the spec set. Each module in
`04-architecture.md` maps to a set of IDs; tests cite them in
docstrings by convention (not a CI gate — see
`adr/0004-testing-strategy.md`).

- `FR-*`  functional requirement
- `NFR-*` non-functional requirement
- `SEC-*` security requirement
- `OPS-*` operational requirement

Where a requirement is a hard carry-over from the existing `doc/`
documents, the source is cited. Where a requirement is new for the
rewrite, the source reads **(new)**.

## 1. Functional requirements

### 1.1 Setup, auth, and reauth (FR-A)

| ID | Requirement | Source |
|---|---|---|
| FR-A-1 | The user picks a region (EU, US, CN) in step 1 of the config flow | FUNCTIONAL_SPEC §4.1 |
| FR-A-2 | The user provides email and password in step 2 | FUNCTIONAL_SPEC §4.1 |
| FR-A-3 | Single-device account: config entry is created immediately after credentials | FUNCTIONAL_SPEC §4.1 |
| FR-A-4 | Multi-device account: the user picks the device to associate | FUNCTIONAL_SPEC §4.1 |
| FR-A-5 | The integration deduplicates devices by the 3iRobotix platform `device_id` | FUNCTIONAL_SPEC §4.1 |
| FR-A-6 | Auth failure and network failure are surfaced via distinct translation keys | FUNCTIONAL_SPEC §4.1 |
| FR-A-7 | Reauth flow updates credentials without deleting the config entry; region and `device_id` are preserved | FUNCTIONAL_SPEC §4.1 |
| FR-A-8 | The integration **persists** the email and password in the config entry (HA-encrypted at rest via `config_entries`). On runtime token expiry the adapter calls `KarcherHomeProtocol.login()` again with the persisted credentials, transparently to the user. The user does not see a reauth prompt on token expiry alone. | (new, supersedes earlier draft) |
| FR-A-8a | Silent reauth is bounded: at most **3 attempts** within a 5-minute window, with exponential backoff (5 s, 30 s, 2 min). Beyond that the integration raises `ConfigEntryAuthFailed` and surfaces HA's reauth notification, on the assumption that the persisted password is actually invalid (changed in the vendor app, account suspended, etc.). | (new) |
| FR-A-8b | Authentication failures from `KarcherHomeProtocol.login()` that distinguish "wrong credentials" from "transient" must drive different behaviour: `AuthError` → immediate `ConfigEntryAuthFailed`; any other `ClientError` subclass → backoff + retry per FR-A-8a. The mapping is owned by `adapter.py` per ADR-0003. | (new) |
| FR-A-9 | No device on the account yields an error with a `no_devices` translation key; the flow does not silently succeed | (new) |
| FR-A-10 | Rate-limit responses during reauth (HTTP 429, explicit throttle) are surfaced as `TransientError` with `Retry-After` honoured up to a bounded ceiling (60 s). The user is not shown a cryptic auth failure for what is actually a vendor throttle. | (new, resolves gap) |
| FR-A-11 | The user-initiated reauth flow (Settings → Integrations → Reauthenticate) collects the password only — region and device are taken from the existing config entry. On success, the persisted password is updated; the existing entity unique_ids and registry entries are preserved (no re-keying). | (new) |

### 1.2 Region routing and endpoint snapshot (FR-RG)

| ID | Requirement | Source |
|---|---|---|
| FR-RG-1 | `region` is stored in config-entry `data` and is immutable after initial setup (changing it requires delete + re-add) | (new) |
| FR-RG-2 | At auth time the adapter stores a `region_endpoint_snapshot` (broker host:port, REST base URL, CA fingerprint) in config-entry `data` | (new) |
| FR-RG-3 | On HA restart the adapter reconnects using the stored snapshot; region-discovery REST is not re-invoked unless the snapshot is missing or stale | (new) |
| FR-RG-4 | If the snapshot's CA fingerprint no longer matches what the broker presents, the adapter surfaces `TransientError`; entities become unavailable; the user is pointed to the re-auth flow via a `repair` (NFR-R-6) | (new, resolves cert-rotation gap) |
| FR-RG-5 | Region-discovery REST is idempotent and has a bounded timeout (5 s); failures are `TransientError`, not `AuthError` | (new) |

### 1.3 Entity migration (FR-MG)

| ID | Requirement | Source |
|---|---|---|
| FR-MG-1 | Entity unique_id shape is `{device_id}_{entity_type}` with `entity_type ∈ {vacuum, battery, cleaning_area, cleaning_time, error, room, cleaning_mode, water_level}`. A test asserts exact equality against a frozen list. | (new) |
| FR-MG-2 | `async_migrate_entry` bumps entry `version` from 1 → 2. The data-shape change is: add `region_endpoint_snapshot`, drop `product_id` redundancy. | (new) |
| FR-MG-3 | On migration, any entity-registry entry whose unique_id does not match the frozen list is re-keyed to the canonical form (pre-rewrite releases sometimes wrote legacy IDs). | (new) |
| FR-MG-4 | Migration is covered by an integration test that (a) starts with a version-1 entry, (b) migrates, (c) asserts entities still resolve against the same HA entity_ids. | (new) |
| FR-MG-5 | If migration itself raises, `async_migrate_entry` returns `False` (HA default behaviour). The entry stays at the pre-migration `version` and the integration shows as "failed to load". The exception is logged at ERROR level with the full traceback; secrets in the entry's `data` are redacted by the existing diagnostics-redaction logic (FR-D-2). | (new) |
| FR-MG-5a | On migration failure (FR-MG-5) the integration creates a persistent HA `repair` issue with translation key `migration_failed_v{from}_v{to}`, telling the user (a) which version pair failed, (b) to downgrade the integration to the version that previously loaded the entry, and (c) to file an issue with the diagnostics download. The repair issue dismisses itself if a subsequent migration attempt succeeds. | (new) |
| FR-MG-5b | Rollback is **not** attempted. Snapshot-and-restore was rejected as fighting HA's `ConfigEntry` API, which has no transaction model. This matches HA core integration practice. The maintainer prevents migration breakage by making each migration step covered by FR-MG-4 before tagging the release; this is the per-release DoD's `Upgrade test` (`spec/08-definition-of-done.md` §3 item 10). | (new) |

### 1.4 Offline semantics (FR-OF)

| ID | Requirement | Source |
|---|---|---|
| FR-OF-1 | When the cloud is unreachable (network down, DNS fail, broker refuses connection), the coordinator raises `UpdateFailed`. Entities become unavailable. This is the normative "offline" state. | (new) |
| FR-OF-2 | The integration does **not** queue commands issued while offline. A command issued while the coordinator is in `UpdateFailed` raises `HomeAssistantError` with a translated message; it is not silently accepted. | (new) |
| FR-OF-3 | On reconnect, the coordinator performs a forced `fetch_properties` before surfacing any push, so that the UI is not stuck on a stale pre-disconnect snapshot. | (new) |
| FR-OF-4 | ~~A single `binary_sensor` (or diagnostic attribute) indicates cloud reachability at any moment. This is not a separate entity; it is an attribute on the vacuum entity (`cloud_connected: bool`) to avoid entity-count inflation.~~ **Deferred post-Phase-4.** The `available` property on all entities already communicates cloud reachability to the user. A separate `cloud_connected` attribute adds no actionable signal beyond what HA's unavailable state provides. Revisit if a concrete user need arises. | (new; deferred 2026-05-02) |
| FR-OF-5 | The coordinator's `available` flag does not flap on single-poll failures: a sliding window of 2 consecutive poll failures is required before `UpdateFailed` is raised. | (new, resolves flapping-availability gap) |
| FR-OF-6 | After **1 h** of continuous `UpdateFailed`, the integration creates a persistent HA `repair` issue with translation key `cloud_outage_persistent`, telling the user (a) the cloud has been unreachable for over an hour, (b) this is usually a vendor outage rather than the integration or their network, (c) entities will recover automatically when the cloud returns, and (d) no user action is required. The threshold is a constant `OUTAGE_REPAIR_THRESHOLD = timedelta(hours=1)` in `coordinator.py`; tunable in code, not in config. **Phase 4 (P4-11).** | (new) |
| FR-OF-7 | The repair issue from FR-OF-6 dismisses itself on the first successful `_async_update_data` after the issue was created. **Phase 4 (P4-11).** | (new) |
| FR-OF-8 | Log spam is bounded during outage. The first poll failure logs at WARNING with the full traceback; subsequent failures log at INFO with a single line until the cloud recovers, but log frequency drops to one line per **10 minutes** after the first 5 minutes of continuous failure. The full traceback is re-logged on each transition (online→offline, offline→online). **Phase 4 (P4-12).** | (new) |

### 1.5 Vacuum entity (MVP in Phase 1) (FR-V)

| ID | Requirement | Source |
|---|---|---|
| FR-V-1 | `async_start`: if no room is selected and a room list is known, pass the explicit list of all known room IDs | ADR history |
| FR-V-2 | `async_start`: if a specific room is selected, pass a single-element list containing that room ID | FUNCTIONAL_SPEC §6 |
| FR-V-3 | `async_start`: if the robot is in `Paused` state, pass `room_ids=[]` to resume from the current position | ADR history |
| FR-V-4 | `async_pause` pauses an in-progress clean | FUNCTIONAL_SPEC §4.2 |
| FR-V-5 | `async_stop` cancels the current action; if returning, the robot stops where it is | FUNCTIONAL_SPEC §4.2 |
| FR-V-6 | `async_return_to_base` sends the robot to the charger | FUNCTIONAL_SPEC §4.2 |
| FR-V-7 | `async_locate` emits an audible beep on the robot | FUNCTIONAL_SPEC §4.2 |
| FR-V-8 | Fan speed `Silent`, `Standard`, `Medium`, `Turbo`; unavailable when mode = Mop-only | FUNCTIONAL_SPEC §4.2 |
| FR-V-9 | `activity` reflects `Cleaning / Paused / Returning / Docked / Idle / Error` per `04-architecture.md` §5 | — |
| FR-V-10 | State changes propagate to the entity within 2 s (push) and 30 s (poll) | NFR §1.1 |
| FR-V-11 | Rooms exposed on entity attributes in Roborock format `{id_as_string: name}` | FUNCTIONAL_SPEC §4.7 |
| FR-V-12 | Service `send_command("app_segment_clean", [room_ids])` cleans the named rooms | FUNCTIONAL_SPEC §4.2 |

### 1.6 Sensors (FR-SE)

| ID | Requirement | Source |
|---|---|---|
| FR-SE-1 | Battery percentage as a dedicated `SensorEntity` with `SensorDeviceClass.BATTERY`, not an attribute of the vacuum entity (HA 2026.8 removed battery from `VacuumEntity`) | — |
| FR-SE-2 | Cleaning-area sensor (m², derived as `raw / 100`), unit `m²`, `state_class: measurement` | FUNCTIONAL_SPEC §4.3 |
| FR-SE-3 | Cleaning-time sensor (min), `device_class: duration`, `state_class: measurement` | FUNCTIONAL_SPEC §4.3 |
| FR-SE-4 | Sensors return `None` (HA UI: unavailable) when coordinator data has not loaded | FUNCTIONAL_SPEC §4.3 |

### 1.7 Binary sensor (FR-BS)

| ID | Requirement | Source |
|---|---|---|
| FR-BS-1 | Error indicator is `on` only if `fault != 0` AND `work_mode ∈ idle` AND NOT docked (derived from `vacuum_state == Error`) | FUNCTIONAL_SPEC §4.4, PROTOCOL §6 |
| FR-BS-2 | Transient faults during cleaning or returning do not flip the error sensor | FUNCTIONAL_SPEC §4.4 |
| FR-BS-3 | Device class is `problem`; icon `mdi:robot-vacuum-alert` | (new) |

### 1.8 Select entities (FR-SL)

| ID | Requirement | Source |
|---|---|---|
| FR-SL-1 | Room select options: `All rooms` plus each named room from the stored map | FUNCTIONAL_SPEC §4.5 |
| FR-SL-2 | Room select is unavailable when no rooms are known | FUNCTIONAL_SPEC §4.5 |
| FR-SL-3 | Current room selection is held by the coordinator and consumed by the vacuum `async_start` | — |
| FR-SL-4 | Cleaning-mode select writes `mode ∈ {0,1,2}` via `prop.set`; takes effect immediately | FUNCTIONAL_SPEC §4.5 |
| FR-SL-5 | Water-level select: `Low`, `Medium`, `High`; unavailable when mode is Vacuum-only | FUNCTIONAL_SPEC §4.5 |
| FR-SL-6 | Water-level entity has `entity_registry_enabled_default = False` | — |
| FR-SL-7 | When `current_map_id` changes, the room list is invalidated and re-fetched; the select state clears to `All rooms` and becomes unavailable until the new list arrives | (new, resolves GAP-3.1) |

### 1.9 State updates (FR-UP)

| ID | Requirement | Source |
|---|---|---|
| FR-UP-1 | Primary update mechanism: MQTT push on `thing/event/property/post` | — |
| FR-UP-2 | Fallback: coordinator polling at 30 s intervals | — |
| FR-UP-3 | MQTT subscribes before the first poll; the callback is wired so the first push does not race the first poll's `async_set_updated_data` | — |
| FR-UP-4 | paho-mqtt callbacks arrive on a foreign thread; the adapter re-enters the event loop exclusively via `loop.call_soon_threadsafe`. Coordinator state is never mutated from the mqtt thread. | NFR §7.3 |
| FR-UP-5 | Push/poll ordering is resolved by monotonic HA-side receipt timestamps, not device-reported timestamps (which skew by tens of seconds). Older-than-current updates are discarded. | (new, resolves clock-skew gap) |
| FR-UP-6 | Reconnect is handled inside `karcher-home` with the library's backoff; the adapter re-subscribes and forces a `fetch_properties` on reconnect so the UI resyncs immediately. | — |

### 1.10 Entity conformance for downstream Matter bridges (FR-AH)

The integration ships no Matter code and has no runtime dependency
on any bridge. The requirements below pin the **shape of this
integration's entities** so that downstream bridges that map HA
entities into a Matter fabric — primarily Home Assistant Matter
Hub ([HAMH](https://github.com/RiDDiX/home-assistant-matter-hub)) —
can discover and expose them without integration-specific code on
their side. Apple Home support is a side-effect of conformance plus
the user installing HAMH separately; it is not a feature of this
integration.

| ID | Requirement | Source |
|---|---|---|
| FR-AH-1 | The vacuum entity exposes rooms as `{id_str: name}` (Roborock-shaped). Tested directly against the entity's `state_attributes`; no bridge runtime is involved. | FUNCTIONAL_SPEC §4.7 |
| FR-AH-2 | The cleaning-mode and water-level select entities are independent `SelectEntity`s with stable `option` lists. Tested at the entity level. | FUNCTIONAL_SPEC §4.7 |
| FR-AH-3 | The fan-speed `select` exposes options that map cleanly onto Matter `RvcCleanMode`: Silent → Quiet, Standard/Medium → Auto, Turbo → Max. The mapping is documented in the entity's docstring; the test asserts the option strings exist. | FUNCTIONAL_SPEC §4.7 |

A change to any of the three FR-AH rows is a breaking change for
downstream Matter bridges (and therefore for Apple Home users who
go through one) and must be called out in `CHANGELOG.md`. The
integration does not run, ship, or test against HAMH itself; HAMH
testing is HAMH's responsibility.

### 1.11 Diagnostics (FR-D)

| ID | Requirement | Source |
|---|---|---|
| FR-D-1 | `diagnostics.py` implements `async_get_config_entry_diagnostics` returning redacted credentials and config, last-known `DeviceProperties`, MQTT connection status, subscription topics, reconnect stats, room list, `karcher-home` version, and the CA fingerprint from the endpoint snapshot | (new, resolves GAP-1.5) |
| FR-D-2 | Redaction covers email, password, token, nonce, and serial-number fields. Covered by a unit test that diffs the diagnostic bundle against a regex. | (new) |

## 2. Non-functional requirements

### 2.1 Performance

| ID | Requirement |
|---|---|
| NFR-P-1 | Push→entity latency ≤ 2 s in 95th percentile, measured over a rolling 1 h window on HIL |
| NFR-P-2 | Poll interval 30 s, a constant in `const.py`, not user-tunable |
| NFR-P-3 | `prop.get` reply timeout 5 s; timeout raises `TransientError` and leaves previous `coordinator.data` in place |
| NFR-P-4 | Setup completes within HA's first-refresh timeout (~10 s) under nominal network conditions |
| NFR-P-5 | The HA event loop is never blocked for more than 50 ms by any integration code path (the adapter's executor calls do not count toward this because they do not run on the loop) |

### 2.2 Reliability

| ID | Requirement |
|---|---|
| NFR-R-1 | MQTT disconnect → reconnect per FR-UP-6; coordinator remains queryable throughout |
| NFR-R-2 | Token expiry recovers via reauth without losing the config entry |
| NFR-R-3 | Cloud unavailability is not fatal; entities go unavailable and recover automatically (FR-OF) |
| NFR-R-4 | The integration is fully operational after an HA restart without user input, provided credentials remain valid |
| NFR-R-5 | The coordinator tolerates a race where push and poll arrive in either order; monotonic HA-side timestamp resolves ordering |
| NFR-R-6 | CA-rotation graceful degradation: if the broker's cert no longer validates against the snapshot's CA fingerprint, the integration raises an HA `repair` (actionable user-visible notice) rather than silently falling back to insecure TLS or silently refusing to reconnect |

### 2.3 Scale

| ID | Requirement |
|---|---|
| NFR-SC-1 | Multiple config entries (multiple robots) coexist with no shared state |
| NFR-SC-2 | Multiple accounts on one HA instance coexist |
| NFR-SC-3 | One adapter instance per config entry; no process-global state |

### 2.4 Maintainability

| ID | Requirement |
|---|---|
| NFR-M-1 | Any module is understandable in isolation: cyclomatic complexity ≤ 10 per function; file length ≤ 500 LOC |
| NFR-M-2 | `mypy --strict` passes on the integration package with zero errors |
| NFR-M-3 | Every public method has a docstring describing inputs, outputs, and raised exceptions |
| NFR-M-4 | Every protocol-adjacent constant cites its source (traffic capture date, APK path, or spec §) in a comment |
| NFR-M-5 | Wire-format knowledge is isolated to `adapter.py`. No entity file imports `karcher` or accesses `DeviceProperties` raw fields; derivation happens in the coordinator. |

### 2.5 Security

See `05-security-threat-model.md`. Headline requirements:

| ID | Requirement |
|---|---|
| SEC-1 | Credentials stored only in HA's encrypted config-entry store |
| SEC-2 | No log line above `DEBUG` contains credentials, tokens, device SN, or MQTT payloads |
| SEC-3 | No `_`-prefixed member of a third-party package is accessed **outside `adapter.py`**. Inside the adapter, each such access carries an inline `# private-api:` justification. |
| SEC-4 | MQTT broker TLS is validated against a pinned CA (managed by `karcher-home`); `tls_insecure_set(True)` is forbidden in any code path |
| SEC-5 | All input surfaced by the adapter (JSON payloads, REST responses, MQTT messages) is validated against the adapter's DTO types before crossing the layer boundary; parsing failures are logged and discarded, not raised to HA |
| SEC-6 | Dependency versions are pinned with an upper bound; `dependabot` is configured; SBOM is generated on release |

### 2.6 Operability

| ID | Requirement |
|---|---|
| OPS-1 | Setup-to-functional time ≤ 60 s under nominal conditions |
| OPS-2 | Logging at `DEBUG` is sufficient to reproduce any command failure |
| OPS-3 | Diagnostics download (FR-D-1) is sufficient for a maintainer to triage a bug without interactive access to the user's HA instance |
| OPS-4 | Reauth completes in a single dialog without device re-selection |
| OPS-5 | Integration appears in HA's `About` panel with correct version, manifest, and HACS badge |

## 3. Removed and deferred requirements

| Previous requirement | Status | Reason |
|---|---|---|
| In-tree cloud client (`cloud/` subpackage) | **Removed** | ADR-0001 reversed; `karcher-home` is wrapped instead |
| SEC-3 as "no private-API access anywhere" | **Scoped** | Allowed inside `adapter.py`; forbidden elsewhere |
| Traceability as a CI gate | **Removed** | Convention only; see `adr/0004` |
| `quality_scale: silver` declared pre-diagnostics | **Removed** | Silver declared only on the release that ships FR-D-1; see `09-roadmap-and-backlog.md` |
| Map image entity | **Deferred to Phase 5** | Non-blocking |
| OTA interception | **Out of scope** | Not a goal |
