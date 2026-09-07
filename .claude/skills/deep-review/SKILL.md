---
name: deep-review
description: Whole-codebase adversarial production-readiness review — reliability, security, edge cases, state invariants, test quality, and drift guards across the integration, the Lovelace card, and repo/CI hygiene. Not diff-scoped; complements /review. Manual invocation only.
---

# Deep review

Adversarial review of the **entire codebase at HEAD**, not a diff.

`/review` is the pre-PR diff pass and stops when `git diff main...HEAD` is
empty. This is the other thing: the pass that asks **if 500 strangers install
this from HACS tomorrow, what breaks, what leaks, and what silently gives them
wrong state?**

Do not run `git diff main...HEAD` and do not stop because the working tree is
clean. The target is the shipped state of `custom_components/karcher_home_robots/`
(Python + `www/` card), `tests/`, and the repo/CI hygiene around them.

Be adversarial. Assume the code is wrong until a specific line proves otherwise.
Assume the cloud lies, the network drops mid-command, the device returns a field
you have never seen, and the user has three robots on one account.

## Ground rules

- **Read-only.** No commit, no push, no auto-fix, no `scp`, no HA restart.
  Propose diffs inside the report; the user applies them.
- **Read the spec before judging.** `ARCHITECTURE.md`, `CLAUDE.md`,
  `.claude/CLAUDE.md`, `doc/PROTOCOL.md`, `doc/LIBRARY.md`, `CONTRIBUTING.md`.
  A finding that contradicts a documented, reasoned decision is only a finding
  if you cite **new evidence that the reasoning no longer holds**. Otherwise it
  is noise.
- **Label every claim: VERIFIED (quote the line) or INFERRED.** No confident
  guesses filling gaps — say "I could not determine X" instead.
- **Check the branch first** (`git branch --show-current`). If it is not `main`,
  some known-open item below may be mid-fix on this branch — assess what is
  actually there, do not report a fix in progress as an open defect.
- If you run anything:

  ```bash
  ~/.venvs/ha-dev/bin/python tests/tools/check_venv.py   # drift check FIRST
  ~/.venvs/ha-dev/bin/python -m pytest tests/ -q
  ~/.venvs/ha-dev/bin/python -m mypy --strict custom_components/karcher_home_robots
  ~/.venvs/ha-dev/bin/python -m ruff check custom_components/
  npm run check                                          # separate frontend toolchain
  ```

  `make` targets are broken. Local-vs-CI disagreement is a known drift mode, so
  run the venv check before trusting any local result.
- **Out of scope, and must not appear in the report:** firmware internals,
  protocol reverse-engineering findings, the unreported voice-pack injection.
  No credentials, serials, tokens, or research passwords in any report text.

## 1. Depth budget

Spend effort proportional to blast radius. Deep, line-by-line:

| File | Why |
|---|---|
| `adapter.py` | sole `karcher` importer; executor bridge; paho thread bridge; exception mapping |
| `coordinator.py` | all mutable state; push/poll reconciliation; the invariant hazard |
| `map_render.py` | numpy/Pillow in executor; untrusted device bytes |
| `map_parser.py` | parses cloud-controlled protobuf dicts |
| `www/card/card.js`, `map-draw.js`, `derive.js`, `card-gestures.js` | most stateful frontend |
| `_account_registry.py` | refcounted shared adapter — lifecycle bugs hit multi-entry users |

Sweep the rest (`switch.py`, `number.py`, `button.py`, `entity.py`, `const.py`, …)
for outright bugs only.

## 2. What to hunt

### Reliability and lifecycle

- Setup/unload/reload symmetry. Every task created has a cancel path and is
  awaited on unload. Every listener/subscription is removed. Reload twice in a
  row — what leaks?
- `_account_registry` refcounting: two config entries on one cloud account, one
  removed. Does the shared adapter survive? Does removing the *last* one
  actually tear down?
- Reconnect and outage: MQTT drops for 20 minutes, then returns. What state does
  the user see meanwhile, and is it *honest* (unavailable) or
  *stale-but-confident*?
- Re-auth: token expiry mid-command. Does it reauth, fail loudly, or hang?
- Startup ordering: first refresh fails; entities still created? `unique_id`
  stable across restarts?
- Concurrency: two commands in flight, push update arriving mid-optimistic-update.
  Find the interleaving that leaves state wrong until the next poll.

### The state-cluster hazard (highest yield)

`CLAUDE.md` names it: clusters of interacting mutable state whose invariants
live only in prose comments — path projection (`_path.py`), outage tracking
(`_outage.py`), resume intent, room names (`_room_names.py`), novel values
(`_novel_values.py`). For each cluster:

1. State the invariant **explicitly**, as an assertion over fields.
2. Find an input sequence (push order, poll race, restart, mid-clean reconnect)
   that violates it.
3. Say whether any existing test would catch that sequence.

### Edge cases and hostile input

- Every field read off the wire: missing, `None`, wrong type, out of range,
  negative, huge. Room count 0. Room count 200. Map grid dimensions of 0, or
  10000×10000 (memory blowup in the executor?). Unicode/RTL/emoji room names.
  Duplicate room ids.
- Unknown enum values — does the `_missing_` handling actually keep the entity
  alive?
- Timezone/DST, clock skew, counters that reset or run backwards (consumables,
  area, time).
- Division by zero, index-out-of-range, and unbounded growth in `map_render`,
  `map_parser`, and card `geometry.js`.

### Security posture

- Logging: prove no credential, token, SN, or MQTT payload escapes above DEBUG.
  Check exception messages and `repr()` paths too, not just explicit log calls.
- `diagnostics.py` redaction: what new field could be added tomorrow and get
  dumped unredacted? Is redaction allowlist- or denylist-shaped? (Denylist is a
  finding.)
- Card: any `innerHTML`/`unsafeHTML`/template injection from device-supplied
  strings (room names!). Any state written to the DOM without escaping.
- Repo/CI: the `.gitleaks.toml` allowlist went stale after the 2026-08-05 `doc/`
  redaction. CI installs ruff unpinned — green CI does not mean pre-commit hooks
  match.
- Dependency posture: `karcher-home` pinned in `manifest.json`; upper bounds
  elsewhere.

### Known-open items — assess severity, do not shallowly rediscover

- `aiohttp.ServerFingerprintMismatch` escaping `adapter.py`'s exception mapping
  unmapped (`doc/LIBRARY.md` trigger 1); the intended `SETUP_ERROR`/repair path.
  **Check whether this is still open on the current branch** before reporting
  it. If open: what does a user actually see today when the fingerprint rotates?
- `tls_insecure_set(True)` inside the pinned `karcher-home` MQTT — disclosed in
  the README, not fixed. Is the disclosure accurate and sufficient?

### Test-quality adversarial pass

Do not measure coverage; measure whether tests can *fail*.

- Find tests that would **survive a deliberate mutant**. Name the mutant and the
  line.
- Specifically hunt vacuous tests: any test that both assigns and asserts the
  same private attribute (`coord._x = ...; assert coord._x == ...`) tests
  nothing once a refactor moves the field. `CLAUDE.md` documents this exact trap.
- Which of the reliability scenarios above have **no** test at all?
- Frontend tests run under happy-dom — see the blind-spot rule below.

### Cross-surface drift (regression classes, not one-off bugs)

Ask for the **missing guard**, not just the current mismatch:

- Mode/suction/water values duplicated in `translations/*.json` and
  `www/card/i18n.js`, held together by a prose "keep in sync" comment. Where is
  the test?
- Card `VERSION` in `www/card/constants.js` must bump on any `www/` change; a
  shell test pins the string. Does anything actually *fail* if someone forgets?
- 7 languages across two independent surfaces — is any key missing in any locale?
- `manifest.json` `quality_scale` — is every requirement at that level genuinely
  met? Name any that is not.

### Architecture and HA patterns

- Layering: `adapter.py` the only `karcher` importer; private-API calls each
  carrying `# private-api:` and allowlisted in `check_imports.py`; no
  `homeassistant.*` at runtime in `adapter.py`; blocking I/O in the executor only
  there (plus the documented CPU-bound map exception). Does `check_imports.py`
  actually enforce what it claims, or can it be trivially evaded?
- Error taxonomy end to end: adapter raises `ClientError` subclasses; coordinator
  maps `AuthError` → `ConfigEntryAuthFailed`, `PermanentError` →
  `ConfigEntryError`, `TransientError` → `UpdateFailed`. Find the exception that
  reaches HA unmapped.
- No bare `except`. No swallowed `asyncio.CancelledError`. No fire-and-forget
  tasks.

## 3. Do NOT report these — deliberate and documented

These look like bugs to anyone optimising for HA-standard patterns. They are not.
The reasoning is in `CLAUDE.md`'s "must stay custom" table.

- `disabled_options` attribute on `KarcherCleaningModeSelect` — HA `SelectEntity`
  has no per-option disable; the card reads this.
- `_attr_options` stays static (all 3 modes always present) — HAMH snapshots
  `SupportedModes` once at startup; shrinking it would permanently hide modes in
  Apple Home.
- `VacuumEntityFeature.STATE` in `_attr_supported_features` — required for HAMH
  multi-room batching; removing it broke Apple Home (commit f4044cd).
- `app_segment_clean` via `async_send_command` — Roborock-compatible interface
  HAMH's Matter bridge expects.
- `room_map` / `map_image_size` / `map_legend` in `extra_state_attributes` —
  custom data for the card canvas; no HA standard exists.
- **Every model gets the full entity set.** Degraded-mode entity gating was
  evaluated and **cancelled**. "Why is there no capability gating?" is not a
  finding.

If you believe one of these is now wrong, you may say so — but only with new
evidence that the original reasoning no longer holds.

## 4. Declare your blind spots

The report must end with what you could **not** check. At minimum state your
coverage of: canvas paint, layout, `adoptStyles` and relative-import failures
(happy-dom does not cover these), hardware-only behaviour, real cloud/MQTT
behaviour, and anything skipped for budget. A review that silently omits these
reads more complete than it is.

## 5. Output format

```
## Deep review — karcher_home_robots @ <sha>

### Findings
  - <file>:<line> — <one-sentence defect>
    Severity: blocker | issue | nit
    Evidence: VERIFIED (quote) | INFERRED (reasoning)
    Failure scenario: <concrete inputs/state → wrong output, crash, or leak>
    Fix: <proposed diff or one-line direction>

### Invariants (state clusters)
  - <cluster> — invariant: <assertion>; violated by: <sequence> | holds

### Test gaps
  - <scenario with no test>
  - <vacuous/mutant-surviving test>: <file:line> — mutant that survives: <mutant>

### Missing guards (drift classes)
  - <duplication or convention with no automated enforcement>

### Not checked
  - <blind spots>

## Verdict
  <is this production-ready for strangers on HACS? 3 sentences, no hedging>
```

Severity rubric (same as `/review`):

- **blocker** — correctness bug, layering violation, security regression, data
  loss, or a crash a normal user will hit.
- **issue** — should fix; follow-up ticket acceptable with user agreement.
- **nit** — style or taste.

Rank findings most-severe first. An empty Findings section is an acceptable
answer if that is what the evidence supports — do not manufacture findings to
look thorough.
