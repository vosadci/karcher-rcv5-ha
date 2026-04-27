# ADR-0002: Boundary discipline, not hexagonal dogma

Status: Accepted
Date: 2026-04-24

## Context

The first draft of the rewrite adopted a full hexagonal (ports &
adapters) architecture: a pure domain core, abstract "port" protocols,
and swappable adapter implementations. For an integration of this size
— one vendor, one device family, one cloud — that shape imports more
structure than it earns back. Hexagonal makes sense when adapters are
genuinely interchangeable and the domain outlives the infrastructure;
neither applies here.

What does matter, and what the old implementation got wrong, is
**layer discipline**: HA-specific code leaking into transport code,
transport code leaking into entity code, state being mutated from four
places, etc. That is a boundary problem, not a topology problem.

## Options considered

1. **Full hexagonal.** Ports for every collaborator (auth, REST, MQTT,
   state, clock), each with a `Protocol`, fake, and real implementation.
2. **Clean-architecture-lite.** Named layers (domain / application /
   infrastructure) with directional import rules enforced in CI.
3. **Pragmatic boundaries (chosen).** A small number of sharp module
   boundaries enforced by an import-graph check; no protocol-per-port,
   no ceremony.

## Decision

Enforce three one-way boundaries. Everything else stays flat.

```
┌──────────────────────────────────────────────────────────────┐
│ HA layer                                                     │
│   vacuum.py · sensor.py · binary_sensor.py · select.py       │
│   config_flow.py · __init__.py · entity.py                   │
│   — imports: coordinator.py, const.py, HA core               │
└───────────────┬──────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────┐
│ Coordinator layer                                            │
│   coordinator.py · state.py                                  │
│   — imports: adapter.py, const.py                            │
│   — owns VacuumState + derivation; merges push + poll        │
└───────────────┬──────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────┐
│ Adapter layer                                                │
│   adapter.py                                                 │
│   — imports: karcher, asyncio, logging                │
│   — the ONLY module that may import karcher           │
│   — the ONLY module that may access third-party privates     │
└──────────────────────────────────────────────────────────────┘
```

The rules, enforced by `tests/tools/check_imports.py` in CI:

1. **HA layer may not import `karcher`**, directly or
   transitively through anything but `coordinator.py`.
2. **Coordinator layer may not import `homeassistant.*`** except the
   types it actually needs (`DataUpdateCoordinator`, `UpdateFailed`,
   `HomeAssistant`).
3. **Adapter layer may not import `homeassistant.*`** at all. It takes
   primitives in and returns typed DTOs; the coordinator maps those to
   HA's world.

Derivation — the translation from raw `DeviceProperties` to the
integration-owned `VacuumState` enum — lives exactly once, in
`coordinator.derive_vacuum_state`. No entity reads raw properties.

## What we are *not* doing

- No `Protocol`-based ports. The adapter is a concrete class; tests
  that need to fake it use a fake class, not a typed interface.
- No per-layer package split. Files stay at the integration root; the
  boundary is defined by imports, not by directory layout.
- No DI container, no service locator, no mediator. Construction happens
  in `__init__.py` and is passed explicitly.

## Consequences

**Positive**

- The rules are four lines of code to enforce, and they catch the
  failure modes the previous codebase actually hit.
- New contributors can read the whole integration linearly without
  chasing indirection.
- The layer that has to change when `karcher-home` changes — the
  adapter — is the same layer that has to change when the vendor bumps
  the protocol. One place, one reason.

**Negative**

- Swapping out `karcher-home` for a different transport would require
  adapter work, not a port implementation. Accepted: there is no second
  transport, and if one appears, introducing a port then is cheaper
  than carrying it speculatively now.
- Contributors coming from hex-architecture backgrounds may expect
  ports. The layering ADR and the import-check message are the
  documentation.

## Enforcement

`tests/tools/check_imports.py` walks the integration package, parses
imports, and fails CI on any violation of the three rules above. The
check runs in pre-commit and CI.
