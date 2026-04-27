# 11 — Agent brief (Phase 0 kickoff)

This document is self-contained input for a coding agent or an engineer
starting the rewrite from scratch. It presumes no prior context. Every
claim is traceable to a file in this directory.

## 1. What you are building

A Home Assistant custom integration called `karcher_home_robots` that
controls the Kärcher RCV5 robot vacuum via the 3iRobotix cloud. The
device has no local API, no open ports, encrypted firmware, and a pinned
MQTT broker certificate — cloud control is the only option. Details in
`01-vision-and-scope.md`.

The deliverable is a green-field implementation that replaces an
existing ad-hoc integration. The rewrite keeps the `karcher-home`
library as its cloud-client dependency and wraps it behind a single
`adapter.py` module (see `adr/0001-library-adapter.md`). The existing
code is reference material; do not port it directly. The `doc/`
directory is authoritative on wire-protocol facts.

## 2. What you must read first (in order)

1. `01-vision-and-scope.md` — goals and MVP boundary.
2. `02-requirements.md` — complete SRS with stable IDs. Namespaces:
   `FR-A` (Account), `FR-RG` (Region), `FR-MG` (Migration),
   `FR-OF` (Offline), `FR-UP` (Updates), `FR-V` (Vacuum),
   `FR-SE` (Sensor), `FR-BS` (Binary sensor), `FR-SL` (Select),
   `FR-AH` (Apple Home), `FR-D` (Diagnostics); `NFR-*`, `SEC-*`, `OPS-*`.
3. `03-constraints-and-deltas.md` — hard/soft constraints and what the
   rewrite relaxes, plus what it does not relax (adapter-scoped
   concessions).
4. `04-architecture.md` — package layout, three-layer boundary
   (entities → coordinator → adapter), state model, concurrency model,
   region routing.
5. `05-security-threat-model.md` — STRIDE, secrets policy, reauth
   policy, CA-rotation graceful degradation (NFR-R-6).
6. `06-test-strategy.md` — pyramid, fixtures, CI gates.
7. `07-coding-standards.md` — language, async/threading, logging,
   errors, dependency discipline.
8. `08-definition-of-done.md` — PR/phase/release gates.
9. `09-roadmap-and-backlog.md` — phased plan; **start from Phase 0**.
10. `10-gap-carryover.md` — resolved vs deferred vs persistent gaps.
11. `adr/0001` through `adr/0004` — the four ADRs governing the
    rewrite (library-adapter, boundary-not-hexagonal, error-taxonomy,
    testing-strategy).

Read `doc/PROTOCOL.md` when you reach Phase 1; skim it now for the
shape of the wire protocol.

## 3. Operating rules

- **Treat user statements as hypotheses.** The spec may diverge from
  observed behaviour; verify against recorded captures or HIL before
  acting.
- **British English; metric units; technical prose; no filler.**
- **Never commit or push without explicit instruction.** Trunk-based,
  short branches, `main` always green.
- **Private-API access to `karcher-home` is permitted only inside
  `adapter.py`.** SEC-3 is enforced by `tests/tools/check_imports.py`.
  Outside the adapter, the prohibition is hard.
- **No blocking I/O outside `adapter.py`.** `run_in_executor` /
  `hass.async_add_executor_job` is permitted only in the adapter (see
  `07-coding-standards.md` §2).
- **paho-mqtt callbacks deliver on a foreign thread.** Re-entry into
  the event loop goes through `loop.call_soon_threadsafe(...)`. This
  is the adapter's job; no other layer knows paho exists.
- **Tests are a convention-driven discipline.** Test docstrings
  **should** cite `Covers: FR-X-N`; `docs-check` warns on orphan IDs at
  review time. It is not a CI gate (see `adr/0004-testing-strategy.md`).

## 4. Phase 0 concrete starting steps

3. Delete the current `custom_components/karcher_home_robots/` contents
   and replace with the layout from `04-architecture.md` §2, stubbed:
   - `__init__.py`: `async_setup_entry` / `async_unload_entry` return
     `True`.
   - `manifest.json`: `version = "2.0.0-alpha.1"`,
     `quality_scale = "bronze"`, `iot_class = "cloud_push"`,
     `requirements` lists `karcher-home` with an upper bound,
     `config_flow = true`.
   - `config_flow.py`: minimal `ConfigFlow` with a placeholder
     `async_step_user` that returns
     `self.async_abort(reason="not_implemented")`.
   - `adapter.py`: type stubs — methods declared, bodies
     `raise NotImplementedError`. Responsibilities documented in the
     module docstring per `adr/0001`.
   - Empty module files for all other modules listed in §2 of the
     architecture doc, each with a docstring describing its
     responsibility.
4. Write `pyproject.toml`, `.ruff.toml` (or `[tool.ruff]` in
   `pyproject.toml`), `mypy.ini` (or `[tool.mypy]`), `pytest.ini` (with
   `asyncio_mode = auto`).
5. Commit CI workflow in `.github/workflows/ci.yml` running:
   `ruff check`, `ruff format --check`, `mypy --strict`, `pytest`,
   coverage, `check_imports`, `check_docs --strict`, `pip-audit
   --strict`, HACS validation, `hassfest`. Matrix over the two pinned
   HA versions in `.github/workflows/ci.yml`.
6. Commit pre-commit config scanning for `sc2021`, `hj2WtyHYYEvBTxDb`,
   and token-shaped strings.
7. Leave ADRs in `adr/` at the repo root (the 4-ADR set lives
   there). Pre-rewrite decision records were removed when `spec/`
   and `adr/` consolidated; the four ADRs are the only authoritative
   set.
8. Commit skeleton `tests/` with `conftest.py` and a trivial unit test
   asserting `custom_components.karcher_home_robots` is importable.
9. Run the full CI locally. It should pass.
10. Open a PR titled `phase 0: scaffold`; the PR description includes
    the Phase-0 DoD checklist from `08-definition-of-done.md`.

## 5. Phase 1 concrete starting steps (after Phase 0 merges)

Work inside-out of the layer diagram: start with the pure code, build
up to the entities. Suggested order:

1. `exceptions.py` — `ClientError` hierarchy per
   `adr/0003-error-taxonomy.md`.
2. `_types.py` — integration-owned frozen `DeviceProperties` dataclass.
3. `adapter.py` — async wrapper around `karcher-home`:
   - `run_in_executor` for blocking calls;
   - `loop.call_soon_threadsafe` bridge for paho-mqtt callbacks;
   - exception translation from `karcher-home` native exceptions to
     `ClientError` subclasses (including `RateLimited`);
   - contained work-arounds for the two upstream bugs (`net_stauts`
     typo and stale `get_device_properties` / unparsed
     `property/post`).
4. `coordinator.py`:
   - `async_setup` sequence; push/poll reconciliation (FR-UP-5);
   - `derive_vacuum_state()` — pure function, 100 % coverage target;
   - offline semantics (FR-OF-1..5).
5. `config_flow.py`, `__init__.py`, `entity.py`, `vacuum.py`,
   `sensor.py` (battery only in MVP), `binary_sensor.py`.
6. Integration tests committed; HIL test set committed under
   `tests/hardware/` (opt-in, `KARCHER_HIL=1`). HIL is run by the
   maintainer at the release tag, not as a phase-exit gate
   (`spec/08-definition-of-done.md` §2 item 4).

## 6. Definitions of "done" for the first PR

The first PR (`phase 0: scaffold`) is done when:

- The PR template checklist is complete.
- CI is green.
- `git grep -nE 'tls_insecure_set' custom_components/` returns
  nothing.
- `git grep -nE 'run_in_executor' custom_components/` outside
  `adapter.py` returns nothing.
- `python tests/tools/check_imports.py` reports no violations.
- A reviewer (see `08-definition-of-done.md` §1.10) has approved.

## 7. What to surface to the user, always

- Protocol changes observed during implementation. Update
  `doc/PROTOCOL.md` and flag in the PR description.
- Anything that requires a new ADR before it can land.
- Any CI gate that produces noise. Gates must be precise; a gate that
  gets ignored loses its value and must be fixed, not dropped.
- Any upstream `karcher-home` release that looks like it removes the
  need for one of the adapter's workarounds — trigger cross-cutting
  backlog item X-4.

## 8. What to avoid

- Polishing speculative features. If it isn't in `02-requirements.md`,
  don't build it.
- Large refactors mid-phase. Land the phase, then refactor in a
  dedicated PR.
- Large PRs. Anything not reviewable in 30 min should be split.
- "Fixing" the existing `custom_components/karcher_home_robots/` —
  the scaffolded new package starts empty.
- New runtime dependencies without an ADR or an upper bound.
- Calling `karcher-home` or paho-mqtt from anywhere other than
  `adapter.py`. The `check_imports.py` layer test exists to catch
  this; do not waive it.
