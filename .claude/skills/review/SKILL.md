---
name: review
description: Single-pass manual review of the current branch's changes — correctness, layering, async hygiene, HA patterns, security posture. No delegation to specialist agents. Manual invocation only.
---

# Review

A focused, diff-level review in one pass. Rolls up what used to be four
specialist agents (SOLID, HA, security, simplify) into a single
lightweight check. Use when you want a read before opening a PR — not a
full pre-merge pipeline.

## Inputs

Start by running:

```bash
git status
git diff main...HEAD --stat
git log main...HEAD --oneline
```

If the diff is empty, stop and say so.

Read `ARCHITECTURE.md` to orient on what the change should satisfy, and
`ROADMAP.md` for the current phase and backlog.

## What to check

Walk the diff top-to-bottom. For each changed file, answer these
questions. Treat them as a linear checklist, not a deep multi-pass
analysis.

### 1. Intent

What is the change trying to accomplish? Tie it to a `ROADMAP.md`
item or the branch/PR intent. If you cannot, that is a finding.

### 2. Correctness

Does the code do what its docstring/commit message says? Look for the
usual suspects: off-by-one, wrong `await`, swapped args, missing
`None` check, shadowed variable, dead branch.

### 3. Layering (`ARCHITECTURE.md`)

Three rules, enforced in principle by `tests/tools/check_imports.py`:

- HA entity modules do not import `python_karcher` directly.
- `coordinator.py` is the only module allowed to import from the
  adapter's public surface; it does not import `python_karcher`
  directly either.
- `adapter.py` is the only module that may import `python_karcher` or
  access third-party privates.

If the diff crosses a layer boundary, the reason must be explicit — a
comment, an ADR, or a commit message.

### 4. Async hygiene (`ARCHITECTURE.md`, `CLAUDE.md`)

- No blocking I/O on the event loop.
- `run_in_executor` / `hass.async_add_executor_job` is allowed **only
  inside `adapter.py`** for calling into `python-karcher`.
- paho-mqtt callbacks arrive on a foreign thread; re-entry into the
  loop goes through `loop.call_soon_threadsafe`, never direct state
  mutation.
- Background tasks have a cancel path and are awaited on unload.

### 5. Error handling (`ARCHITECTURE.md` error taxonomy)

- Exceptions raised by the adapter are subclasses of `ClientError`.
- `python-karcher` native exceptions are mapped to the taxonomy inside
  the adapter — they do not leak upward.
- Coordinator translates `AuthError` → `ConfigEntryAuthFailed`,
  `PermanentError` → `ConfigEntryError`, `TransientError` →
  `UpdateFailed`.
- No bare `except:`. No swallowed `asyncio.CancelledError`.

### 6. Security posture

- No credentials, tokens, serial numbers, or payload bodies above
  `DEBUG` level. Redaction goes through the `_redact()` helper.
- No `tls_insecure_set(True)`. The bundled CA is pinned.
- No `_`-prefixed third-party access outside `adapter.py`.
- No new dependency without an upper bound and a one-line reason in
  the PR body.
- The APK-known strings `sc2021` and `hj2WtyHYYEvBTxDb` must not
  appear anywhere in integration source — the `forbidden-strings`
  pre-commit hook catches this.

### 7. Home Assistant patterns (target: HA 2025.1+, HACS Silver)

- `DataUpdateCoordinator` used correctly; no parallel state stores.
- Battery is a **separate `SensorEntity`** (it was removed from
  `VacuumEntity` in HA 2026.8).
- `VacuumActivity` enum used, not `STATE_*` strings.
- `unique_id` stable across restarts; any schema change triggers
  `async_migrate_entry` and is covered by a migration test.
- `manifest.json` has `iot_class: cloud_push` and the
  `quality_scale` value tracked in `ROADMAP.md`.

### 8. Tests (`ARCHITECTURE.md`)

- Every new code path has a test: unit if it is pure, contract if it
  touches the adapter, integration if it is HA-visible.
- A `Covers:` note in the docstring where the tie is obvious — this is
  convention, not a CI gate.
- Critical paths (coordinator state derivation, adapter exception
  mapping) are held at 100 %.

### 9. Docs

- `CHANGELOG.md` `[Unreleased]` has an entry for the change.
- If the adapter's public surface changed, its docstring is updated.
- If there is a protocol-level finding, `doc/PROTOCOL.md` has a
  dated entry with the exact capture command.

### 10. Reuse / simplicity

- Is there a shared helper being duplicated? Point it out.
- Is a new abstraction earning its weight, or is it a speculative
  generalisation? Favour removing lines over adding them.

## Output

A short, structured report — not prose.

```
## Review — <branch>

### Intent
  <one-line summary of what the change accomplishes>

### Findings
  - <file>:<line> — <finding>
    Severity: blocker | issue | nit

### Tests
  - Covered: <list>
  - Missing: <list>

### Docs
  - <changelog / protocol / docstring status>

## Summary
  <3-sentence verdict>
```

Severity rubric:

- **blocker** — must fix before merge. Correctness bug, layering
  violation, security regression, missing required migration.
- **issue** — should fix before merge; follow-up ticket acceptable with
  user agreement. Missing test, unclear name, small refactor.
- **nit** — style or taste; mergeable as-is.

Do not run `git commit`, `git push`, or any destructive operation. Do
not auto-fix — propose diffs in the report and let the user apply them.
