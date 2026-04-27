# 05 — Security threat model

Context: the integration runs inside a Home Assistant instance on a
trusted home LAN, authenticating to the 3iRobotix cloud on behalf of
one Kärcher account and controlling one physical robot per config
entry. Credentials are supplied by the user through HA's UI. The
integration delegates wire-protocol work to `karcher-home`; the
security surface therefore has two layers: (a) the integration itself
and (b) the dependency.

Scope of this threat model:

- **In scope:** the integration package (`custom_components/karcher_home_robots/`),
  its handling of user-supplied and cloud-supplied data, its secrets,
  and the boundary between the integration and `karcher-home`.
- **Out of scope:** the internals of `karcher-home`, the 3iRobotix
  platform itself, and the Kärcher mobile app. Weaknesses of the
  platform are documented in `doc/INVESTIGATION.md` and carried into
  `SEC-*` only where the integration can mitigate them at its own
  boundary.

## 1. Trust boundaries

```
┌─────────────────────────────────────────────────────┐
│ Home Assistant host (trusted)                       │
│  ┌───────────────────────────────────────────────┐  │
│  │ karcher_home_robots (this integration)        │  │
│  │  ┌─────────────┐   ┌─────────────────────┐    │  │
│  │  │ entities +  │   │ adapter.py          │    │  │
│  │  │ coordinator │──▶│ (wraps python-      │────│──▶  karcher-home ──▶  3iRobotix cloud
│  │  └─────────────┘   │  karcher via       │    │  │                          (TLS-pinned)
│  │                     │  run_in_executor)  │    │  │
│  │                     └─────────────────────┘    │  │
│  └───────────────────────────────────────────────┘  │
│        ▲                                            │
│        │ user credentials (UI)                      │
└────────│────────────────────────────────────────────┘
         user
```

Boundaries:

- **B1:** User → HA UI (HA-managed, not the integration's concern).
- **B2:** HA → integration (via `ConfigEntry` data).
- **B3:** Integration → `karcher-home` (in-process, same trust level).
- **B4:** `karcher-home` → 3iRobotix cloud (REST + MQTT; TLS pinned
  by `karcher-home`).
- **B5:** 3iRobotix cloud → integration (inbound payloads; cross
  B4 then B3).

## 2. STRIDE per boundary

### B2: HA → integration

| Threat | Detail | Mitigation |
|---|---|---|
| **I**nformation disclosure | Credentials logged | `SEC-2`: no credential, token, SN, or MQTT payload above DEBUG. A unit test greps captured log output against a redaction regex |
| **T**ampering | Config entry edited to point at an attacker-controlled region/cloud | The integration validates `region` against a fixed allow-list (`EU`, `US`, `CN`) and rejects anything else. The region is immutable after setup (FR-RG-1). |

### B3: Integration ↔ `karcher-home`

Same process, same trust level. The risk is not adversarial but
integrity:

| Threat | Detail | Mitigation |
|---|---|---|
| Use of a compromised `karcher-home` release | Supply-chain attack on PyPI | Upper-bound pinning; dependabot with security advisories enabled; a release-time `pip-audit --strict` gate (`SEC-6`). Signed-tarball verification would be ideal but is not supported by PyPI-first projects today. |
| Stale version with known bug | Diverging from upstream fixes | Dependabot grouped patch bumps; HIL validation on bump before merge |
| Private-API access leaking outside the adapter | Contributor adds `_mqtt` usage in `coordinator.py` | `tests/tools/check_imports.py` enforces that `karcher` is imported only from `adapter.py`; `ruff TID` and a pygrep hook reinforce it |

### B4/B5: `karcher-home` ↔ 3iRobotix cloud

The integration does not make these wire-level decisions; `karcher-home`
does. The integration's obligation is to refuse to regress them:

| Threat | Detail | Mitigation |
|---|---|---|
| TLS downgrade via `tls_insecure_set(True)` | A contributor turns off verification to debug | `SEC-4`: forbidden anywhere; a pygrep hook and a ruff rule catch the string literal |
| Credential exfiltration in logs | Adapter logs raw payloads | Adapter redacts credential-shaped and token-shaped strings before logging; coordinator never receives raw wire frames |
| DoS by broker | Platform refuses connection or cycles | `karcher-home`'s reconnect backoff handles retries; the adapter wraps exhaustion as `TransientError`, coordinator sets entities unavailable, user sees `FR-OF` offline semantics |
| Malicious payload elevates control | An inbound MQTT payload exploits a parser | `karcher-home` performs the JSON parse; the adapter then validates the shape of each field before returning an integration-owned `DeviceProperties` DTO. Unknown-type or out-of-range values become `ValidationError`, logged and discarded |

### Internal to integration

| Threat | Detail | Mitigation |
|---|---|---|
| Insecure deserialisation | Trusted-looking JSON or pickle triggers unexpected behaviour | The integration does not use `pickle` anywhere; `pickle` import is banned. JSON handling is delegated to `karcher-home` or to the stdlib; no `eval`/`exec` anywhere |
| Dependency tampering | Supply-chain attack on any pinned dep | Upper-bound pinning (`SEC-6`), dependabot grouped PRs, SBOM generated on release |
| Log injection | Attacker-controlled strings land in logs | All log args use `%s` formatting, never `+` concatenation; log lines are single-line and never fed back into a parser |

## 3. Secrets and credential policy

| Secret | Where it lives | Policy |
|---|---|---|
| User email + password | HA config-entry storage (encrypted at rest) | Stored via `config_entries.async_update_entry`; never logged |
| REST auth token | Process memory only (owned by `karcher-home`) | Refreshed on `AuthError`; never persisted by the integration |
| MQTT username + password | Process memory only (owned by `karcher-home`) | Derived from REST login response |
| 3iRobotix CA cert | Bundled inside `karcher-home` | Snapshot fingerprint stored in `region_endpoint_snapshot`; rotations monitored by `tools/rotate-ca-cert.py` |
| `iot_dev.p12` mutual-TLS client cert | Bundled inside `karcher-home` | Shared global; documented as platform-level weakness; cannot be rotated without 3iRobotix cooperation |
| APK-derived passwords `sc2021`, `hj2WtyHYYEvBTxDb` | Research strings; referenced in `doc/` only | A pre-commit `forbidden-strings` hook rejects any commit that introduces either string into integration source |
| Research captures | `tests/fixtures/captures/*.jsonl` | Sanitised: SNs, tokens, device IDs replaced with synthetic equivalents. A CI grep rejects anything that matches the shape of a real value |

## 4. Reauth policy

- **Silent reauth on token expiry.** The integration persists the
  email and password in the config entry (encrypted at rest) and on
  token expiry retries `KarcherHomeProtocol.login()` automatically
  with bounded backoff (FR-A-8, FR-A-8a). The user is not prompted
  for a token-expiry event alone.
- **`AuthError` from `login()`:** distinguishes "credentials
  invalid" from "transient" (FR-A-8b). Credentials-invalid →
  `ConfigEntryAuthFailed` immediately; transient → contributes to
  the FR-A-8a backoff counter.
- **User-visible reauth flow** is triggered when (a) silent reauth
  exhausts its budget (3 attempts in 5 min) or (b) `login()`
  returns an unambiguous credentials-invalid error. Only the
  password is collected; region and `device_id` are preserved
  (FR-A-7, FR-A-11). The persisted password is updated on success.
- **Rate limiting during reauth:** vendor 429 / explicit throttle
  surfaces as `TransientError`, not `AuthError`. The user does not see
  a cryptic auth dialog for what is a vendor throttle. `Retry-After`
  is honoured up to a 60 s ceiling (FR-A-10).
- **Token lifetime:** unknown; `karcher-home` handles short-term
  refresh internally. On hard expiry, the silent-reauth path
  (FR-A-8) handles it before the user is notified.
- **Threat model implication of A.** Persisting the password
  enlarges the credential-at-rest blast radius beyond an active
  access token. Mitigation: HA's `config_entries` storage is
  encrypted at rest; the threat model assumes a host-compromise
  attacker already obtains the live access token from process
  memory. Persisting matches HA's standard cloud-integration
  pattern (Roborock, Mammotion-HA, Dreame).

## 5. CA-rotation graceful degradation (NFR-R-6)

If the broker's TLS cert no longer validates against the snapshot's
CA fingerprint:

1. The adapter surfaces `TransientError`; `karcher-home` does not
   silently fall back to `tls_insecure_set(True)` — that is forbidden.
2. The coordinator raises `UpdateFailed`; entities become unavailable.
3. The integration creates (or refreshes) a persistent HA `repair`
   issue with a translation key `ca_rotation_required`, telling the
   user (a) what happened, (b) that the integration is waiting for a
   release bump, and (c) that no user action is required beyond
   updating when the fix ships.
4. On every reconnect attempt, the adapter re-tries validation; the
   issue self-resolves on a successful reconnection.

The policy is deliberately user-visible rather than silently
degrading. Silent degradation is the pattern the old implementation
used (`tls_insecure_set(True)` in perpetuity); it is exactly what this
rewrite refuses to re-introduce.

## 6. Input validation policy

All inbound data is parsed through `karcher-home` into its native
objects, then translated by the adapter into integration-owned frozen
dataclasses before crossing the layer boundary. The coordinator and
entities never see a raw `dict` or a `karcher-home` object.

If a translation fails because a field is missing, out of range, or
the wrong type, the adapter raises `ValidationError`. This is logged
at DEBUG and does not propagate to HA. Repeated failures on the same
device elevate the log level to WARNING and increment a counter
surfaced in diagnostics.

## 7. Hardening checklist (merged into Phase 4, §09)

- CA cert pinning on MQTT and REST (via `karcher-home`).
- Mutual TLS on REST (via `karcher-home`).
- CA-fingerprint snapshot stored in config-entry data; rotation check
  runs on every reconnect (see §5).
- `ruff --select=S` (bandit ruleset) clean.
- `pip-audit --strict` gate in CI.
- SBOM (CycloneDX) generated on release tag.
- Dependabot enabled, grouped, with security advisories auto-prioritised.
- No `eval`, `exec`, or `pickle` anywhere in the integration.
- No synchronous HTTP library (`requests`, `urllib3`) imported outside
  `karcher-home`'s own dependency graph.
- `mypy --strict` clean as defence-in-depth against shape errors.

## 8. Data-flow diagram (DPIA support)

```
     Kärcher account (user)
           │
           ▼ email + password
   HA config flow ─▶ adapter (process memory) ─▶ karcher-home ─▶ 3iRobotix cloud
                                                                     │
                                                                     ▼
                                                                 RCV5 robot
```

The integration introduces no new data transfers relative to the
existing ecosystem. User data sent to 3iRobotix is identical to what
the Kärcher mobile app sends.
