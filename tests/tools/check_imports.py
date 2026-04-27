#!/usr/bin/env python3
"""Import-graph guard for the adapter boundary.

Enforces two rules via AST analysis (stdlib only):

Rule 1 — Adapter boundary
    Only `custom_components/karcher_home_robots/adapter.py` may import
    `karcher` (the PyPI distribution `karcher-home`). Every other module
    in the integration package that contains `import karcher` or
    `from karcher import …` is a violation.

Rule 2 — Private-API allowlist
    Inside adapter.py, every attribute access of the form
    `<expr>._<name>` is checked against ALLOWED_PRIVATE_API. If the
    name is not in the allowlist the access is a violation.
    A computed `getattr(obj, name)` call where `name` is not a string
    literal is unconditionally a violation — the checker cannot
    statically verify dynamic attribute names.

Adding a private symbol requires a single PR that updates
ALLOWED_PRIVATE_API here, the table in spec/03-constraints-and-deltas.md
§3.1, and the call site in adapter.py. See ADR-0001.

Exit status: 0 = clean, 1 = one or more violations.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "custom_components" / "karcher_home_robots"
ADAPTER = PKG / "adapter.py"

# Operational mirror of spec/03-constraints-and-deltas.md §3.1.
# Must agree with that table at all times.
ALLOWED_PRIVATE_API: frozenset[str] = frozenset(
    {
        "_mqtt",
        "_mqtt.on_message",
        "_update_device_properties",
        "_lib_publish",
        "_lib_wait_for_reply",
        "subscribe_device",
        "net_stauts",  # DeviceProperties typo path
    }
)


def _is_karcher_import(node: ast.stmt) -> bool:
    """Return True if the node imports from the `karcher` top-level package."""
    if isinstance(node, ast.Import):
        return any(
            alias.name == "karcher" or alias.name.startswith("karcher.") for alias in node.names
        )
    if isinstance(node, ast.ImportFrom):
        mod = node.module or ""
        return mod == "karcher" or mod.startswith("karcher.")
    return False


def _check_rule1(pkg: Path, adapter: Path) -> list[str]:
    """Rule 1: only adapter.py may import karcher."""
    violations: list[str] = []
    if not pkg.exists():
        return violations
    for py in pkg.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        if py.resolve() == adapter.resolve():
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except SyntaxError as exc:
            violations.append(f"{py}: syntax error: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.stmt) and _is_karcher_import(node):
                violations.append(
                    f"{py}:{node.lineno}: only adapter.py may import `karcher` "
                    f"(ADR-0001, spec/04-architecture.md §3)"
                )
    return violations


def _attr_chain(node: ast.expr) -> str | None:
    """Return the dotted attribute chain for `a.b.c`, or None if not resolvable."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attr_chain(node.value)
        if parent is None:
            return None
        return f"{parent}.{node.attr}"
    return None


def _check_rule2(adapter: Path, allowlist: frozenset[str]) -> list[str]:
    """Rule 2: private attribute accesses inside adapter.py must be allowlisted."""
    violations: list[str] = []
    if not adapter.exists():
        return violations
    try:
        tree = ast.parse(adapter.read_text(encoding="utf-8"), filename=str(adapter))
    except SyntaxError as exc:
        violations.append(f"{adapter}: syntax error: {exc}")
        return violations

    for node in ast.walk(tree):
        # Detect computed getattr(obj, name) where name is not a string literal.
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "getattr" and len(node.args) >= 2:
                name_arg = node.args[1]
                if not isinstance(name_arg, ast.Constant):
                    violations.append(
                        f"{adapter}:{node.lineno}: computed getattr() with "
                        f"non-literal name is forbidden in adapter.py "
                        f"(SEC-3, spec/03 §3)"
                    )
                    continue
                # Literal getattr — treat as an attribute access.
                name_val = str(name_arg.value)
                if name_val.startswith("_") and name_val not in allowlist:
                    violations.append(
                        f"{adapter}:{node.lineno}: getattr private symbol "
                        f"`{name_val}` not in ALLOWED_PRIVATE_API "
                        f"(spec/03-constraints-and-deltas.md §3.1)"
                    )
            continue

        # Detect dotted private-attribute access: expr._name or expr._a.b
        if isinstance(node, ast.Attribute):
            if not node.attr.startswith("_"):
                continue
            chain = _attr_chain(node)
            if chain is None:
                continue
            # Find the private-and-beyond portion of the chain.
            parts = chain.split(".")
            for i, part in enumerate(parts):
                if part.startswith("_"):
                    private_suffix = ".".join(parts[i:])
                    if private_suffix not in allowlist:
                        violations.append(
                            f"{adapter}:{node.lineno}: private attribute "
                            f"`{private_suffix}` not in ALLOWED_PRIVATE_API "
                            f"(spec/03-constraints-and-deltas.md §3.1)"
                        )
                    break

    return violations


def main() -> int:
    violations: list[str] = []
    violations.extend(_check_rule1(PKG, ADAPTER))
    violations.extend(_check_rule2(ADAPTER, ALLOWED_PRIVATE_API))
    if violations:
        for v in violations:
            print(v, file=sys.stderr)
        print(
            f"\n{len(violations)} import-graph violation(s). "
            "See spec/04-architecture.md §3 and ADR-0001.",
            file=sys.stderr,
        )
        return 1
    print("Import graph OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
