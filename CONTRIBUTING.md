# Contributing

Thanks for helping. This integration started as one person's RCV 5 and now runs
on hardware nobody here owns, so reports from your robot are the only way some
of it gets verified at all.

**Contents:** [Adding a robot model](#adding-a-robot-model) ·
[Support tiers](#support-tiers) · [Development setup](#development-setup) ·
[Tests](#tests) · [Docs and CHANGELOG](#docs-and-changelog) ·
[Opening the PR](#opening-the-pr) · [Dependencies](#dependencies)

---

## Adding a robot model

You do not need to write code to get a robot recognised. If you would rather
just report it, open an
[Add a robot model](https://github.com/vosadci/karcher-rcv5-ha/issues/new?template=add_model.yml) issue — the product
ID, the name printed on the robot, and "it works for me" is enough.

If you want to open the PR yourself, it is four steps and touches two files.

**1. Add one row to `PROFILES`** in
[`custom_components/karcher_home_robots/_model_profile.py`](custom_components/karcher_home_robots/_model_profile.py):

```python
ModelProfile(
    product_id="1946123509838999552",   # the real ID from diagnostics, as a decimal string
    member_name="RVM4_COMFORT",         # a valid Python identifier, unique in the table
    display_name="RVM 4 Comfort",       # Kärcher's spelling, shown in the device registry
    tier=SupportTier.COMMUNITY_VERIFIED,
    evidence="Community report of working control on this exact product ID.",
),
```

`evidence` is one line and ends up verbatim in the README table, so write it for
a stranger deciding whether to trust the entry.

Use the real product ID, not a placeholder — a conformance test reserves an
obviously-fake one as a sentinel and will fail loudly if a row claims it.

**2. Regenerate the README table** — do not hand-edit it:

```bash
python tests/tools/check_docs.py --fix-model-table
```

**3. Add one `CHANGELOG.md` line** under `[Unreleased]`, in the existing
`### Added` block. One sentence, user-visible effect only.

**4. Open the PR with "Allow edits by maintainers" ticked.** GitHub shows the
checkbox in the sidebar as you open it. Leave it unticked and the maintainer
cannot push a fixup to your branch, which means closing your PR and re-landing
the change by hand — that has already happened twice here (#135, #136), and it
costs you the attribution.

That is the whole change. If anything else needs an authored edit — a test file,
`adapter.py`, `const.py` — something has gone wrong; say so in the PR rather
than working around it.

### Where the product ID comes from

**Settings → Devices & Services → Kärcher Home Robots → ⋮ → Download
diagnostics.** The `device.product_id` field is the number. Diagnostics are safe
to attach: serial numbers, MAC addresses, email, tokens, and endpoint URLs are
redacted automatically, and `product_id` is deliberately kept because it is the
one field triage cannot proceed without.

---

## Support tiers

A tier says how much evidence we have. **It never gates functionality** — every
model gets the full entity set regardless. Tier drives the device-registry name,
a diagnostics field, one setup log line, and a Repairs prompt.

| Tier | What it takes |
|---|---|
| `MAINTAINER_VERIFIED` | The maintainer owns the robot and the HIL suite runs against it. |
| `COMMUNITY_VERIFIED` | Someone reported working control on that exact product ID. Their word is enough — record whose hardware in `evidence`. |
| `EXPECTED` | Kärcher's backend puts the model on a `productThingModelTemplateId` shared with a model in either verified tier (`doc/PROTOCOL.md` §16.5). |
| `UNCERTAIN` | No template evidence, or evidence of divergence. |

A product ID absent from the table is the fifth state and needs no row: the
robot still sets up, registers under its raw ID, and raises an INFO Repairs
notice asking for the ID.

Claim the *weakest* tier your evidence supports. `EXPECTED` in particular is a
claim about the vendor's schema, not about the robot working — if you have
actually used it, that is `COMMUNITY_VERIFIED` and it is a stronger claim.

Tiers are adjudicated once, by a person, into a row. Do not derive them at
runtime from the cloud catalog; `_model_profile.py`'s module docstring records
why.

---

## Development setup

```bash
python -m pip install -e '.[test,dev]'
pre-commit install
```

The `make` targets run `python3` by default. If the `python3` on your PATH is
not the environment you just installed into, pass your interpreter explicitly:

```bash
make check PY=/path/to/venv/bin/python
```

`make check` is `lint type test-cov coverage-gate import-graph` — the backend CI
gates. Run it before pushing.

### The Lovelace card

The card under `custom_components/karcher_home_robots/www/` has its **own**
toolchain — npm, vitest, eslint — separate from the Python environment, and its
own CI job. There is no build step; the card is served raw.

```bash
make front-install   # npm ci, once
make front           # eslint + vitest, mirrors CI
```

**Bump `VERSION` in `www/card/constants.js` on any change under `www/`.** The
card is registered as a versionless resource behind Home Assistant's service
worker, so an unbumped card gets served stale from cache and you will test the
old code without knowing. A shell test pins the string — update it in the same
commit.

### Hardware tests

`tests/hardware/` skips itself entirely unless `KARCHER_HIL=1` is set, so a
normal `make check` never touches a robot. Running it needs the maintainer's
credentials and hardware; you are not expected to.

---

## Tests

New behaviour needs a test. Two rules matter more than coverage here.

**Assert against an independent oracle.** A table-driven test that iterates
`PROFILES` and compares the result to `PROFILES` proves only that the table
equals itself — this repo has already shipped one such test. Valid oracles: the
merged `Product` enum, the full adapter path (`get_devices()` → `Device.model`),
the README file on disk, Python's own rules (`isidentifier()`, uniqueness), and
hardcoded literals whose duplication is deliberate and commented.

**Assert through the public surface.** A test that both sets and reads the same
private attribute keeps passing after the real field moves elsewhere — Python
lets you assign any attribute, so it silently starts testing a stray name. Go
through the coordinator's `data`, the entity state, or the issue registry
instead.

Both rules have the same check: deliberately break the code and confirm the test
fails. A test that passes either way is not protecting anything.

---

## Docs and CHANGELOG

`CHANGELOG.md` renders in HACS. It is user-facing, not a commit log: one terse
line per user-visible change, appended to the existing group under
`[Unreleased]`. Skip pure refactors, test-only changes, doc edits, and card
`VERSION` bumps — git history holds those.

`tests/tools/check_docs.py --strict` is a required CI job. It catches broken
relative links, a stale generated model table, an unindexed file in `doc/`, and
drift in any restatement of the minimum HA version.

Protocol-level findings go in `doc/PROTOCOL.md` with the exact command, the
payload, and the capture date.

---

## Opening the PR

- **Tick "Allow edits by maintainers."** See above; it is the single most
  useful thing you can do.
- Fill in the checklist in the PR template honestly. An unticked box with a
  sentence explaining why is fine; a ticked box that isn't true is not.
- Keep commits meaningful — the maintainer merges without squashing when the
  history says something, and a red→green pair proving a test bites is worth
  preserving.
- Do not bump `manifest.json`'s version or create a tag. Releases are cut by
  hand after a hardware pass.

Architecture and the layer rules live in
[ARCHITECTURE.md](ARCHITECTURE.md); the hard constraints and development
commands are in [CLAUDE.md](CLAUDE.md). Read `ARCHITECTURE.md` before changing
anything under `custom_components/`.

Security issues do **not** go in a public issue — see
[SECURITY.md](.github/SECURITY.md).

---

## Dependencies

`karcher-home` is pinned exactly (`==0.5.1`) in both `pyproject.toml` and
`manifest.json`; the two must stay in sync. Bumps arrive via dependabot and are
merged only after a hardware pass, because the library is the entire cloud
protocol and its released version is three years old.

`pytest-homeassistant-custom-component` pins Home Assistant with `==`, so **the
phcc version silently chooses the HA channel.** Check every phcc bump by hand:
`python tests/tools/check_venv.py` refuses a pre-release HA, and if it reports
one, fix the pin rather than reinstalling.

What would make us fork or vendor `karcher-home`, and what it would cost, is
written down in [doc/LIBRARY.md](doc/LIBRARY.md). Adding a robot model is an
explicit **non**-trigger: it never needs a library change.
