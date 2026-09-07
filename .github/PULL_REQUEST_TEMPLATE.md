## What and why

<!-- One paragraph: what problem does this solve, and for whom? -->

## Changes

<!-- Bulleted list of behaviour changes; one line each. -->

## Checklist

- [ ] `make check` passes locally
- [ ] Tests added or updated for new behaviour
- [ ] `CHANGELOG.md` `[Unreleased]` has an entry
- [ ] No credentials, tokens, SNs, or payloads logged above DEBUG
- [ ] No blocking I/O outside `adapter.py`
- [ ] No `_`-prefixed third-party access outside `adapter.py`
- [ ] No `tls_insecure_set(True)`
- [ ] If `adapter.py` gained a **new private-symbol access**: allowlist in `check_imports.py` and `ARCHITECTURE.md` table updated
- [ ] If a model was added to `_model_profile.py`: README table regenerated with `python tests/tools/check_docs.py --fix-model-table`
- [ ] If config-entry schema changed: `async_migrate_entry` updated and tested
- [ ] If protocol-level finding: `doc/PROTOCOL.md` has a dated entry

## Deployment notes

<!-- Anything out of the ordinary: migrations, re-auth required, etc. Leave blank if none. -->
