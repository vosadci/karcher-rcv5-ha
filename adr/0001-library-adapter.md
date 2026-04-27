# ADR-0001: Library-adapter — wrap `karcher-home`, do not rewrite

Status: Accepted
Date: 2026-04-24

## Context

The prior implementation of `karcher_home_robots` used the
`karcher-home` library for all vendor-cloud interaction: REST auth,
device enumeration, MQTT subscribe, and property decoding. The original
rewrite plan proposed replacing it with an in-tree `cloud/` package so
that the integration owned the entire wire protocol end-to-end.

> **Three names, one library.** The PyPI distribution is
> [`karcher-home`](https://pypi.org/project/karcher-home/), the Python
> import is `karcher`, and the upstream GitHub repository is
> [`lafriks/python-karcher`](https://github.com/lafriks/python-karcher).
> All references in this spec set use `karcher-home` (PyPI) and
> `karcher` (import); `python-karcher` is reserved for the GitHub
> project. Latest release at adoption time: `0.5.1` (2023-10-03).

On closer inspection the replace-it plan is not justified:

- `karcher-home` is already the definitive implementation of the
  3iRobotix wire format. It is the product of the same reverse-engineering
  effort that sits in `doc/PROTOCOL.md`. Re-deriving it in-tree doubles
  the surface area the rewrite has to maintain without making the
  integration behave differently from the user's perspective.
- The library's *flaws* are narrow and known: two upstream bugs
  (documented in `03-constraints-and-deltas.md`) require targeted
  work-arounds; it is synchronous and must be called through an
  executor; paho-mqtt delivers messages on a foreign thread. None of
  these are structural problems — they are adapter responsibilities.
- The only previously-cited technical reason to replace the library was
  "no `_`-prefixed access". That is a style rule the rewrite is
  deliberately relaxing: private-API access to a library the integration
  vendors is a tractable risk, unlike the protocol work a rewrite would
  have to carry permanently.

## Options considered

1. **In-tree cloud client.** Reimplement REST + MQTT + codec in
   `custom_components/.../cloud/`. Zero runtime dependency on
   `karcher-home`.
2. **Fork `karcher-home`.** Keep the external dependency shape but own
   the fork. No functional win, highest maintenance cost.
3. **Library-adapter (chosen).** Keep `karcher-home` as a pinned
   dependency. Wrap it behind a single adapter module that absorbs the
   blocking/foreign-thread and work-around concerns. Everything above
   the adapter sees an async, typed, loop-friendly surface.

## Decision

**Wrap, do not rewrite.** The integration depends on `karcher-home`
with an explicit upper bound in `pyproject.toml` and accesses it only
through a thin adapter layer.

The adapter has three jobs:

1. **Async boundary.** Every `karcher-home` call happens in a thread
   pool via `hass.async_add_executor_job`. No synchronous vendor call
   reaches the event loop.
2. **Foreign-thread bridge.** paho-mqtt invokes callbacks on its network
   thread. The adapter re-enters the event loop exclusively through
   `loop.call_soon_threadsafe`; coordinator state is never mutated from
   the mqtt thread.
3. **Workaround containment.** The `net_stauts` typo and the
   stale-`get_device_properties` behaviour are patched at the adapter,
   not elsewhere. The integration proper never sees them.

Private attribute access on `karcher-home` (e.g. `_mqtt`,
`_update_device_properties`) is explicitly permitted **inside the
adapter** and nowhere else. CI enforces that no other module imports
private symbols from third-party packages.

## Consequences

**Positive**

- Dramatically less code to maintain. The rewrite's novelty stays
  concentrated in HA integration work (coordinator, entities, error
  mapping, diagnostics) rather than reimplementing a wire protocol.
- Upstream fixes and protocol updates land via a `karcher-home`
  version bump, not an integration PR.
- The adapter doubles as the stable contract that unit tests target;
  the rest of the integration can be tested against a fake adapter
  without touching paho-mqtt.
- No new maintenance burden for certs, codec evolution, or MQTT client
  semantics.

**Negative**

- The integration inherits `karcher-home`'s release cadence and
  any latent bugs. Upstream has been dormant since `0.5.1`
  (2023-10-03). Mitigation: pin exact, dependabot-watch for
  releases. The fork/vendor contingency is **explicitly accepted
  as risk, not pre-designed**: until 3iRobotix actually changes the
  wire format or PyPI removes the package, building a fork is
  premature. If/when a trigger fires, the response is decided then,
  not now. Hidden cost of writing a contingency ADR before it's
  needed is anti-YAGNI; the integration ships against the version
  that the prior implementation has already validated end-to-end.
- A pinned set of seven private-API usages exists, enumerated in
  `spec/03-constraints-and-deltas.md` §3.1. Mitigation: the
  allowlist is a normative table; an `ALLOWED_PRIVATE_API` constant
  in `tests/tools/check_imports.py` mirrors it and is enforced via
  AST scan (P0-7). Adding a symbol takes a three-file PR.
- `karcher-home` ships no `py.typed`; mypy resolves it as `Any`.
  Mitigation: the adapter declares the upstream surface as
  `KarcherHomeProtocol` / `DevicePropertiesProtocol` in `_types.py`
  and applies `cast(...)` once at construction. After the cast,
  `mypy --strict` checks the adapter against the Protocols
  (`spec/04-architecture.md` §4.1.1, `spec/07-coding-standards.md`
  §1). No vendored `.pyi` stubs.
- Blocking work runs in the default executor. Mitigation: adapter calls
  are short (<100 ms typical); long-running operations are not
  introduced.

## Enforcement

- `pyproject.toml` declares `karcher-home==0.5.1` (exact pin per
  `spec/03-constraints-and-deltas.md` §3 and `CONTRIBUTING.md`
  Dependencies).
- `tests/tools/check_imports.py` ensures only
  `custom_components/karcher_home_robots/adapter.py` imports
  `karcher`; every other module sees an integration-owned
  surface.
- Any PR that touches the adapter identifies which `karcher-home`
  version it is validated against in the PR body.

## Supersedes

None. (Originally drafted as "In-tree cloud client"; superseded before
any implementation, hence replaced in place.)
