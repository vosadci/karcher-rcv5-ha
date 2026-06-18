---
name: docs-check
description: Check that ARCHITECTURE.md, ROADMAP.md, CHANGELOG, CLAUDE configuration, and manifest/HACS versions are internally consistent and up to date. Runs the deterministic docs checker, then does a narrative pass for drift the script cannot catch.
---

# Docs check

Catches documentation drift across the docs. Has two passes:

1. **Deterministic** — `python3 tests/tools/check_docs.py --strict`.
2. **Narrative** — a manual read-through for things the script cannot
   see (stale prose, contradictions, outdated phase language).

## Pass 1 — deterministic

Run:

```bash
python3 tests/tools/check_docs.py --strict
```

The checker covers:

1. **Broken links.** Every relative markdown link resolves to a real
   file.
2. **Waiver expiry.** Open waivers in `WAIVERS.md` with an ISO-date
   expiry in the past are reported.
3. **Required structure.** `README.md` has a top heading; `CHANGELOG.md`
   has `[Unreleased]`; `CLAUDE.md` has `## Skills`.
4. **Version consistency.** `hacs.json` `homeassistant` agrees with
   `custom_components/karcher_home_robots/manifest.json` (when present)
   and is covered by the CI HA matrix in `.github/workflows/ci.yml`.
5. **`doc/` index completeness.** Every file in `doc/` is listed in
   `doc/README.md`.

(The earlier spec/ADR traceability checks — requirement-ID, ADR-chain,
and backlog references — were dropped when the `spec/` set and `adr/`
apparatus were consolidated into `ARCHITECTURE.md` and `ROADMAP.md`.)

If the script exits non-zero, stop and report the failures. Don't do
the narrative pass on a red tree.

## Pass 2 — narrative

Walk each of the items below. For each, say "clean" or list concrete
drift with file, line, and suggested fix.

### Reading order and index

- `README.md` and `ARCHITECTURE.md` name the current top-level docs.
  Any newly added top-level doc should be referenced where relevant.

### CLAUDE.md coverage

- Every agent in `.claude/agents/*.md` appears in `CLAUDE.md` `## Agents`
  with a one-line purpose.
- Every skill in `.claude/skills/*/SKILL.md` appears in `CLAUDE.md`
  `## Skills` with invocation form.
- "Hard constraints" section reflects `ARCHITECTURE.md`; no stale
  constraints left over from a superseded decision.

### Phase alignment

- `CHANGELOG.md` `[Unreleased]` `### Phase: N — ...` header names the
  current phase.
- The named phase exists as a heading in `ROADMAP.md`.
- Backlog items marked "in progress" are consistent with open PRs and
  the current branch name prefix.

### Architecture and standards

- `ARCHITECTURE.md` module tree matches the actual folder layout
  under `custom_components/karcher_home_robots/`.
- The import-graph rules in `ARCHITECTURE.md` match what
  `tests/tools/check_imports.py` enforces. If the code enforces more
  than the doc describes, update the doc.
- `ARCHITECTURE.md` banned imports match the ruff
  `flake8-tidy-imports.banned-api` config in `pyproject.toml`.

### Security alignment

- Security controls described in `ARCHITECTURE.md` are covered by
  `tests/contract/test_adapter.py` (exception mapping, redaction) and the
  pre-commit `forbidden-strings` hook (no credential literals in source).
- Secrets policy still names the right files and passwords and excludes
  them from source.

### Testing alignment

- `ARCHITECTURE.md` layer names match the pytest markers in
  `pyproject.toml` (`unit`, `contract`, `integration`, `hardware`).
- Coverage targets in `ARCHITECTURE.md` match the gates in
  `pyproject.toml` and `tests/tools/coverage_gate.py`.

### Protocol doc

- Any capture command, topic, or payload cited in a spec must match
  `../doc/PROTOCOL.md`. Dates on protocol findings should be within
  the last two years unless flagged as historical.

### Changelog completeness

- Every merged PR since the last release tag has a line under
  `[Unreleased]`.

## Output format

```
## Docs check — <branch>

### Pass 1 — deterministic
  <short summary of errors / warnings, or "clean">

### Pass 2 — narrative
  Reading order          ✓ / ⚠ / ✗
  CLAUDE.md coverage     ✓ / ⚠ / ✗
  Phase alignment        ✓ / ⚠ / ✗
  Architecture           ✓ / ⚠ / ✗
  Security               ✓ / ⚠ / ✗
  Testing                ✓ / ⚠ / ✗
  Protocol               ✓ / ⚠ / ✗
  Changelog              ✓ / ⚠ / ✗

## Findings
  - <file:line or section> — <concrete drift> — <suggested fix>

## Verdict
FRESH / MINOR DRIFT / STALE
```

Cite file paths and, where relevant, line numbers or section headings.
Do not edit files. Propose diffs; let the user apply them.
