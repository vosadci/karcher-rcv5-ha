#!/usr/bin/env python3
"""Local dev-venv drift check.

Compares the currently active Python environment's installed package
versions against the constraints in pyproject.toml — [project.dependencies]
plus the `test` and `dev` optional-dependency groups (the set `make install`
/ `pip install -e '.[test,dev]'` installs). A long-lived local venv can drift
out of sync with a pin bump (e.g. a dependabot phcc bump) without anyone
noticing, since nothing re-installs it automatically; this catches that
before it produces a local test result that disagrees with CI.

Also refuses a pre-release Home Assistant. `pytest-homeassistant-custom-component`
pins HA exactly, so the phcc version silently selects the HA release channel and
most phcc releases pin a beta. This integration ships to users on stable HA;
testing against a beta means green here while the real target is untested.
Dependabot cannot see the distinction, which is how pyproject.toml once came to
require `homeassistant==2026.9.0b0` (phcc 0.13.358, PR #143).

The drift half is local-only — CI installs fresh from pyproject.toml, so it
cannot drift (see .claude/CLAUDE.md, "Python interpreter"). The HA-channel half
is the reason this script also runs in CI: there, a beta-pinned phcc bump is
exactly what it catches.

Unlike the other tests/tools/check_*.py scripts, this one is not
stdlib-only (it imports `packaging`, a `dev` extra) — its entire job is to
inspect an already-installed dev venv, so that dependency is guaranteed
present by definition.

Exit status: 0 = in sync, 1 = one or more packages missing or out of range.
"""

from __future__ import annotations

import sys
import tomllib
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"

# The extras `make install` installs. `mutation` is deliberately excluded —
# it's on-request only (tests/README.md) and never expected to be present.
CHECKED_EXTRAS = ("test", "dev")


def _requirements() -> list[Requirement]:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    specs = list(project.get("dependencies", []))
    optional = project.get("optional-dependencies", {})
    for extra in CHECKED_EXTRAS:
        specs.extend(optional.get(extra, []))
    return [Requirement(spec) for spec in specs]


def _check(req: Requirement) -> str | None:
    try:
        installed = metadata.version(req.name)
    except metadata.PackageNotFoundError:
        return f"{req.name}: not installed (pyproject.toml requires {req.specifier or 'any'})"
    if req.specifier and not req.specifier.contains(installed, prereleases=True):
        return f"{req.name}: installed {installed} does not satisfy {req.specifier}"
    return None


def _check_ha_channel() -> str | None:
    """Reject a pre-release Home Assistant.

    HA is not one of our declared dependencies — phcc drags it in with an exact
    pin — so a missing install is not this check's business and passes quietly.
    """
    try:
        installed = metadata.version("homeassistant")
    except metadata.PackageNotFoundError:
        return None
    try:
        version = Version(installed)
    except InvalidVersion:
        return f"homeassistant: unparseable version {installed!r}"
    if not version.is_prerelease:
        return None
    return (
        f"homeassistant: {installed} is a PRE-RELEASE. This integration ships to users "
        "on stable HA and must never be tested against a beta. The HA version is chosen "
        "by the pytest-homeassistant-custom-component pin in pyproject.toml, not "
        "directly — move that pin to a phcc release whose HA is stable."
    )


def main() -> int:
    drift = [p for req in _requirements() if (p := _check(req)) is not None]
    channel = _check_ha_channel()

    for problem in (*drift, *(c for c in (channel,) if c is not None)):
        print(problem, file=sys.stderr)

    if drift:
        # Deliberately not printed for a channel problem: reinstalling is what
        # pulls the beta in, so telling the user to upgrade would loop them.
        print(
            f"\n{len(drift)} package(s) out of sync with pyproject.toml. "
            "Run: pip install -e '.[test,dev]' --upgrade",
            file=sys.stderr,
        )
    if channel is not None:
        print(
            "\nFix the pytest-homeassistant-custom-component pin in pyproject.toml, "
            "then reinstall. Do not reinstall first.",
            file=sys.stderr,
        )
    if drift or channel is not None:
        return 1
    print("Venv in sync with pyproject.toml.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
