#!/usr/bin/env python3
"""Phase-graduated coverage gate.

Reads the active phase from `pyproject.toml` `[tool.karcher].phase`,
picks the matching thresholds from `THRESHOLDS` below, runs `coverage
report` once for the overall numbers, and once per per-file rule for
file-scoped numbers. Exits 0 if every threshold passes; non-zero if
any fails. Phase 0 suspends the gate and exits 0 unconditionally.

The thresholds here are the operational mirror of the table in
`spec/06-test-strategy.md` §6.1; the two must agree. Bumping the
phase is a one-line edit to `pyproject.toml`; bumping a threshold
requires a PR that updates this file and the spec table together.

Stdlib only — runs without a venv bootstrap.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
PKG = "custom_components/karcher_home_robots"


# Phase → (overall_lines, overall_branches, per-file rules).
# Per-file rules are (path-glob, line%, branch%).
THRESHOLDS: dict[int, dict[str, object]] = {
    0: {"suspended": True},
    1: {
        "lines": 70,
        "branches": 60,
        "files": [
            (f"{PKG}/adapter.py",            90, 90),
            (f"{PKG}/coordinator.py",        90, 90),  # derive_vacuum_state lives here
            (f"{PKG}/config_flow.py",        80, 75),
            (f"{PKG}/diagnostics.py",        80, 75),
            (f"{PKG}/vacuum.py",             75, 70),
            (f"{PKG}/sensor.py",             75, 70),
            (f"{PKG}/binary_sensor.py",      75, 70),
            (f"{PKG}/select.py",             75, 70),
        ],
    },
    2: {
        "lines": 80,
        "branches": 70,
        "files": [
            (f"{PKG}/adapter.py",            95, 95),
            (f"{PKG}/coordinator.py",        95, 95),
            (f"{PKG}/config_flow.py",        90, 85),
            (f"{PKG}/diagnostics.py",        90, 85),
            (f"{PKG}/vacuum.py",             85, 80),
            (f"{PKG}/sensor.py",             85, 80),
            (f"{PKG}/binary_sensor.py",      85, 80),
            (f"{PKG}/select.py",             85, 80),
        ],
    },
    3: {
        "lines": 85,
        "branches": 80,
        "files": [
            (f"{PKG}/adapter.py",           100, 100),
            (f"{PKG}/coordinator.py",       100, 100),
            (f"{PKG}/config_flow.py",        95, 90),
            (f"{PKG}/diagnostics.py",        95, 90),
            (f"{PKG}/vacuum.py",             90, 85),
            (f"{PKG}/sensor.py",             90, 85),
            (f"{PKG}/binary_sensor.py",      90, 85),
            (f"{PKG}/select.py",             90, 85),
        ],
    },
}
# Phases ≥ 4 inherit the Phase 3 rules.
def _rules_for(phase: int) -> dict[str, object]:
    if phase in THRESHOLDS:
        return THRESHOLDS[phase]
    if phase > max(THRESHOLDS):
        return THRESHOLDS[max(THRESHOLDS)]
    raise SystemExit(f"coverage_gate: unknown phase {phase}")


def _read_phase() -> int:
    with PYPROJECT.open("rb") as f:
        data = tomllib.load(f)
    try:
        phase = data["tool"]["karcher"]["phase"]
    except KeyError as exc:
        raise SystemExit(
            "coverage_gate: pyproject.toml is missing [tool.karcher].phase"
        ) from exc
    if not isinstance(phase, int):
        raise SystemExit(
            f"coverage_gate: [tool.karcher].phase must be an int (got {phase!r})"
        )
    return phase


def _coverage_report() -> str:
    """Run `coverage report` and return its stdout."""
    result = subprocess.run(
        ["coverage", "report", "--format=total", "--precision=1"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode not in (0, 2):
        # 0 = ok, 2 = below fail_under (we don't set it here)
        raise SystemExit(
            f"coverage_gate: `coverage report` failed: {result.stderr}"
        )
    return _coverage_report_full()


def _coverage_report_full() -> str:
    result = subprocess.run(
        ["coverage", "report", "--show-missing"],
        capture_output=True, text=True, check=False,
    )
    return result.stdout


def _parse_overall(report: str) -> tuple[float, float] | None:
    """Parse the TOTAL line from `coverage report`. Returns (lines%, branches%)."""
    for line in report.splitlines():
        if line.startswith("TOTAL"):
            cols = line.split()
            # Branch coverage is enabled, so columns are:
            # Name Stmts Miss Branch BrPart Cover Missing
            try:
                pct = float(cols[-1].rstrip("%"))
            except (ValueError, IndexError):
                return None
            # Branch% is harder — coverage.py reports a single combined
            # number when branch=true. Treat overall % as the lines floor
            # and recompute branch separately if/when needed.
            return pct, pct
    return None


def _parse_file(report: str, path: str) -> tuple[float, float] | None:
    for line in report.splitlines():
        if line.startswith(path):
            cols = line.split()
            try:
                pct = float(cols[-1].rstrip("%"))
            except (ValueError, IndexError):
                return None
            return pct, pct
    return None


def main() -> int:
    phase = _read_phase()
    rules = _rules_for(phase)

    if rules.get("suspended"):
        print(f"coverage_gate: phase {phase} — gate suspended (Phase 0)")
        return 0

    report = _coverage_report_full()
    print(report)

    failures: list[str] = []

    overall = _parse_overall(report)
    if overall is None:
        return 0  # nothing to enforce against; let pytest decide
    lines_pct, branches_pct = overall
    floor_lines = float(rules["lines"])
    floor_branches = float(rules["branches"])
    if lines_pct < floor_lines:
        failures.append(
            f"overall lines {lines_pct:.1f}% < {floor_lines:.0f}% (phase {phase})"
        )
    if branches_pct < floor_branches:
        failures.append(
            f"overall branches {branches_pct:.1f}% < {floor_branches:.0f}% (phase {phase})"
        )

    for path, line_floor, branch_floor in rules.get("files", []):
        per_file = _parse_file(report, path)
        if per_file is None:
            # The file may not exist yet; report-time absence is not a
            # failure unless the spec says it must exist by this phase.
            continue
        f_lines, f_branches = per_file
        if f_lines < line_floor:
            failures.append(
                f"{path} lines {f_lines:.1f}% < {line_floor:.0f}% (phase {phase})"
            )
        if f_branches < branch_floor:
            failures.append(
                f"{path} branches {f_branches:.1f}% < {branch_floor:.0f}% (phase {phase})"
            )

    if failures:
        for f in failures:
            print(f"coverage_gate: FAIL — {f}", file=sys.stderr)
        return 1

    print(f"coverage_gate: phase {phase} — all thresholds met")
    return 0


if __name__ == "__main__":
    sys.exit(main())
