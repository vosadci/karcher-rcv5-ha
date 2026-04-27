# Specification set

This directory is the structured specification for the
`karcher_home_robots` Home Assistant integration. It consolidates the
reverse-engineered knowledge in `doc/` and the architectural and
process decisions in `adr/` into an executable plan.

The integration is a clean-room replacement of an earlier ad-hoc
implementation; the prior code is archived on branch
`legacy/pre-rewrite-2026-04-23` as reference material only. The cloud
wire protocol is delegated to the `karcher-home` library behind a
single adapter module (`adr/0001-library-adapter.md`); the integration
owns the adapter, the coordinator, the entities, and the HA
integration surface.

Path convention in this directory: backticked file paths are
**repo-root-relative**. `02-requirements.md` means
`spec/02-requirements.md`; `adr/0001-library-adapter.md` means the
file at that path from the repo root.

## Reading order

For a reviewer or a new contributor, read top-down:

1. `01-vision-and-scope.md` — what is being built and why, MVP
   boundary, non-goals.
2. `02-requirements.md` — SRS; functional and non-functional
   requirements with stable IDs.
3. `03-constraints-and-deltas.md` — hard/soft constraints carried
   forward from `doc/CONSTRAINTS.md`, and the deltas the current
   architecture introduces (including adapter boundaries for
   constraints that this project does not relax).
4. `04-architecture.md` — three-layer boundary (entities → coordinator
   → adapter), module layout, data ownership, sequence diagrams,
   concurrency model, region routing.
5. `05-security-threat-model.md` — STRIDE model, mitigations, secrets
   policy, reauth policy, CA-rotation graceful degradation.
6. `06-test-strategy.md` — test pyramid, fixtures, CI gates, coverage
   targets, hardware-in-the-loop regression.
7. `07-coding-standards.md` — style, typing, async/threading rules,
   logging, error handling, commit/PR policy.
8. `08-definition-of-done.md` — per-PR, per-phase, per-release gates.
9. `09-roadmap-and-backlog.md` — Phase 0 to Phase 5 with per-phase
   acceptance criteria and concrete backlog.
10. `10-gap-carryover.md` — which gaps from the prior implementation
    this design resolves, which persist as platform-level issues, and
    which must be addressed in specific phases.
11. `11-agent-brief.md` — self-contained brief suitable as Phase 0
    input for a coding agent or an engineer starting from zero.
12. `adr/` — architecture decision records. The active set is four:
    `0001-library-adapter.md`, `0002-boundary-not-hexagonal.md`,
    `0003-error-taxonomy.md`, `0004-testing-strategy.md`.

## Glossary

| Term | Definition |
|---|---|
| RCV5 | Kärcher Robot Cleaner V5, the target device |
| 3iRobotix | OEM that supplies the vacuum firmware and operates the cloud |
| MQTT push | State updates received on `thing/event/property/post` from the broker |
| Polling fallback | Periodic `prop.get` issued by the coordinator when push is silent |
| Coordinator | `DataUpdateCoordinator` subclass owning device state for one config entry |
| Adapter | `adapter.py`: the only module that imports `karcher`; wraps the library behind an async, typed, HA-free API |
| `karcher-home` | Upstream PyPI library owning REST, MQTT, codec, topic layout, and TLS pinning for the 3iRobotix cloud |
| HAMH | [Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) (Apple Home bridge) |
| Silver | HACS quality scale tier requiring diagnostics, reauth, and full test coverage |

## Decisions already made (input to these specs)

| Decision | Value | Source |
|---|---|---|
| Deliverable form | Structured spec set | User, 2026-04-23 |
| Reuse policy | Consolidate existing `doc/` and gap-fill | User, 2026-04-23 |
| Cloud client strategy | Wrap `karcher-home` via `adapter.py`; do **not** rewrite the wire protocol in-tree | `adr/0001-library-adapter.md`, User, 2026-04-24 |
| Architectural pattern | Three one-way layers enforced by `check_imports.py`; hexagonal ports & adapters rejected as overshoot for a one-adapter system | `adr/0002-boundary-not-hexagonal.md` |
| ADR set | Four ADRs (`0001`..`0004`); previous drafts `0005`..`0011` folded into the main spec set | User, 2026-04-24 |
| First-cut scope | MVP (vacuum + battery + error), then iterate | User, 2026-04-23 |

Any subsequent change to these decisions invalidates sections of the
spec set and must be reflected in a new ADR.
