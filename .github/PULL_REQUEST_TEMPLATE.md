<!--
  Title must begin with the backlog item ID, e.g.
    P1-7 Config flow: reauth on 401/403
-->

## Intent

<!-- One paragraph: what problem does this solve, and for whom? -->

## Scope

- Backlog item: <!-- P<phase>-<n> from 09-roadmap-and-backlog.md -->
- Requirements satisfied: <!-- FR-*, NFR-*, SEC-*, OPS-* IDs -->
- ADRs touched: <!-- ADR-NNNN or "none" -->
- `karcher-home` version validated against: <!-- e.g. 0.3.7 -->

## Changes

<!-- Bulleted list of behaviour changes; one line each. -->

## Tests

- [ ] Unit tests cover new pure logic
- [ ] Contract tests cover new adapter behaviour (if `adapter.py` changed)
- [ ] Integration tests cover new HA-visible behaviour (if entities changed)
- [ ] Adapter and `coordinator.derive_vacuum_state` coverage still at 100 %

## Definition of Done (per-PR)

Cross-check against `08-definition-of-done.md`:

- [ ] `make check` passes locally
- [ ] `CHANGELOG.md` `[Unreleased]` has an entry with requirement IDs
- [ ] No credentials, tokens, SNs, or payloads in logs above DEBUG
- [ ] No new deps without upper bound and justification
- [ ] No private HA APIs or `hass.data` writes from non-HA layers
- [ ] No `_`-prefixed third-party access outside `adapter.py`
- [ ] No `tls_insecure_set(True)`
- [ ] No blocking I/O outside `adapter.py` (and only via `run_in_executor`)
- [ ] If manifest version bumped, changelog section matches
- [ ] If config-entry schema changed, `async_migrate_entry` updated + test
- [ ] If entity unique_id shape changed, migration test covers it (FR-U)
- [ ] If protocol-level finding, `doc/PROTOCOL.md` has a dated entry

## Deployment notes

<!-- Anything out of the ordinary: migrations, cache clears, manual
     scp to the Synology, re-auth required, etc. -->

## Review

`/review` on the changed branch is expected before merge. The review
skill rolls up SOLID, HA-pattern, security, and simplification checks
into one pass; no specialist agents are invoked.
