# Contributing

The `karcher_home_robots` Home Assistant custom integration for the
Kärcher RCV5 robot vacuum. The specification under `spec/` (start at
`spec/README.md`) and the four ADRs in `adr/` are the source of truth
for design and process. Read them before writing code.

## Local setup

```bash
make install          # pip install -e .[test,dev]
pre-commit install    # enable local hooks
```

Python 3.12+ is required. Use the project venv, not a system
interpreter.

## Development loop

```bash
make test            # unit + contract + integration
make test-cov        # tests with coverage report (no gate)
make coverage-gate   # phase-graduated coverage gate (suspended in Phase 0)
make lint            # ruff check + format check
make type            # mypy --strict
make check           # lint + type + test-cov + coverage-gate + import-graph + docs
```

`make coverage-gate` reads `[tool.karcher].phase` from
`pyproject.toml` and enforces the per-phase floors in
`spec/06-test-strategy.md` §6.1. The gate is suspended in Phase 0
and blocking from Phase 1; bumping the phase happens in the same
PR that closes the phase milestone (DoD §2 item 2a).

Single test:

```bash
python3 -m pytest tests/unit/test_state_derivation.py::test_idle -v
```

## Branch and commit discipline

- Branch name encodes the backlog item: `<phase>-<n>/<short-desc>` —
  e.g. `P1-7/config-flow-reauth`.
- Commits are **per logical phase**, not per file. Present-tense
  imperative messages. Conventional Commits (`feat:`, `fix:`, `docs:`,
  `chore:`, `test:`, `refactor:`) are encouraged but not enforced.
- No force-push to `main`. No `--amend` on pushed commits.
- Never commit secrets. The `gitleaks` and `forbidden-strings` hooks
  will stop you; the known APK passwords `sc2021` and
  `hj2WtyHYYEvBTxDb` must never appear in integration source.

## Pull requests

Before opening a PR:

1. `make check` is green locally.
2. `CHANGELOG.md` `[Unreleased]` has an entry citing the
   `FR`/`NFR`/`SEC`/`OPS` ID the change satisfies.
3. The PR title starts with the backlog item ID.
4. The PR body lists: intent, scope, tests added, ADRs touched (if
   any), `karcher-home` version validated against, deployment notes.

At merge time the `/review` skill runs the full pipeline: tests, lint,
type, import graph, SOLID review, HA pattern review, security review,
simplification review. All must be ✓ or explicitly waived in
`WAIVERS.md` per the procedure in `spec/08-definition-of-done.md` §5.

## ADRs

Changes that alter module boundaries, the import graph, the error
taxonomy, the state model, the config-entry schema, or the
adapter's contract with `karcher-home` require a new ADR under
`adr/`. Use the template in `adr/README.md`. Reference the ADR number
from the PR body.

If you need to supersede an existing ADR, add a new one with
`Supersedes: ADR-NNNN` and update the old one's status to
`Superseded`. The current set is `0001-library-adapter`,
`0002-boundary-not-hexagonal`, `0003-error-taxonomy`,
`0004-testing-strategy`.

## Tests are a requirement, not a courtesy

Every FR / NFR / SEC / OPS requirement in `spec/02-requirements.md`
should be cited by at least one test docstring via `Covers: FR-X-N`.
Traceability is a **convention, not a CI gate** (ADR-0004):
`docs-check` warns on orphan requirement IDs at review time; it does
not fail the build. Gaps are addressed in review rather than blocked
at merge.

Coverage gates (blocking): lines ≥ 85 %, branches ≥ 80 % overall;
`adapter.py` and `coordinator.derive_vacuum_state` at 100 %.

## Protocol discoveries

When you learn anything new about the wire protocol, update
`doc/PROTOCOL.md` with the exact capture command, topic or endpoint,
payload shape, and capture date. If the discovery affects the
adapter's interaction with `karcher-home`, that is a separate
logical commit from any behavioural change that uses it.

If a finding suggests a `karcher-home` upstream bug or missing
feature, open an issue in that project and reference it in
`adapter.py`'s work-around comment.

## Dependencies

- Every runtime dep is **pinned to an exact version** (`==X.Y.Z`) in
  both `pyproject.toml` and `manifest.json` `requirements`. Ranges
  (`>=`, `~=`, `,<`) are forbidden. Same discipline as HA core
  integrations (e.g. `python-roborock==5.5.1`).
- `karcher-home` bumps are special:
  - Patch bumps: dependabot auto-PR; HIL smoke required before merge.
  - Minor bumps: same + review of CHANGELOG in upstream.
  - Major bumps: a short design note in the PR body plus full HIL
    suite.
- `requests`, `urllib3`, `pickle`, `marshal` are banned in the
  integration. `paho.mqtt.*` is not imported directly; it is accessed
  only through `adapter.py` via `karcher-home`.

## Security

See `spec/05-security-threat-model.md` for the threat model and the SEC-*
requirements. Every new log line above DEBUG must be checked for
credential leakage. Every new dependency must have an upper bound and
a documented reason in the PR body or an ADR.

Vulnerabilities: report privately to the maintainers, not via a
public issue. See `SECURITY.md`.

## Claude usage

If you use Claude Code in this repo, the configuration in `.claude/`
governs behaviour. Two skills are available: `/review` (combined
review) and `/docs-check` (docs freshness). Neither runs
automatically. The repository-level `CLAUDE.md` is the entry point;
read it before prompting.

## License

By contributing you agree your contributions are licensed under the
project's MIT license.
