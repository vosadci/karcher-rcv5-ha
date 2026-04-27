# ADR index

Each ADR records a significant decision for the project. The set is
deliberately small: four ADRs, four decisions. Everything else lives
inline in the relevant spec document so it stays close to the thing
it governs. ADRs supersede previous decisions only by an explicit
`Supersedes:` line. Pre-rewrite decision records were removed on
the spec-set consolidation; this directory holds the only
authoritative set.

| # | Title | Status |
|---|---|---|
| 0001 | Library-adapter — wrap `karcher-home`, do not rewrite | Accepted |
| 0002 | Boundary discipline, not hexagonal dogma | Accepted |
| 0003 | Error taxonomy | Accepted |
| 0004 | Testing pyramid | Accepted |

Template:

```
# ADR-XXXX: Title

Status: Accepted | Proposed | Superseded by ADR-YYYY
Date: YYYY-MM-DD

## Context
## Options considered
## Decision
## Consequences
## Supersedes (optional)
```

New ADRs are only warranted for decisions that would otherwise require
editing two or more of `04-architecture.md`, `05-security-threat-model.md`,
`06-test-strategy.md`, or the adapter-layer API. Anything smaller goes
in the spec doc directly.
