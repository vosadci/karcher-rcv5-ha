---
name: docs-check
description: Check that the spec set, ADRs, CHANGELOG, CLAUDE configuration, and manifest/HACS versions are internally consistent and up to date. Runs the deterministic docs checker, then does a narrative pass for drift the script cannot catch.
---

# Docs check

Catches documentation drift across the spec set. Has two passes:

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
2. **ADR chain.** `Supersedes:` and `Superseded-by:` fields are mutual;
   the losing ADR has `Status: Superseded`.
3. **Requirement references.** Any `FR-*` / `NFR-*` / `SEC-*` / `OPS-*`
   ID cited in any spec file exists in `02-requirements.md`.
4. **ADR references.** Every `ADR-NNNN` citation resolves to an
   `adr/NNNN-*.md` file.
5. **Backlog references.** Every `P<phase>-<n>` citation exists in
   `09-roadmap-and-backlog.md`.
6. **Waiver expiry.** Open waivers in `docs/WAIVERS.md` with an ISO-date
   expiry in the past are reported.
7. **Required structure.** `README.md` has a top heading; `CHANGELOG.md`
   has `[Unreleased]`; `CLAUDE.md` has `## Agents`.
8. **Version consistency.** `hacs.json` `homeassistant` agrees with
   `custom_components/karcher_home_robots/manifest.json` (when present)
   and is covered by the CI HA matrix in `.github/workflows/ci.yml`.

If the script exits non-zero, stop and report the failures. Don't do
the narrative pass on a red tree.

## Pass 2 — narrative

Walk each of the items below. For each, say "clean" or list concrete
drift with file, line, and suggested fix.

### Reading order and index

- `README.md` lists the files in order 01–11, adr/, .claude/, tooling.
  Any newly added top-level doc should be named in the reading order.
- The "Decisions made" table in `README.md` (if present) matches the
  ADR set.

### CLAUDE.md coverage

- Every agent in `.claude/agents/*.md` appears in `CLAUDE.md` `## Agents`
  with a one-line purpose.
- Every skill in `.claude/skills/*/SKILL.md` appears in `CLAUDE.md`
  `## Skills` with invocation form.
- "Hard constraints" section reflects the current ADR set; no stale
  constraints left over from a superseded decision.

### Phase alignment

- `CHANGELOG.md` `[Unreleased]` `### Phase: N — ...` header names the
  current phase.
- The named phase exists as a heading in `09-roadmap-and-backlog.md`.
- Backlog items marked "in progress" are consistent with open PRs and
  the current branch name prefix.

### Architecture and standards

- `04-architecture.md` module tree matches the actual folder layout
  under `custom_components/karcher_home_robots/`.
- The import-graph rules in `04-architecture.md` §3 match what
  `tests/tools/check_imports.py` enforces. If the code enforces more
  than the doc describes, update the doc.
- `07-coding-standards.md` banned imports match the ruff
  `flake8-tidy-imports.banned-api` config in `pyproject.toml`.

### Security alignment

- `05-security-threat-model.md` SR-1..6 list matches the tests in
  `tests/contract/test_security_regressions.py`.
- Secrets policy still names the right files and passwords and excludes
  them from source.
- Every `SEC-*` listed in the threat model has a corresponding entry in
  `02-requirements.md`.

### Testing alignment

- `06-test-strategy.md` layer names match the pytest markers in
  `pyproject.toml` (`unit`, `contract`, `integration`, `hardware`).
- Coverage targets in the strategy match the gates in `pyproject.toml`
  `[tool.coverage.report]` and `.github/workflows/ci.yml`.

### Protocol doc

- Any capture command, topic, or payload cited in a spec must match
  `../doc/PROTOCOL.md`. Dates on protocol findings should be within
  the last two years unless flagged as historical.

### Changelog completeness

- Every merged PR since the last release tag has a line under
  `[Unreleased]` citing its requirement IDs.
- Every requirement ID listed in `[Unreleased]` exists in
  `02-requirements.md`.

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
