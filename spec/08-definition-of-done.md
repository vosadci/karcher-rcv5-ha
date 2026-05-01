# 08 — Definition of Done

Three scopes: PR, phase, release. Each scope's DoD is a checklist that
must pass without waiver before the work is marked complete. Anything
that would normally be "polish left for later" is either promoted into
the checklist here or explicitly out of scope in
`01-vision-and-scope.md`.

## 1. Per-PR DoD

1. **All CI gates green.** `ruff`, `ruff format --check`,
   `mypy --strict`, `pytest`, phase-graduated coverage gate
   (`coverage_gate.py`), `check_imports`, `check_docs --strict`,
   `hassfest`, `pip-audit`. HACS validation is not a CI gate (see
   `06-test-strategy.md` §5 item 8). See
   `06-test-strategy.md` §5.
2. **Tests added or updated.** No PR lands without at least one test
   change, unless the PR is doc-only or pure formatting and labelled
   as such. The coverage gate is suspended in Phase 0 (§6.2 of
   `06-test-strategy.md`); this rule still applies — code lands with
   tests, even when the gate would not fail.
2a. **No coverage regression** against `main` for any file the PR
    modifies, regardless of whether the absolute floor is met.
    Reviewer-visible only; not a CI gate to avoid flakiness on
    refactors.
3. **Docstrings present** on every public function/method added or
   modified. Citing the requirement ID in a `Covers:` line is
   **encouraged, not required** (see `adr/0004`).
4. **No `# type: ignore`** added without a justification comment.
5. **No `TODO`** left without an issue link.
6. **No new dependency** without an upper bound and a one-line
   justification in the PR body (or an ADR for substantive changes).
7. **No new `_`-prefixed external access outside `adapter.py`** (SEC-3).
8. **Changelog entry** added under `## [Unreleased]` in
   `CHANGELOG.md`, cross-referencing the requirement IDs touched.
9. **PR description** filled in per template: linked issues, test
   plan (unit/contract/integration), security considerations where
   applicable. HIL results are **not** a per-PR requirement; if the
   author happens to have a robot and ran HIL, they may include a
   line in the PR body, but absence is not a blocker (see §2 item
   4 for the rationale).
10. **Review approval not required.** This is a single-maintainer
    project; `main` advances on the maintainer's authority alone.
    Pretending that "the author re-reads the diff cold" is a
    substitute for a second reviewer is theatre — confirmation bias
    is precisely what a separate reviewer is meant to catch. The
    substitutes for a second human are the CI gates and the
    `/review` skill, both deterministic and re-runnable; their
    failure modes are documented in `spec/06-test-strategy.md` §5
    and the `.claude/skills/review/SKILL.md` file. When (if) a
    co-maintainer joins, this item is rewritten to require an
    independent review from someone who is not the PR author.
11. **No `main` merge conflicts.** PR is rebased on current `main`
    before merge.

## 2. Per-phase DoD

Each phase in `09-roadmap-and-backlog.md` exits only when all of the
below are true.

1. **All phase backlog items completed** — status `Done` in issue
   tracker.
2. **Phase acceptance criteria met** — the list under "Acceptance"
   for that phase in `09-roadmap-and-backlog.md`.
2a. **Coverage gate met for the phase about to be exited** (not for
    the next phase). The `coverage_gate.py` run is reproduced and
    pasted into the phase milestone. Bumping
    `[tool.karcher].phase` in `pyproject.toml` happens in the **same
    PR** that closes the phase milestone — not before, not after.
3. **Requirement coverage reviewed** — `docs-check` has been run; any
   orphan requirement IDs are either covered, deferred (with a named
   phase), or explicitly marked out-of-scope in the phase's closing
   note. This is a review-time pass, not a build gate.
4. **No phase HIL gate.** Manual hardware testing is reserved for
   the per-release DoD (§3 item 3). Phase exit relies on the unit,
   contract, and HA integration test layers
   (`spec/06-test-strategy.md` §3). This matches how reference
   integrations operate (Roborock in HA core, Mammotion-HA, Dreame)
   and avoids gating phase exit on maintainer hardware availability.
5. **Documentation updated:**
   - `README.md` user-visible features list reflects reality.
   - `doc/PROTOCOL.md` updated if the phase revealed new wire-level
     facts.
   - ADRs added for any in-phase decisions that warrant one (see
     `adr/README.md` — the bar for a new ADR is high).
   - `CHANGELOG.md` has the phase's entries under `## [Unreleased]`.
6. **Technical debt** introduced during the phase has been either
   fixed or captured as an issue with a target phase.
7. **No regressions** against the previous phase — the phase-specific
   test suite is a strict superset of the previous.
8. **CI green on `main`** for at least 48 h with no manual fix-ups.

## 3. Per-release DoD (includes a phase DoD)

### 3.0 Release cadence

The project releases **on demand**, not on a calendar.

- **Phase exit** cuts a `MINOR.0` tag (`v2.0.0`, `v2.1.0`, `v2.2.0`,
  `v2.3.0`, `v2.4.0` per `spec/09-roadmap-and-backlog.md` Phase 1
  through Phase 5).
- **Patch releases** between phase tags are cut when at least one of
  the following is true:
  - A security-relevant change has merged.
  - A `karcher-home`, `pytest-homeassistant-custom-component`, or
    other runtime-dep bump has merged.
  - Accumulated bugfixes are worth grouping (maintainer judgement).
- A patch release runs the **full per-release DoD below**, including
  HIL, SBOM, `/review`, upgrade test, and the `quality_scale.yaml`
  audit. There is no "lightweight patch" path. The cost of the full
  DoD is the price of the release-only HIL gate (Q5); patches that
  cannot afford it wait for the next scheduled phase exit.
- Phase 0 is internal; no Phase-0 release tag is cut. The first
  user-visible tag is `v2.0.0` at Phase 1 exit.

### 3.1 Per-release DoD checklist

Adds to the phase DoD:

1. **Version bumped** in `manifest.json` per SemVer; tag matches.
   `.github/workflows/release.yml` verifies this at release time.
2. **`CHANGELOG.md`** `[Unreleased]` block moved under the new
   version with date.
3. **HIL run passed** end-to-end against at least one account in each
   region the maintainer can test. Unvisited regions are called out in
   the release notes.
4. **Matrix CI** green against both pinned HA versions in
   `.github/workflows/ci.yml` (oldest supported + current).
5. **Release notes** drafted, including a user-facing summary, any
   required user action (reauth, etc.), and a link to the migration
   notes.
6. **HACS** metadata is manually validated (`hacs/action` is not run
   in CI for unregistered repos; see `06-test-strategy.md` §5 item 8).
7. **SBOM** generated (CycloneDX JSON), attached as a release asset.
8. **Security review** (`/review` skill on the release branch): no
   outstanding blockers.
9. **Quality-scale claim is auditable.** The `quality_scale` field in
   `manifest.json` (`bronze` / `silver`) may not exceed the highest
   tier whose every item is marked `done` (or `exempt` with a
   justification) in
   `custom_components/karcher_home_robots/quality_scale.yaml`.
   `.github/workflows/release.yml` runs a check that fails the release
   if the manifest claim outruns the YAML reality. Premature claims
   are blocked at release, not by review judgement.
10. **Upgrade test**: install the previous release, populate with a
    realistic config, upgrade to this release, assert entities
    survive and `async_migrate_entry` completes. Documented in
    `tests/integration/test_migration_integration.py` (FR-MG-4).

## 4. What "in progress" requires

An issue moves to `In progress` only when:

- It has an owner.
- Acceptance criteria are listed in the issue.
- Its design impact is understood — no architectural surprise.
- A branch is opened.
- Relevant tests are identified (or the issue itself is a test
  issue).

## 5. Waivers

Any DoD item can be waived only by:

- A written rationale in the PR description or phase retrospective.
- A compensating control (e.g. "coverage below threshold for this
  module because X; adding HIL test Y next sprint").
- Explicit acknowledgement by the reviewer (reviewer distinct from
  author where a second human exists).

If a waiver carries past the PR — i.e. anyone reading `main` later
needs to know it exists — the PR creates `WAIVERS.md` at the repo
root with one entry. Until that happens the file does not exist;
empty-register ceremony is not maintained.

Each entry has: ID (`W-NNNN`, monotonic), date, source (the rule
being waived: FR/NFR/SEC/OPS ID, DoD item, ADR number, or
coding-standards section), rationale, scope, expiry (ISO date or
release tag — no open-ended waivers), owner, and mitigation.
`check_docs` flags expired entries when the file exists; expired
waivers without resolution block the next phase's DoD.
