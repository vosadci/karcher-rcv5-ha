# 07 — Coding standards

Binding rules for code in this project. Any rule can be waived by an
ADR; no rule can be waived by a PR review alone.

## 1. Language, version, types

- Python 3.12+ for development and deployment.
- `from __future__ import annotations` at the top of every module.
- `mypy --strict` must pass with zero errors. No `# type: ignore`
  without a one-line justification comment.
- Public functions and methods have full type annotations. Private
  helpers have them too; it's rarely worth the time saved to skip.
- `Protocol` classes serve two purposes here: (a) test-seam fakes
  for components with multiple real implementations; (b) **typing
  the `karcher` upstream surface**, which ships no stubs. The
  Protocols are declared in `_types.py`; the adapter applies a
  single `cast(KarcherHomeProtocol, raw_client)` at construction and
  is type-checked against the Protocol thereafter
  (`spec/04-architecture.md` §4.1.1).
- No `Any` in the public surface of `adapter.py`. `Any` is permitted
  inside the `KarcherHomeProtocol` declaration where the upstream
  type is genuinely opaque (paho internals via `_mqtt`, callback
  envelopes); each such `Any` carries a one-line comment naming the
  reason.
- `# type: ignore` is allowed only with a `[error-code]` and a
  one-line justification. The Protocol-cast strategy means it should
  almost never be needed inside `adapter.py`; appearance in any
  other module is a review-blocker absent an exceptional
  justification.

## 2. Async and threading

- Every I/O call from the coordinator layer upward is `async`.
- `run_in_executor` / `hass.async_add_executor_job` is **permitted
  only inside `adapter.py`** — the adapter wraps the synchronous
  `karcher-home` API. No other module may use an executor.
- paho-mqtt (used transitively via `karcher-home`) delivers
  callbacks on a background thread. Re-entry into the event loop
  **must** go through `loop.call_soon_threadsafe(...)`. This is the
  adapter's job; no other layer knows paho exists.
- No `threading.Thread`, `threading.Lock`, or `queue.Queue` anywhere.
  `asyncio.Lock` / `asyncio.Queue` where synchronisation is required.
- Background tasks are tracked in a per-instance `set[asyncio.Task]`.
  Every `create_task` call is paired with a `task.add_done_callback`
  that drops the handle and logs exceptions.
- Use `async with asyncio.timeout(...)` for timeouts.
  `asyncio.wait_for` is deprecated and not used in new code.
- Updates to HA state go through
  `coordinator.async_set_updated_data`. The adapter never calls HA
  APIs.

## 3. Module discipline

- One class per file if the class is more than ~100 LOC.
- Files ≤ 500 LOC. Beyond that, split.
- Functions ≤ 50 LOC. Beyond that, consider a method object.
- Cyclomatic complexity ≤ 10 per function. `ruff` checks.
- No circular imports. Enforced by `tests/tools/check_imports.py`.

## 4. Names

- Module names: `snake_case`.
- Class names: `CamelCase`. HA-facing entity classes are prefixed
  `Karcher` (carrying forward the existing convention, kept for
  unique_id stability).
- Constants: `UPPER_SNAKE_CASE`.
- Private: single leading underscore. No dunders except the standard
  ones.
- Test modules mirror the module under test: `adapter.py` →
  `tests/unit/test_adapter.py` (or split per aspect under
  `tests/unit/adapter/`).

## 5. Docstrings

- One-line summary (imperative mood: "Parse", not "Parses").
- Followed by a paragraph only if the summary is insufficient.
- For public methods: `Args`, `Returns`, `Raises`, in that order,
  using Google style. `mypy` checks the types; the docstring
  documents intent.
- Protocol-adjacent constants cite their source in a comment:
  `# Confirmed via traffic capture (2026-03-28, tools/capture-mqtt.py).`
- No "TODO" comments without an issue number.

## 6. Logging

- One `_LOGGER = logging.getLogger(__name__)` per module.
- Levels:
  - `DEBUG` — wire traffic (adapter only), state transitions,
    reconnect attempts.
  - `INFO` — config-entry setup/unload, first push received, entry
    reauth, migration events.
  - `WARNING` — recoverable: validation failure, unexpected payload
    shape, CA fingerprint mismatch.
  - `ERROR` — unrecoverable within the current operation: command
    failure, unreachable cloud past retry budget.
  - No `CRITICAL` unless the event should page a human (HA's own
    concern).
- `%s` formatting only: `_LOGGER.debug("sent %s to %s", cmd, topic)`.
  No f-strings in log calls.
- `SEC-2`: no credential, token, device SN, MQTT payload, or REST
  body above DEBUG. A unit test greps captured output against a
  redaction regex.

## 7. Errors

- The integration raises only `ClientError` subclasses (from
  `exceptions.py`) from the adapter, and HA's `ConfigEntryAuthFailed`
  / `ConfigEntryError` / `UpdateFailed` from the coordinator.
- `karcher-home` native exceptions **do not leak** past the
  adapter. The adapter catches and translates.
- Entities never raise. An entity that cannot produce a value returns
  `None` and reports `available = False`.
- `except Exception` is forbidden except in two places:
  - `coordinator._async_update_data` translation layer (where
    unknown exceptions become `UpdateFailed`).
  - The adapter's `karcher-home` call sites (where unexpected
    exceptions become `ClientError` subclasses).
  Every such block logs the exception at ERROR and re-raises an
  appropriate typed exception.
- `contextlib.suppress` is forbidden. Catch explicitly.

## 8. Configuration and constants

- No `hass.data` access inside `adapter.py`.
- No env-var reads inside the integration package. HA is the
  configuration source of truth.
- `const.py` contains only HA-facing strings (domain, conf keys,
  platform names, translation keys). Wire constants live in
  `karcher-home` and are not re-exported.
- No magic numbers in entity code. A poll interval of 30 s is
  `POLL_INTERVAL_SECONDS = 30` in `const.py`.

## 9. Dependency discipline

- Direct imports only from:
  - standard library,
  - `homeassistant.*` (HA core),
  - `voluptuous` (HA's config-flow schema library),
  - `aiohttp` (for HA-side helpers),
  - `karcher` (only inside `adapter.py`).
- `requests`, `urllib3`, `pickle`, and `marshal` are banned anywhere.
- `paho.mqtt.*` is not imported directly; it is a transitive dep of
  `karcher-home` and is accessed only through the adapter's
  foreign-thread bridge.
- Every external dep has an upper bound in both `pyproject.toml` and
  `manifest.json requirements`.
- An import-graph CI test asserts:
  - Only `adapter.py` imports `karcher`.
  - `adapter.py` does not import `homeassistant.*` at runtime
    (`TYPE_CHECKING` annotations are fine).
  - Entity modules do not import `adapter.py` directly; they go
    through the coordinator.
  - `const.py` imports nothing except the standard library and
    `homeassistant.const`.

## 10. Git workflow

- Trunk-based with short-lived branches. `main` is always green.
- Commit messages: imperative mood, ≤ 72 char subject, wrapped body.
  Conventional Commits optional but not required.
- One logical change per commit. Squash only at merge if the PR has
  noisy fixup history; otherwise preserve the history.
- `pre-commit` hooks run `ruff format`, `ruff check`,
  `check_imports`, `check_docs`, and a secret scan (rejects the
  APK-known passwords `sc2021` and `hj2WtyHYYEvBTxDb`).
- Never `git push --force` to `main`.
- Never `commit --no-verify` unless the user explicitly asks.

## 11. Pull-request discipline

Template in `.github/PULL_REQUEST_TEMPLATE.md`:

- Linked issue / requirement IDs (`FR-*` etc.).
- Summary: what changed and why.
- Test plan (for entity or flow changes, include manual steps).
- Screenshots / logs for UI-visible or state-machine changes.
- Docs updates if applicable.
- HIL results **optional**: include if the author ran HIL; the
  release-tag DoD owns the HIL gate, not per-PR (see
  `spec/08-definition-of-done.md` §2 item 4).

Merge requires:

- All CI gates green (per `spec/06-test-strategy.md` §5 and the
  per-PR DoD `spec/08-definition-of-done.md` §1).
- `/review` skill output addressed in the PR body.
- No human review approval required. Single-maintainer project;
  `main` advances on the maintainer's authority alone. CODEOWNERS
  is documentation, not an enforced gate (see DoD §1 item 10 for
  the rationale).

## 12. Versioning and releases

- Semantic versioning: `MAJOR.MINOR.PATCH`.
- Breaking changes bump MAJOR and require an `async_migrate_entry`
  update (see FR-MG).
- Tag format: `v{version}`.
- Releases are cut by `.github/workflows/release.yml` on tag push;
  the workflow verifies `manifest.json` version matches the tag and
  publishes the packaged integration zip as a release asset.

## 13. Licensing

Project is licensed under MIT (see `LICENSE`). New source files
include an SPDX identifier comment at the top:
`# SPDX-License-Identifier: MIT`.

## 14. HACS and HA quality

- `manifest.json` declares `quality_scale` only at the tier we
  actually meet. Starts `bronze`; bumps to `silver` on the PR that
  ships FR-D-1 and all Silver-criteria tests.
- Integration type: `cloud_push` (`iot_class: cloud_push`).
- Translations: English is source; other locales are pulled in
  through the standard HA translation pipeline; `strings.json` never
  contains secret-bearing strings.
