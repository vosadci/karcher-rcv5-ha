# CLAUDE.md

`karcher_home_robots` — HA custom integration for the Kärcher RCV5 robot vacuum.

Read `ARCHITECTURE.md` before touching code. `doc/PROTOCOL.md` is authoritative on the wire format.

## Hard constraints

- **`adapter.py` is the only importer of `karcher`.** No other module touches the library. Enforced by `tests/tools/check_imports.py`.
- **Private-API access to `karcher-home` only inside `adapter.py`.** Each call site carries `# private-api: <reason>`. The allowlist is in `check_imports.py`; `ARCHITECTURE.md` documents it.
- **No `tls_insecure_set(True)`.** CA-rotation surfaces a `repair` issue, not silent insecure fallback.
- **`run_in_executor` / `hass.async_add_executor_job` only inside `adapter.py`.** Everything above is async end-to-end.
- **paho-mqtt callbacks re-enter the loop only via `loop.call_soon_threadsafe`.** The adapter owns this bridge; no other layer knows paho exists.
- **No `homeassistant.*` imports in `adapter.py` at runtime.** `TYPE_CHECKING` annotations only.
- **No credential, token, SN, or MQTT payload above DEBUG log level.**
- **No `quality_scale` beyond what's implemented.** Current value is in `manifest.json`.

## Development commands

```bash
make install      # pip install -e .[test,dev]
make test         # pytest tests/ -v
make test-cov     # pytest with coverage
make lint         # ruff check + ruff format --check  ⚠ broken — use direct invocation below
make type         # mypy --strict custom_components/karcher_home_robots  ⚠ broken — use direct invocation below
make import-graph # check_imports.py — boundary enforcement
make check        # lint + type + test-cov + coverage-gate + import-graph
make precommit    # run all pre-commit hooks
```

Single test: `python -m pytest tests/unit/test_state_derivation.py::test_idle -v`

`asyncio_mode = auto` in `pytest.ini` — no `@pytest.mark.asyncio` needed.

`mypy --strict` is a blocking CI gate.

## Repository layout

```
custom_components/karcher_home_robots/   — integration package
  adapter.py         — only importer of karcher
  coordinator.py     — state ownership, push/poll, derive_vacuum_state
  entity.py          — shared base
  vacuum.py, sensor.py, binary_sensor.py, select.py, config_flow.py
  exceptions.py      — ClientError hierarchy
  _types.py          — integration-owned DTOs
  const.py           — HA-facing constants only
  diagnostics.py     — redacted diagnostics dump (Phase 4)
  image.py           — KarcherMapImage entity (ImageEntity), live floor plan PNG
  map_data.py        — DTOs: MapSnapshot, MapGrid, Pose, RoomInfo, RoomChain
  map_parser.py      — pure parser: Map.data protobuf dict → MapSnapshot
  map_render.py      — numpy + Pillow renderer; pure, runs in executor

tests/
  tools/check_imports.py   — import-boundary enforcement (keep this)
  tools/coverage_gate.py   — phase-graduated coverage gate (keep this)
  unit/, contract/, integration/, hardware/, fixtures/

doc/               — protocol reverse-engineering reference
ARCHITECTURE.md    — module map, layer rules, error taxonomy, workarounds
CHANGELOG.md       — version history (shown in HACS)
```

## Collaboration rules

- **Never commit or push automatically.** Wait for explicit instruction.
- After any change to the integration package, remind the user to deploy to their HA instance (`scp` + restart) if that's how they iterate. Do not `scp` or restart automatically.
- After significant protocol discoveries, update `doc/PROTOCOL.md` with exact commands, topics, payloads, and capture date.

## Secrets and sensitive paths — never commit

| Item | Location |
|---|---|
| MQTT test certs | `../karcher-mqtt-certs/` |
| Kärcher APK | `~/Downloads/KHR_*.apk` |
| jadx output | `/tmp/apk_jadx/` |
| Research passwords | In `doc/PROTOCOL.md` as findings only — do not repeat here |

Pre-commit secret scan blocks the research passwords. The 3iRobotix CA cert and `iot_dev.p12` are bundled inside `karcher-home`, not here.

## Agents

None — specialist review is handled by `/review` (a skill, not an agent).

## Skills

| Skill | Invocation | Purpose |
|---|---|---|
| `/review`     | Manual | Change review: layering, HA patterns, security posture |
| `/docs-check` | Manual | Documentation freshness and consistency check          |
