# The `karcher-home` dependency — scope, risk, and fork triggers

The integration talks to the 3iRobotix cloud through one library:
[`karcher-home`](https://github.com/lafriks/python-karcher) by @lafriks, pinned
exactly at `0.5.1` (released October 2023). `adapter.py` is its only importer.

**It is not maintained on a release cadence.** Two bugs we work around —
the `net_stauts` typo and a malformed-JSON decode — are already fixed on
upstream `main` and have been unreleased since 2023.

**It is also not a blocker.** Since `_LenientProduct._missing_` landed, the
library's frozen `Product` enum no longer bottlenecks anything: an unrecognised
product ID mints a pseudo-member instead of raising, and adding a robot model is
a one-row edit in `_model_profile.py` that never touches the library. That is
the explicit **non**-trigger. What follows is what *would* force our hand.

Captured 2026-09-07 against the installed `karcher-home==0.5.1`.

---

## Fork or vendor when any one of these fires

**1. 3iRobotix rotates the REST server certificate.** Highest severity, and the
only trigger that breaks every user at once with no workaround above the
dependency. `consts.py:119` holds a hardcoded SHA-256 thumbprint, and
`karcher.py:137` passes it as `aiohttp.Fingerprint` on **every** REST request.
When the server cert changes, every call raises
`aiohttp.ServerFingerprintMismatch` and only a library release can fix it.

It used to present badly on top of that. `ServerFingerprintMismatch` inherits
from `aiohttp.ClientError`, not `OSError` and not `KarcherHomeException`, so it
matched none of `adapter.get_devices()`'s or `_login()`'s `except` clauses. It
escaped `async_setup_entry` entirely and Home Assistant recorded the entry as
`SETUP_ERROR` — which, unlike `SETUP_RETRY`, is never retried automatically. The
user got a stack trace and a dead entry.

`adapter._translate_aiohttp_error()` now maps it to `CertificatePinError`
(a `PermanentError`), so the failure reaches the integration card as
`ConfigEntryError` with a message naming the host and the cause. That improves
the diagnosis, not the outcome: the thumbprint is still inside the dependency,
so a rotation still needs a library release. The severity here is unchanged.

One place is deliberately left unmapped: `_fetch_map_data`. Its callers
(`get_rooms`, `get_map_snapshot`) re-raise `ClientError` and swallow everything
else to degrade to "no map yet". Mapping raw aiohttp errors there would convert
an ordinary blip during a map fetch into a raised error on a path that
currently absorbs it — a behaviour change, not a fix.

**2. Home Assistant ships a paho-mqtt the library cannot tolerate.** The
released `0.5.1` metadata requires `paho-mqtt` with **no upper bound**
(verified: `importlib.metadata.requires("karcher-home")`), and HA — not this
integration — decides which version is installed. `mqtt.py` uses v1-style
callbacks throughout. Upstream is *reported* to have declared incompatibility
with `paho-mqtt>=2.0` in a commit that landed after the `v0.5.1` tag; we have
not verified that commit, only that the released metadata is unpinned.

**3. More than two carried patches, or any one patch carried over 12 months.**
Each work-around is containment debt in `adapter.py`; past that point, owning
the code is cheaper than owning the patches.

**4. A work-around needs a *new* private symbol whose absence breaks setup**
rather than degrading one feature. Reaching further into internals to keep the
integration alive at all is the signal that the public surface has run out.

**5. An upstream `Product` or `Device` shape change that `_missing_` cannot
absorb.**

**6. A field report of `ValueError` from `DeviceStatus(v)`.** `Device.__init__`
coerces it eagerly inside the same unguarded list comprehension that used to
break accounts on unknown models, and its members are `0` and `1` only — so an
out-of-range status still fails discovery for every robot on the account. We did
not patch this the way we patched `Product`: a `DeviceStatus` pseudo-member
would be semantically empty, because `is_online()` compares against
`DeviceStatus.Online` and would silently read `False`. A real report changes the
calculus.

---

## What forking would cost

1765 lines across 13 modules. Roughly 1000–1250 of them are load-bearing for us.

| Area | Where | Rough size |
|---|---|---|
| AES-128-ECB crypto and request hashing | `utils.py:43-93` | ~50 lines |
| Auth, session, and request signing | `auth.py` + `karcher.py` `_request` / `login` / `logout` / `get_urls` | ~220 lines |
| MQTT client and message plumbing | `mqtt.py` + `karcher.py` `_mqtt_connect` / `_process_mqtt_message` / `_update_device_properties` | ~245 lines |
| Map fetch, decrypt, protobuf | `map.py`, `mapdata_pb2.py`, `get_map_data` | ~140 lines |
| Region/country endpoint table | `countries.py` | 289 lines, mechanical |

`cli.py` (194 lines) and `identifiers.py` (24) are dead to us — 12% of the
library we would simply not carry.

---

## TLS, stated accurately

The two claims this file exists to correct were both wrong in our own docs until
2026-09-07.

**The installed package contains no certificate files.** Not the 3iRobotix CA
cert, not `iot_dev.p12` — the wheel ships `.py` files and nothing else
(`find <site-packages>/karcher -type f ! -name '*.py'` returns nothing). Those
artefacts were extracted from the APK during the investigation; they live in
`INVESTIGATION.md`'s procedure, not in a dependency.

**REST is pinned by fingerprint, not by a CA.** `aiohttp.Fingerprint` compares
the server certificate's SHA-256 directly. It is stricter than a CA check — no
trust store is consulted at all — and it is brittle for exactly the same reason
(trigger 1).

**MQTT is not verified at all.** `mqtt.py:23-25`:

```python
# TODO validate certificate
self._client.tls_set(cert_reqs=ssl.CERT_NONE)
self._client.tls_insecure_set(True)
```

The connection is encrypted; the server is not authenticated. This project's own
hard rule forbids `tls_insecure_set(True)`, and our code honours it — `adapter.py`
sets no TLS options anywhere. But the adapter drives the library's MQTT client,
so the library's behaviour is ours in practice. It is disclosed in the README's
security section rather than quietly carried.

Fixing it means either a patch carried against the dependency or a fork — it is
not a trigger on its own today, but it is the most likely reason trigger 3 fires.
