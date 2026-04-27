# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries under `[Unreleased]` are grouped by `Added`, `Changed`,
`Deprecated`, `Removed`, `Fixed`, `Security`. Every user-visible
change cites the `FR-*` / `NFR-*` / `SEC-*` / `OPS-*` IDs it
satisfies. Traceability is a convention, not a CI gate (ADR-0004).

## [Unreleased]

### Phase: 0 — Scaffold

### Added
- Specification set under `rewrite/` (`SPEC-INDEX.md`, `01`–`11`,
  four ADRs `0001`..`0004`, `CLAUDE.md`, `CONTRIBUTING.md`,
  `CHANGELOG.md`).
- `.claude/skills/review/` — combined review skill (layering, HA
  patterns, SOLID, security posture, simplification).
- `.claude/skills/docs-check/` — docs-freshness check.
- Baseline tooling: `pyproject.toml` (`ruff`, `mypy --strict`,
  `pytest`, coverage thresholds ≥ 85 % lines / ≥ 80 % branches),
  `Makefile`, `.pre-commit-config.yaml`, `hacs.json`, `.gitignore`.
- CI workflow `.github/workflows/ci.yml` pinning HA `2025.1.0` and
  `2025.10.0`, pinning `hacs/action@22.5.0`, running `pip-audit
  --strict` (no `|| true`), `hassfest`, and
  `tests/tools/check_imports.py`.
- Release workflow `.github/workflows/release.yml` verifying
  `manifest.json` version matches the tag and packaging the
  integration zip.
- Dependabot config `.github/dependabot.yml` with grouped updates
  (`python-patches`, `pytest-stack`, `lint-stack`,
  `actions-patches`).
- Pull-request template
  (`.github/PULL_REQUEST_TEMPLATE.md`) and single-maintainer
  `.github/CODEOWNERS`.

### Changed
- **Cloud-client strategy:** the rewrite wraps `karcher-home`
  behind a single `adapter.py` rather than rewriting the wire
  protocol in-tree (`adr/0001-library-adapter.md`). The adapter owns
  the async boundary (`run_in_executor`), the foreign-thread bridge
  (`loop.call_soon_threadsafe` for paho-mqtt callbacks), and
  containment of the two documented upstream bugs
  (`net_stauts` typo, stale `get_device_properties` and unparsed
  `property/post`).
- **Architectural pattern:** three one-way layers (entities →
  coordinator → adapter) enforced by `tests/tools/check_imports.py`,
  replacing the previous hexagonal ports-and-adapters framing
  (`adr/0002-boundary-not-hexagonal.md`).
- **Error taxonomy:** single `ClientError` hierarchy with
  `AuthError`, `TransientError` (incl. `RateLimited`),
  `PermanentError`, `ValidationError`, `ProtocolError`
  (`adr/0003-error-taxonomy.md`).
- **Testing strategy:** traceability is a convention (review-time
  warning only), not a CI gate. Coverage thresholds lowered from
  `≥ 90 %/≥ 85 %` to `≥ 85 %/≥ 80 %` overall; `adapter.py` and
  `coordinator.derive_vacuum_state` held at 100 %
  (`adr/0004-testing-strategy.md`).
- **Requirements namespaces** renamed for clarity:
  - `FR-A` (Account) — includes `FR-A-10` rate-limit tolerance on
    reauth.
  - `FR-RG` (Region) — five region-routing requirements including
    endpoint snapshot persistence.
  - `FR-MG` (Migration) — five requirements, including
    `async_migrate_entry` v1→v2 and unique-id re-key
    (`FR-MG-1..5`).
  - `FR-OF` (Offline) — five offline-semantics requirements.
  - `FR-UP` (Updates) — push/poll semantics, monotonic HA-side
    receipt ordering (`FR-UP-5`), resync on reconnect
    (`FR-UP-6`).
- **NFR-R-6** added: broker-CA rotation surfaces a `repair` issue
  rather than silently falling back to `tls_insecure_set(True)`.
- **SEC-3** scoped: private-API access to `karcher-home` is
  permitted only inside `adapter.py`; the prohibition is hard
  everywhere else and enforced by `check_imports.py`.
- **License reverted to MIT.** An earlier draft of the rewrite
  carried an Apache-2.0 `LICENSE` (with the copyright placeholder
  unfilled) plus matching `pyproject.toml`, `README.md`, and
  `CONTRIBUTING.md` claims. This was an unintentional drift from the
  original repo's MIT licence; restored on continuity grounds. Aligns
  with `karcher-home` upstream (also MIT) and avoids Apache-2.0
  compliance overhead (NOTICE, patent grant) without a real benefit
  for a small HACS integration.

### Deprecated

### Removed
- **ADRs 0005..0011** (`secrets-and-reauth`, `error-taxonomy`
  duplicate, `room-selection-contract`,
  `diagnostics-and-silver-quality`, `matter-contract`,
  `testing-strategy`, `in-tree-cloud-client`,
  `hexagonal-architecture`). Survivors renumbered into the four-ADR
  set above; retired rationale folded into the main spec files
  (reauth policy into `05-security-threat-model.md` §4, room
  selection into `02-requirements.md` `FR-V`/`FR-SL`, diagnostics
  into `09-roadmap-and-backlog.md` Phase 4, Matter contract into
  `02-requirements.md` `FR-AH`).
- **Claude reviewer agents:** `solid-reviewer`, `security-reviewer`,
  `design-reviewer`, `ha-reviewer`, `pr-reviewer`. Their checklists
  are absorbed into `/review`.
- **Claude skills:** `security-review`, `simplify`, `solid-check`.
  Absorbed into `/review`.
- **Traceability CI job** and
  `tests/tools/check_traceability.py`. Traceability remains as a
  docstring convention surfaced by `check_docs.py` at review time.
- **Python 3.13** from the CI matrix; HA targets Python 3.12 in the
  supported release range.
- `aiomqtt`, `pydantic`, `cryptography` from runtime dependencies —
  all owned by `karcher-home`.
- `mutmut` from dev dependencies — promoted to a cross-cutting
  backlog item (`X-5`), not a CI gate.

### Fixed
- `pip-audit --strict` is now actually strict: the trailing
  `|| true` has been removed from the CI step.
- HACS and HA versions are pinned in CI rather than floating
  (`hacs/action@22.5.0`; HA `2025.1.0` + `2025.10.0` matrix).

### Security
- Reauth policy documented (`05-security-threat-model.md` §4):
  vendor 429s surface as `TransientError`, not `AuthError`; region
  and `device_id` are preserved across reauth; `Retry-After` honoured
  up to a 60 s ceiling.
- CA-rotation graceful degradation (`NFR-R-6`,
  `05-security-threat-model.md` §5): on fingerprint mismatch, the
  adapter raises `TransientError`, the coordinator raises
  `UpdateFailed`, and a persistent HA `repair` issue
  (`ca_rotation_required`) is created — never a silent insecure
  fallback.

---

## Releases

<!-- Release entries go here when tags are cut. Template:

## [2.0.0] — YYYY-MM-DD

### Added
- … (FR-A-1, FR-V-1)

### Changed
- …

### Security
- … (SEC-*)

-->
