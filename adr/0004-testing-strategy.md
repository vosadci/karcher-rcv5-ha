# ADR-0004: Testing pyramid

Status: Accepted
Date: 2026-04-24

## Context

The prior integration had tests per entity type (good) and a single
`conftest.py` with patched library boundaries (workable but brittle).
Coverage was uneven: state derivation had table tests, but several
behaviours documented in `doc/GAP_ANALYSIS.md` §4 were untested. The
rewrite needs a deliberately shaped test strategy that is both fast
for day-to-day use and comprehensive enough to catch protocol drift
coming in from `karcher-home` releases.

## Decision

Three fast layers plus one opt-in hardware layer. Detail in
`../06-test-strategy.md`.

- **Unit.** Pure functions and data classes; no HA; no I/O; deterministic.
  Heavy investment in `coordinator.derive_vacuum_state`, the adapter's
  `karcher-home`-exception mapper, and any in-tree parsing. Adapter
  unit tests mock the `karcher` surface; they do not mock
  paho-mqtt internals.
- **Contract.** The adapter against a fake broker and a fake REST
  server. Targets protocol-level behaviour as the adapter sees it:
  subscribe, push decode, command encode, reconnect backoff, timeout
  handling, rate-limit backoff, region routing selection.
- **Integration.** HA-loop tests via `pytest-homeassistant-custom-component`.
  Targets HA-visible behaviour: entity states, config flow, reauth,
  diagnostics, unique_id migration, offline semantics.
- **HIL (hardware-in-the-loop).** Opt-in; not blocking CI; expected
  before a release tag. Captured logs are sanitised and fed back as
  contract-test fixtures.

Coverage gates (CI): lines ≥ 85 %, branches ≥ 80 %. The adapter and
the coordinator state-derivation path are held at 100 %. Numbers are
deliberately lower than the previous draft; the goal is signal on
regressions, not a coverage-theatre gate.

Traceability to requirement IDs is a **convention, not a gate.**
Test docstrings should cite `Covers: FR-X-N` where obvious, and
`/docs-check` will spot orphan IDs at docs-review time — but CI does
not fail on missing citations. Requiring a `Covers:` line on every
test wastes review cycles on trivial cases and incentivises cargo-cult
annotations.

## Consequences

- Unit tests dominate the suite and run in < 5 s; daily iteration is
  cheap.
- Contract tests exercise everything that used to require HA, without
  HA overhead.
- HIL catches protocol drift on release candidates with manageable
  toil.
- Fixtures are centralised under `tests/fixtures/`; recorded captures
  are sanitised once and reused forever.
- No `check_traceability.py` in CI. The tool does not exist in this
  repository.

## History

Previously numbered 0010 in an early draft; renumbered when the ADR
set was trimmed to four. Traceability-as-gate was removed in the same
pass.
