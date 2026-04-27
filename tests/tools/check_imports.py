#!/usr/bin/env python3
"""Import-graph guard for the adapter boundary.

NOTE: This file currently still encodes the obsolete `cloud/`-package
shape that pre-dates the architectural pivot to a single
`adapter.py`. It vacuously passes today because no `cloud/` package
exists. It is scheduled for full rewrite in P0-7
(`spec/09-roadmap-and-backlog.md` Phase 0). The rewritten checker
must enforce two rules:

1. **Adapter boundary.** Only
   `custom_components/karcher_home_robots/adapter.py` may import
   `karcher` (the PyPI distribution `karcher-home`). Every other module
   in the integration package is forbidden from importing it directly
   or transitively via re-exports.

2. **Private-API allowlist.** Inside `adapter.py`, every `_`-prefixed
   attribute access against a `karcher` symbol must match an entry in
   the `ALLOWED_PRIVATE_API` constant declared in this checker. The
   constant is the operational mirror of the table in
   `spec/03-constraints-and-deltas.md` §3.1; the two must agree.
   Computed `getattr(obj, name)` calls with non-literal names are
   rejected outright. Adding a private symbol requires a single PR
   that updates this constant, the spec table, and the call site.

The historical text below is preserved for reference until the
rewrite lands; the code below it is kept passing-green so the CI
gate stays wired but is currently a no-op.

Rules (legacy, retained until P0-7 rewrites this file):

1. `custom_components/karcher_home_robots/cloud/**` must not import
   from `homeassistant.*`. The cloud client is HA-agnostic.
2. `custom_components/karcher_home_robots/**` (outside `cloud/`) must
   import only the public façade symbols from `cloud`, never internal
   modules.

   Public façade = symbols re-exported by
   `custom_components.karcher_home_robots.cloud.__init__`. Anything
   that resolves through a sub-module path
   (`cloud.rest.something`, `cloud.mqtt.Client`, etc.) is a violation.

3. Tests are exempt — they may reach internals for unit testing.

Exit status:
    0 — clean
    1 — one or more violations (printed to stderr)

The script is intentionally dependency-free (stdlib `ast` only) so it
works in pre-commit hooks and CI without a venv bootstrap.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "custom_components" / "karcher_home_robots"
CLOUD = PKG / "cloud"

PUBLIC_CLOUD_SUBMODULES: frozenset[str] = frozenset(
    # Anything else under cloud.* is internal and off-limits to the
    # integration package. `exceptions` is public because HA code needs
    # to catch typed errors.
    {"exceptions"}
)


def _iter_py(root: Path) -> Iterator[Path]:
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        yield p


def _violations_cloud_no_ha() -> list[str]:
    out: list[str] = []
    if not CLOUD.exists():
        return out
    for path in _iter_py(CLOUD):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            out.append(f"{path}: syntax error: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "homeassistant" or alias.name.startswith("homeassistant."):
                        out.append(
                            f"{path}:{node.lineno}: cloud/ must not import `{alias.name}` "
                            f"(ADR-0002, spec/04-architecture.md §3)"
                        )
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == "homeassistant" or mod.startswith("homeassistant."):
                    out.append(
                        f"{path}:{node.lineno}: cloud/ must not import from `{mod}` "
                        f"(ADR-0002, spec/04-architecture.md §3)"
                    )
    return out


def _violations_integration_uses_only_facade() -> list[str]:
    out: list[str] = []
    if not PKG.exists():
        return out
    for path in _iter_py(PKG):
        # Skip cloud/ itself; it owns its internals.
        try:
            rel = path.relative_to(CLOUD)
            _ = rel
            continue
        except ValueError:
            pass
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            out.append(f"{path}: syntax error: {exc}")
            continue
        for node in ast.walk(tree):
            mod = ""
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    _check_module(path, node.lineno, alias.name, out)
                continue
            else:
                continue
            _check_module(path, node.lineno, mod, out)
    return out


def _check_module(path: Path, lineno: int, mod: str, out: list[str]) -> None:
    # Only interested in our own cloud package.
    prefix = "custom_components.karcher_home_robots.cloud"
    # Accept relative imports once they're normalised: we don't try to
    # resolve them; we just look at absolute dotted names. Relative
    # imports (`from .cloud import X`) can still be caught if authors
    # write absolute imports (which is the project convention).
    if mod == prefix or mod.startswith(prefix + "."):
        tail = mod[len(prefix):].lstrip(".")
        if not tail:
            return  # importing the package itself is fine
        top = tail.split(".", 1)[0]
        if top not in PUBLIC_CLOUD_SUBMODULES:
            out.append(
                f"{path}:{lineno}: integration code imports internal cloud module `{mod}`; "
                f"use the public façade (`from .cloud import ...`) "
                f"(spec/04-architecture.md §3)"
            )


def main() -> int:
    violations: list[str] = []
    violations.extend(_violations_cloud_no_ha())
    violations.extend(_violations_integration_uses_only_facade())
    if violations:
        for v in violations:
            print(v, file=sys.stderr)
        print(
            f"\n{len(violations)} import-graph violation(s). "
            "See spec/04-architecture.md §3 and ADR-0002.",
            file=sys.stderr,
        )
        return 1
    print("Import graph OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
