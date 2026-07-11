#!/usr/bin/env python3
"""Local dev-venv drift check.

Compares the currently active Python environment's installed package
versions against the constraints in pyproject.toml — [project.dependencies]
plus the `test` and `dev` optional-dependency groups (the set `make install`
/ `pip install -e '.[test,dev]'` installs). A long-lived local venv can drift
out of sync with a pin bump (e.g. a dependabot phcc bump) without anyone
noticing, since nothing re-installs it automatically; this catches that
before it produces a local test result that disagrees with CI.

Not a CI gate — CI always installs fresh from pyproject.toml, so it can't
drift. Local dev venvs only (see .claude/CLAUDE.md, "Python interpreter").

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


def main() -> int:
    problems = [p for req in _requirements() if (p := _check(req)) is not None]
    if problems:
        for p in problems:
            print(p, file=sys.stderr)
        print(
            f"\n{len(problems)} package(s) out of sync with pyproject.toml. "
            "Run: pip install -e '.[test,dev]' --upgrade",
            file=sys.stderr,
        )
        return 1
    print("Venv in sync with pyproject.toml.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
