# Tech Debt Audit — karcher-rcv5-ha
Generated: 2026-05-02 | Branch: main | Phase: 4 (Silver)

---

## Architectural mental model

A three-layer HA custom integration: **Entities** (vacuum, sensors, selects, binary sensor) read state from a **Coordinator** (`DataUpdateCoordinator`) which owns push/poll reconciliation and error-taxonomy logic. The Coordinator holds a **Adapter** (`KarcherAdapter`) that is the only module importing `karcher-home`, the sole cloud client. The adapter bridges paho-mqtt's foreign-thread callbacks into the asyncio event loop via `call_soon_threadsafe`, works around several upstream library bugs, and translates all library exceptions into an integration-owned `ClientError` hierarchy.

The architecture is sound and the layering is rigorously enforced by a CI import-graph check. Debt is concentrated in a handful of specific spots rather than spread systemically. This is a well-structured ~1,200-line integration with 97%+ coverage.

---

## Executive summary

1. ~~**`asyncio.get_event_loop()` is deprecated in 3.10+** — used in `adapter.py:250` inside a running coroutine; should be `asyncio.get_running_loop()`.~~ **FIXED**
2. **`_fetch_properties_sync` leaks a `threading.Event` into `_wait_events` when `mqtt.publish` raises** — the event is never cleaned up on that path.
3. **Eight `assert self._client is not None` guards in `adapter.py`** — asserts are stripped in optimised builds (`python -O`). These should be explicit `RuntimeError` raises.
4. **`silent_reauth` buries three policy constants inside the function body** — `_REAUTH_WINDOW`, `_MAX_ATTEMPTS`, `_BACKOFF` are redeclared on every call.
5. **Five exception classes in `exceptions.py` are never raised by production code** — `AccessDenied`, `DeviceNotFound`, `InvalidRegion`, `TimeoutError`, `ProtocolError` (the last one is caught but never raised by the adapter).
6. **`sn`, `product_id`, `nickname` stored redundantly in config entry data** — only `device_id` is used by `async_setup_entry`; the rest are dead weight that need migration-safe handling to remove.
7. **`ALL_ROOMS_LABEL = "All rooms"` is a hardcoded English string** — exposed as `current_option` to HA UI and not going through `strings.json` translation.
8. **Room select matches by name, not ID** — two rooms with the same name silently break selection.
9. **`_to_kdevice()` reconstructs upstream `Device` with 8 hardcoded sentinel fields** — any upstream constructor change silently produces wrong data.
10. **`aiohttp >=3.9,<4` pins too loosely** — the installed version (3.13.3) has 10 open CVEs against the HA test environment; the project pins as a dependency but does not control what HA installs.

---

## Findings

| ID | Category | File:Line | Severity | Effort | Description | Recommendation |
|----|----------|-----------|----------|--------|-------------|----------------|
| F001 | Type/contract | [adapter.py:250](custom_components/karcher_home_robots/adapter.py#L250) | High | S | **FIXED** ~~`asyncio.get_event_loop().time()` inside a running coroutine. Deprecated in Python 3.10+; emits DeprecationWarning in 3.12+.~~ Replaced with `asyncio.get_running_loop().time()`. | Resolved. |
| F002 | Error handling | [adapter.py:563](custom_components/karcher_home_robots/adapter.py#L563) | High | S | **FIXED** ~~`_fetch_properties_sync`: if `mqtt.publish` raises (line 563), the event registered on line 547 stays in `wait_events` forever. Also: timeout was not detected — `event.wait()` return value ignored, stale data returned silently.~~ Publish + wait wrapped in `try/finally`; timeout now raises `TransientError`. | Resolved in commit alongside audit. |
| F003 | Error handling | [adapter.py:204,224,292,317,352,437,459,486](custom_components/karcher_home_robots/adapter.py#L204) | High | S | `assert self._client is not None` used as a guard 8 times. Asserts are silently dropped with `python -O`. HA's production runner may not use `-O`, but this is a latent correctness hazard. | Replace with `if self._client is None: raise RuntimeError("async_setup() not called")` — or extract a `_require_client()` helper |
| F004 | Consistency | [adapter.py:246–248](custom_components/karcher_home_robots/adapter.py#L246) | Medium | S | `_REAUTH_WINDOW`, `_MAX_ATTEMPTS`, `_BACKOFF` are local constants inside `silent_reauth()` and are re-created on every call. They encode policy that tests need to reason about. | Hoist to module-level constants (`_SILENT_REAUTH_WINDOW = 300.0` etc.) |
| F005 | Dead code | [exceptions.py:27,55,59,39](custom_components/karcher_home_robots/exceptions.py#L27) | Medium | S | `AccessDenied`, `DeviceNotFound`, `InvalidRegion`, `TimeoutError` are defined but never raised by production code. `ProtocolError` is caught in the coordinator but no code path in the adapter raises it. | Either raise them from the appropriate paths or remove them from the hierarchy and the import lists |
| F006 | Architectural decay | [config_flow.py:216–218](custom_components/karcher_home_robots/config_flow.py#L216) | Medium | M | `sn`, `product_id`, `nickname` are stored in config entry data at creation but `async_setup_entry` only uses `device_id`. They are never read back. They add migration surface (and `sn` is a sensitive serial that happens to be redacted by diagnostics only because the regex catches it). | Remove from new entries; mark as dead in migration notes. They survive in v1 entries through migration, so require a v3 migration if removed now. Open question: intended for future use? |
| F007 | Consistency | [select.py:50](custom_components/karcher_home_robots/select.py#L50) | Medium | M | `ALL_ROOMS_LABEL = "All rooms"` is a hardcoded English string exposed as `current_option` and as one of the `options` list values. The select entity translations cover the cleaning-mode and water-level states via `strings.json`, but the "All rooms" sentinel is never translated. | Add `"all_rooms"` to `strings.json` `entity.select.room.state` and use a translation key + HA's `translate()` helper; or define it as a special sentinel HA knows to translate |
| F008 | Error handling | [select.py:111–113](custom_components/karcher_home_robots/select.py#L111) | Medium | S | `async_select_option` matches the selected room by `room.name == option`. If two rooms have identical names (valid on some maps), the first match wins silently. | Match by ID: `options` should be `f"{r.room_id}:{r.name}"` and the lookup should decode the ID prefix; or store a `{name: room_id}` map that warns on duplicate names |
| F009 | Architectural decay | [adapter.py:579–597](custom_components/karcher_home_robots/adapter.py#L579) | Medium | M | `_to_kdevice()` reconstructs an upstream `_KDevice` with 8 hardcoded sentinel fields (`isDefault=False`, `onlineTime=0`, `versions="[]"`, etc.). Any change to the upstream constructor signature breaks this silently at runtime rather than at import time. | Add a version-pinned test that imports `_KDevice` and checks it accepts these fields, or vendor a minimal dataclass that wraps the call |
| F010 | Dependency | [pyproject.toml:38–40](pyproject.toml#L38) | Medium | M | `aiohttp>=3.9,<4` is pinned by the project but controlled by HA at runtime. 10 CVEs are open against 3.13.3 (the installed version in CI), all patched in 3.13.4. The project cannot force the HA install version, but the lower bound is far too loose (3.9 is years behind). | Tighten lower bound to `>=3.13.4` to at least fail loudly on installs that would be vulnerable. Add a note in CLAUDE.md that aiohttp CVEs are HA-owned |
| F011 | Error handling | [coordinator.py:213](custom_components/karcher_home_robots/coordinator.py#L213) | Low | S | Initial room fetch in `async_setup` catches bare `Exception` and logs a warning. This is intentional (rooms are non-fatal), but a `ClientError` vs unexpected exception distinction would be cleaner. | Change to `except ClientError as exc` for the expected path; let unexpected exceptions propagate to surface bugs |
| F012 | Consistency | [coordinator.py:22](custom_components/karcher_home_robots/coordinator.py#L22) | Low | S | `import time` (wall-clock) is used for outage tracking (`time.monotonic()`) alongside `self.hass.loop.time()` (monotonic event-loop clock) for update ordering. Two monotonic clocks serve different purposes but the distinction is easy to miss. | Add inline comments clarifying why `time.monotonic()` is used for outage duration (survives event-loop suspension) vs `hass.loop.time()` for update ordering |
| F013 | Type/contract | [vacuum.py:85](custom_components/karcher_home_robots/vacuum.py#L85) | Low | S | `coordinator._device` is accessed directly from `KarcherVacuum.__init__` (and from every other entity `__init__`). This is a private attribute of `KarcherCoordinator`. `entity.py` also accesses it in `device_info`. | Expose `coordinator.device` as a public property |
| F014 | Documentation | [adapter.py:323](custom_components/karcher_home_robots/adapter.py#L323) | Low | S | `get_rooms` catches bare `except Exception` on the map-data call and returns `[]`, logging at DEBUG. This is intentional (no map = empty rooms), but the comment just says "no map?" — it should also mention that `KarcherHomeException` is caught above and this branch is for unexpected errors (e.g., protobuf decode failures). | Improve inline comment to distinguish the two paths |
| F015 | Test debt | [tests/contract/](tests/contract/) | Medium | L | 8 of 11 contract test files named in `spec/06-test-strategy.md` do not exist. This is the primary test-debt finding from the separate testing-strategy audit. The audit is on record; listed here for completeness and prioritisation. | Implement per the testing strategy plan |
| F016 | Dependency | [manifest.json:7](custom_components/karcher_home_robots/manifest.json#L7) | Low | S | `karcher-home==0.5.1` is exact-pinned in `manifest.json` (correct for HA), but `pyproject.toml` does not add an upper bound for the test harness — the editable install will use whatever is in the venv. | Already exact-pinned; no action needed. (Flagged as considered, not a finding.) |
| F017 | Security | [adapter.py:206–207](custom_components/karcher_home_robots/adapter.py#L206) | Low | S | `get_endpoint_snapshot()` reads private attributes `_base_url` and `_mqtt_url` directly. These are in the allowlist and logged at DEBUG, but the MQTT URL could contain credentials in some broker configurations. | Confirm broker URL scheme never includes credentials (see PROTOCOL.md); add to allowlist documentation if so |

---

## Top 5 — fix these first

### 1. F001 — `get_event_loop()` → `get_running_loop()` (adapter.py:250) — **FIXED**

```diff
-        now = asyncio.get_event_loop().time()
+        now = asyncio.get_running_loop().time()
```

---

### 2. F002 — `_fetch_properties_sync` event leak + silent timeout (adapter.py:563) — **FIXED**

Two bugs fixed together:

1. **Event leak**: if `mqtt.publish` raised, the reply event was left in `_wait_events`. Fixed with `try/finally`.
2. **Silent timeout (Q4)**: `event.wait(timeout)` returns `False` on timeout; the return value was ignored, so stale cached data was returned silently instead of raising `TransientError`. Fixed by checking the return value.

Applied diff:

```diff
-    mqtt.publish(publish_topic, payload)
-    event.wait(timeout)
-    wait_events.pop(reply_topic, None)
+    try:
+        mqtt.publish(publish_topic, payload)
+        replied = event.wait(timeout)
+    finally:
+        wait_events.pop(reply_topic, None)
+
+    if not replied:
+        raise TransientError(
+            f"prop.get reply not received within {timeout:.0f}s for {sn}"
+        )
```

Two new contract tests added: `test_fetch_properties_timeout_raises_transient_error` and `test_fetch_properties_publish_error_cleans_up_event`.

---

### 3. F003 — Replace `assert` guards with explicit `RuntimeError` (adapter.py, 8 sites)

Extract a helper to avoid repetition:

```python
def _require_client(self) -> KarcherHomeProtocol:
    if self._client is None:
        raise RuntimeError("KarcherAdapter.async_setup() was not called")
    return self._client
```

Replace all 8 `assert self._client is not None` + subsequent `self._client` access sites with `client = self._require_client()`.

---

### 4. F004 — Hoist `silent_reauth` constants to module level (adapter.py:246–248)

```diff
+_SILENT_REAUTH_WINDOW = 300.0   # seconds — 5-minute attempt window (FR-A-8a)
+_SILENT_REAUTH_MAX_ATTEMPTS = 3
+_SILENT_REAUTH_BACKOFF = (5.0, 30.0, 120.0)  # seconds

 async def silent_reauth(self) -> None:
-        _REAUTH_WINDOW = 300.0  # 5 minutes
-        _MAX_ATTEMPTS = 3
-        _BACKOFF = (5.0, 30.0, 120.0)
-
-        now = asyncio.get_event_loop().time()
-        if now - self._reauth_window_start > _REAUTH_WINDOW:
+        now = asyncio.get_running_loop().time()
+        if now - self._reauth_window_start > _SILENT_REAUTH_WINDOW:
```

Tests can now assert the policy by reading the module constant rather than reverse-engineering the behaviour.

---

### 5. F008 — Room select name-collision bug (select.py:111–113)

The current implementation matches by `room.name`. If two rooms are named "Bedroom", the second is permanently unselectable.

```diff
 @property
 def options(self) -> list[str]:
-    return [ALL_ROOMS_LABEL] + [r.name for r in self.coordinator.rooms]
+    return [ALL_ROOMS_LABEL] + [f"{r.room_id}:{r.name}" for r in self.coordinator.rooms]

 async def async_select_option(self, option: str) -> None:
     if option == ALL_ROOMS_LABEL:
         self.coordinator.set_selected_room_id(None)
         return
-    for room in self.coordinator.rooms:
-        if room.name == option:
-            self.coordinator.set_selected_room_id(room.room_id)
-            return
+    try:
+        room_id = int(option.split(":", 1)[0])
+    except (ValueError, IndexError):
+        _LOGGER.warning("Unparseable room option %r; ignoring", option)
+        return
+    for room in self.coordinator.rooms:
+        if room.room_id == room_id:
+            self.coordinator.set_selected_room_id(room.room_id)
+            return
     _LOGGER.warning("Room %r not found in room list; ignoring", option)
```

Note: this changes the string visible in the HA UI from "Kitchen" to "3:Kitchen". A cleaner approach is to keep the display name but track selection by ID internally — requires a `{name: room_id}` dict built at `options` time and stored as instance state. But that adds complexity; the prefix form is simple and robust.

---

## Quick wins

- [x] **F001** — `get_event_loop()` → `get_running_loop()` in `adapter.py:250` (1 line)
- [ ] **F004** — Hoist 3 constants out of `silent_reauth` to module level (5 lines)
- [ ] **F013** — Add `coordinator.device` public property to `KarcherCoordinator`; remove all `coordinator._device` access from entity files (8 sites)
- [ ] **F012** — Add 2-line clarifying comment distinguishing `time.monotonic()` vs `hass.loop.time()` in `coordinator.py`
- [ ] **F014** — Improve `get_rooms` exception comment to distinguish map-not-found vs unexpected error paths

---

## Things that look bad but are actually fine

**`except Exception` in adapter `close()` and `unsubscribe()` (adapter.py:188, 420).** These are teardown paths. Swallowing all exceptions on teardown is correct — you cannot usefully propagate from a destructor-equivalent, and a raising `close()` would cause the coordinator's `async_shutdown` to fail silently. The `_LOGGER.debug(exc_info=True)` ensures observability. Leave these alone.

**`except Exception` in `_migrate_v1_to_v2` caller (`__init__.py:134`).** Migration failure must not crash HA's config-entry machinery. The bare `except` here is intentional; the repair issue creation below it is the designed recovery path (FR-MG-5). The `_LOGGER.exception` call ensures the full traceback is preserved. Leave this alone.

**`cast(KarcherHomeProtocol, raw)` in `adapter.py:180`.** The `karcher-home` library ships no `py.typed` marker. Without stubs, mypy treats every import as `Any`. The Protocol + single `cast()` pattern is the least-bad way to get type safety without vendoring stubs that would drift silently. The `_types.py` comment already explains the intent and the escape hatch when upstream ships `py.typed`. Leave it.

**`coordinator._device` private access from `entity.py` and entities.** This looks like a layering violation, but `entity.py` is the base class in the same package. Python's name-mangling convention is `__attr` (double underscore); a single underscore is "internal by convention, not enforcement". The access is within the integration package, not from external code. It's mildly untidy but not structurally wrong. F013 proposes a public property anyway, which is the right direction.

**`_to_kdevice()` hardcoded sentinel values (F009 listed as Medium).** The upstream library uses `Device` for subscribe/unsubscribe only. The hardcoded fields (`isDefault`, `onlineTime`, etc.) are never read back by the adapter. The real risk is a constructor signature change breaking at runtime, not wrong data. This is mitigated by the exact pin `karcher-home==0.5.1` in `manifest.json`. The risk goes up only on a library upgrade — at which point the adapter already needs review per CLAUDE.md. Consider this Low in practice.

**`time.monotonic()` vs `hass.loop.time()` (F012 listed as Low).** Both are monotonic clocks. `time.monotonic()` is used for wall-clock outage duration (survives event-loop sleep, correct for `timedelta` comparisons). `hass.loop.time()` is used for update ordering (event-loop relative, correct for comparing push vs poll timestamps within the HA lifecycle). The two-clock design is intentional and correct; the only issue is that it's not explained inline.

**`ProtocolError` caught but never raised.** The coordinator catches `ProtocolError` at lines 303 and 322 as a soft-error (return cached data). Currently no adapter code raises it, so the branches are dead. But the exception class is part of the taxonomy for future protocol-level validation (e.g., if the adapter starts validating MQTT payload structure). It's not dead code in the sense of being unreachable — it's reserved. Listed as F005 because it creates confusion, not because it's harmful.

---

## Open questions for the maintainer

1. **`sn`, `product_id`, `nickname` in config entry data (F006)**: Are these stored for future use (e.g. offline display without re-authenticating)? If yes, document it. If no, plan a v3 migration to remove them and reduce the sensitive-data footprint.

2. **`ALL_ROOMS_LABEL` translation (F007)**: The HA UI will show "All rooms" to non-English users. Is this intentional (HA vacuum room names are generally English), or should it go through strings.json?

3. **`ProtocolError` raised by nothing (F005)**: Should the adapter validate MQTT payload structure and raise `ProtocolError` on schema violations, or is this class purely for future use? If the latter, add a comment; if it's truly vestigial, remove it.

4. ~~**`_fetch_properties_sync` timeout (F002 adjacent)**: If `event.wait(timeout)` times out, the function returns without raising. The caller (`fetch_properties`) then calls `_project_properties`, which may return stale data rather than raising `TransientError`. Is this intentional? The spec says a 5 s timeout should raise `TransientError` (spec/10-gap-carryover.md §3 GAP 3.5 "Resolved"), but the current code returns stale data silently on timeout. This deserves a dedicated test and possibly a fix.~~ **RESOLVED** — fixed in F002; `TransientError` now raised on timeout.

5. **aiohttp CVEs (F010)**: 10 CVEs against 3.13.3, all patched in 3.13.4. Is the project's HA environment pinned to an aiohttp version below 3.13.4? If so, this is inherited debt from the HA test harness and not actionable in this repo. If the maintainer controls the environment, bump the pin.
