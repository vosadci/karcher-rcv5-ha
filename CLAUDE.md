# CLAUDE.md — project guidance

This file is the entry point for any Claude-driven work inside this
project. It overrides default Claude behaviour and MUST be followed
exactly.

## What this repository is

The `karcher_home_robots` Home Assistant custom integration for the
Kärcher RCV5 robot vacuum. Three-layer boundary discipline (entities →
coordinator → adapter), a thin adapter around the `karcher-home`
library, fully typed (`mypy --strict`), tested, and targeting HACS
Silver after Phase 4. The package is a clean-room replacement of an
earlier ad-hoc implementation.

Read the spec set before touching any code:

1. `spec/README.md` — reading order and glossary.
2. `spec/01-vision-and-scope.md` through `spec/11-agent-brief.md` —
   the SRS, architecture, test strategy, DoD, roadmap.
3. `adr/` — the four decision records (0001..0004).

`README.md` is the user/marketing-facing README rendered on GitHub and
in HACS; it is not the spec index.

## Hard constraints — do not work around these

- **`karcher-home` is the cloud client.** It is wrapped behind
  `adapter.py`; no other module imports `karcher`. Rewriting the
  wire protocol in-tree is out of scope. (ADR-0001)
- **Private-API access to `karcher-home` is permitted only inside
  `adapter.py`.** Enforced by `tests/tools/check_imports.py`. (SEC-3)
- **No `tls_insecure_set(True)`.** `karcher-home` pins to the
  bundled 3iRobotix CA; broker-CA rotation surfaces a `repair` issue,
  not silent insecure fallback. (SEC-4, NFR-R-6)
- **`run_in_executor` / `hass.async_add_executor_job` is permitted
  only inside `adapter.py`.** The rest of the integration is async
  end-to-end. (`07-coding-standards.md` §2)
- **paho-mqtt callbacks deliver on a foreign thread.** Re-entry into
  the event loop goes through `loop.call_soon_threadsafe(...)`; the
  adapter owns this bridge. No other layer knows paho exists.
- **No HA imports inside `adapter.py` at runtime.** `TYPE_CHECKING`
  annotations only. (§3 of `spec/04-architecture.md`, ADR-0002)
- **No credential, token, SN, or MQTT payload above DEBUG log level.**
  (SEC-2)
- **No `quality_scale` claim beyond what's implemented.** Ships
  `bronze` until diagnostics (FR-D-1) and migration (FR-MG-1..5) land
  in Phase 4. (`spec/09-roadmap-and-backlog.md` Phase 4 commentary)

## Development commands

```bash
make install      # pip install -e .[test,dev]
make test         # pytest tests/ -v
make test-cov     # pytest with coverage; fails below thresholds
make lint         # ruff check + ruff format --check
make type         # mypy --strict custom_components/karcher_home_robots
make check        # lint + type + test-cov + import-graph + docs
make docs         # check_docs.py --strict: links, ADR chain, versions
make precommit    # run all pre-commit hooks
```

Single test:

```bash
python -m pytest tests/unit/test_state_derivation.py::test_idle -v
```

**Python interpreter:** use `python3` from the project venv. Locally
the user has `/opt/anaconda3/bin/python3` with assorted dev libs —
prefer the venv over that when possible.

**`asyncio_mode = auto`** is set in `pytest.ini`; async tests do not
need the `@pytest.mark.asyncio` decorator.

**`mypy --strict`** is a blocking CI gate. There is no "typecheck is
optional" mode.

## Repository layout

```
<repo-root>/
  README.md                           — user-facing (HACS, GitHub)
  CHANGELOG.md, CONTRIBUTING.md, LICENSE, CLAUDE.md
  Makefile, pyproject.toml, .pre-commit-config.yaml, .gitignore,
    .editorconfig, hacs.json

  spec/                               — the spec set
    README.md                         — reading order and glossary
    01-vision-and-scope.md ... 11-agent-brief.md
  adr/                                — four decision records (0001..0004)
  doc/                                — reverse-engineering reference
                                        (PROTOCOL, INVESTIGATION, ROOTING, …)
  .claude/                            — skills, settings.json
  .github/                            — CI, release workflow, PR template,
                                        issue templates, SECURITY.md,
                                        CODEOWNERS, dependabot

  custom_components/karcher_home_robots/   — scaffolded in Phase 0
    __init__.py, manifest.json, const.py, config_flow.py, coordinator.py,
    entity.py, vacuum.py, sensor.py, binary_sensor.py, select.py,
    diagnostics.py, strings.json, translations/, py.typed
    adapter.py                        — the only importer of karcher
    exceptions.py                     — ClientError hierarchy (ADR-0003)
    _types.py                         — integration-owned DTOs

  tests/
    conftest.py
    tools/check_imports.py, tools/check_docs.py
    unit/, contract/, integration/, hardware/, fixtures/
```

## Source of truth

- **Requirements** → `spec/02-requirements.md`. Namespaces: `FR-A`
  (Account), `FR-RG` (Region), `FR-MG` (Migration), `FR-OF` (Offline),
  `FR-UP` (Updates), `FR-V` (Vacuum), `FR-SE` (Sensor), `FR-BS`
  (Binary sensor), `FR-SL` (Select), `FR-AH` (Apple Home), `FR-D`
  (Diagnostics); `NFR-*`, `SEC-*`, `OPS-*`. Test docstrings should
  cite `Covers: FR-X-N`; `docs-check` warns on orphans at review time.
  It is not a CI gate (ADR-0004).
- **Protocol** → `doc/PROTOCOL.md`. Authoritative on the wire.
  Update it when you discover anything new; include capture date and
  tool invocation.
- **Architecture** → `spec/04-architecture.md` + `adr/0002`. Changes
  that alter module boundaries or the import graph require a new ADR.
- **Decisions** → `adr/`. The active set is four (`0001`..`0004`).

## Skills (slash commands)

| Skill | Invocation | Purpose |
|---|---|---|
| `/review` | Manual | Combined change review: layering, HA patterns, SOLID, security posture, simplification |
| `/docs-check` | Manual | Docs freshness: links, ADR chain, requirement ID references, version drift |

No other Claude agents or skills are configured in-tree. Previous
reviewer agents (`solid-reviewer`, `security-reviewer`,
`design-reviewer`, `ha-reviewer`, `pr-reviewer`) and skills
(`security-review`, `simplify`, `solid-check`) were removed as
ceremony; their checklists folded into `/review`.

## Collaboration rules

- **Never commit or push automatically.** Wait for explicit
  instruction.
- Commits are per logical phase, not per file. Present-tense
  imperative messages.
- No force-pushes to `main`; no destructive git ops without
  instruction.
- After any change to the HA integration package, remind the user to
  test locally or deploy to their HA instance (`scp` + restart HA) if
  that is how they iterate. Do not `scp` or restart automatically.
- After significant protocol discoveries, update `doc/PROTOCOL.md`
  with exact commands, topics and payloads, and the capture date.

## Secrets and sensitive paths

Mirrors `doc/INVESTIGATION.md` — do not commit these under any
circumstance. The pre-commit hook blocks them.

| Item | Location | Committed? |
|---|---|---|
| MQTT test certs | `../karcher-mqtt-certs/` | No (.gitignore) |
| Kärcher APK | `~/Downloads/KHR_*.apk` | No |
| jadx output | `/tmp/apk_jadx/` | No |
| APK research passwords `sc2021`, `hj2WtyHYYEvBTxDb` | Documented in `doc/PROTOCOL.md` as research findings; never in integration source |

The 3iRobotix CA cert and the `iot_dev.p12` mutual-TLS cert are
bundled inside `karcher-home`, not in this repository.

## Phase awareness

The current phase is named in `CHANGELOG.md` under `## [Unreleased]`
and in the active milestone on the issue tracker. Claude should:

- Reject work outside the current phase's backlog unless explicitly
  told to spike ahead.
- Cite the backlog item ID (`P1-7` etc. from
  `spec/09-roadmap-and-backlog.md`) in branch names and PR titles.
- Refuse to merge without the phase DoD passing
  (`spec/08-definition-of-done.md`).
