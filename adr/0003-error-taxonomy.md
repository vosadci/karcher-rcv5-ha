# ADR-0003: Error taxonomy

Status: Accepted
Date: 2026-04-24

## Context

The prior integration catches `Exception` broadly at the coordinator
boundary and logs-and-swallows command errors. That's survivable but
lossy — auth failures and schema violations are indistinguishable from
transient network blips in the logs, which drives bad HA behaviour
(entities reported "available" despite auth failure; config flow
silent about reauth needs).

## Decision

All errors raised by the adapter and the coordinator are subclasses of
`ClientError` defined in `exceptions.py`. The hierarchy:

```
ClientError
├── AuthError              – login failed or token rejected
│   ├── InvalidCredentials – wrong password / user not found
│   ├── TokenRejected      – previously valid token now rejected
│   └── AccessDenied       – API says no for reasons other than auth
├── TransientError         – retryable
│   ├── NetworkError       – DNS, TCP, TLS, socket
│   ├── TimeoutError       – request/publish/reply timed out
│   ├── RateLimited        – HTTP 429 / explicit throttle
│   └── BrokerDisconnect   – MQTT layer surprise disconnect
├── PermanentError         – not retryable without operator action
│   ├── DeviceNotFound     – `device_id` absent from account
│   └── InvalidRegion      – region/tenant mismatch
├── ValidationError        – inbound payload fails schema
└── ProtocolError          – structurally valid but semantically unsupported
```

The adapter is responsible for mapping `karcher-home` exceptions and
raw HTTP/MQTT error shapes into this taxonomy before they leave the
adapter boundary. The coordinator is responsible for translating these
into HA exceptions:

| Integration exception  | HA exception              | Effect                                          |
|------------------------|---------------------------|-------------------------------------------------|
| `AuthError` (any)      | `ConfigEntryAuthFailed`   | Triggers reauth flow; entities unavailable      |
| `PermanentError` (any) | `ConfigEntryError`        | No retry; config entry surfaces error to user   |
| `TransientError` (any) | `UpdateFailed`            | Coordinator marks unavailable; schedules retry  |
| `ValidationError`      | — (logged at DEBUG)       | Treated as a missed update                      |
| `ProtocolError`        | — (logged at WARNING)     | Treated as a missed update                      |

`RateLimited` is a `TransientError` because HA's retry cadence is long
enough to absorb vendor throttles; the adapter should still honour any
`Retry-After` header by sleeping up to a bounded ceiling before
returning.

## Consequences

- Log levels are meaningful: WARNING means something that might need
  attention; DEBUG means noise.
- HA's diagnostic experience (config-entry state, repair flows) is
  driven by the correct exception for each cause.
- Tests can assert precise exception types; no catch-all `except
  Exception` hides regressions.
- Adding a new error case requires a subclass, not a string check.
- The adapter is the single place that has to know `karcher-home`'s
  native exception shapes.

## History

Previously numbered 0006 in an early draft; renumbered when the ADR
set was trimmed to four. No content change between drafts.
