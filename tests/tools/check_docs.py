#!/usr/bin/env python3
"""Documentation freshness and consistency checker.

Runs a set of deterministic drift checks across the docs and
configuration:

1. Broken relative markdown links in any `.md` across the repo.
2. `WAIVERS.md` (repo root) entries with a date-form expiry in the
   past are reported. The file is created on demand when the first
   waiver lands; absence is not a problem.
3. Required structural markers: `README.md` top heading, `CHANGELOG.md`
   `[Unreleased]` block, `CLAUDE.md` skills section.
4. Version consistency: `hacs.json` `homeassistant` agrees with
   `manifest.json` (when present), with every prose restatement of the
   minimum HA version (README badge and Requirements line,
   `ARCHITECTURE.md`, `doc/CONSTRAINTS.md` — see `HA_VERSION_SITES`),
   and appears in the CI workflow's HA matrix.
5. `doc/` index completeness: every file in `doc/` is listed in
   `doc/README.md`.
6. Supported-models table: the generated region in `README.md` matches
   what `_model_profile.PROFILES` renders. `--fix-model-table` rewrites
   the region in place, so adding a robot model stays a one-file edit.

The earlier spec/ADR traceability checks (requirement-ID, ADR-chain,
and backlog references) were dropped when the `spec/` set and `adr/`
apparatus were consolidated into `ARCHITECTURE.md`; per CHANGELOG.md,
traceability is a convention, not a CI gate.

Stdlib only — including the model-profile module it loads by path, which is
why that module may not import Home Assistant, `karcher`, or even a sibling
via a relative import (this script runs in CI with no `pip install`).

Exit 0 on clean, 1 on any issue.

Soft checks (warnings) are printed but do not fail the build unless
`--strict` is given.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

LINK_RE = re.compile(r"(?<!\!)\[([^\]]+)\]\(([^)]+)\)")

# Every place the minimum HA version is restated in prose or badges, with a
# regex capturing it. `hacs.json` is the source of truth and these must agree.
# Kept explicit rather than "grep for a version-shaped string" so that adding a
# new restatement is a deliberate act: an unlisted site drifts unnoticed, which
# is exactly how these four fell a release behind the version actually tested.
HA_VERSION_SITES: tuple[tuple[str, str], ...] = (
    ("README.md", r"img\.shields\.io/badge/HA-([^%\s]+)%2B-"),
    ("README.md", r"^- \*\*Home Assistant\*\* (\S+) or newer$"),
    ("ARCHITECTURE.md", r"^- Minimum HA version: (\S+)$"),
    ("doc/CONSTRAINTS.md", r"^\| Minimum HA version: ([^\s|]+) \|"),
)


# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------


def _iter_md(root: Path) -> Iterator[Path]:
    for p in root.rglob("*.md"):
        if any(seg in p.parts for seg in ("__pycache__", ".git", "node_modules")):
            continue
        yield p


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# -----------------------------------------------------------------------------
# Checks
# -----------------------------------------------------------------------------


def check_links(errors: list[str]) -> None:
    """1. Every relative link resolves."""
    for md in _iter_md(ROOT):
        text = _read(md)
        for m in LINK_RE.finditer(text):
            target = m.group(2).strip()
            # Ignore external, anchors, protocol-qualified, and empty.
            if not target or target.startswith("#"):
                continue
            if target.startswith(("http://", "https://", "mailto:", "computer://", "tel:")):
                continue
            # Strip anchor and query.
            path_part = target.split("#", 1)[0].split("?", 1)[0]
            if not path_part:
                continue
            resolved = (md.parent / path_part).resolve()
            if not resolved.exists():
                errors.append(f"{md.relative_to(ROOT)}: broken link -> {target}")


def check_waivers(errors: list[str], warnings: list[str]) -> None:
    """2. Open waivers with a past ISO-date expiry."""
    waivers = ROOT / "WAIVERS.md"
    if not waivers.exists():
        return
    text = _read(waivers)
    # Only consider the `## Open` section up to `## Closed`.
    open_section_re = re.compile(r"##\s+Open\s*(.+?)##\s+Closed", re.DOTALL)
    m = open_section_re.search(text)
    if not m:
        return
    body = m.group(1)
    entry_re = re.compile(r"###\s+W-(\d{4})\s+—\s+(.+)")
    expiry_re = re.compile(r"\*\*Expiry:\*\*\s+(\d{4}-\d{2}-\d{2})")
    today = dt.date.today()
    for entry in re.split(r"(?=^###\s+W-)", body, flags=re.MULTILINE):
        em = entry_re.search(entry)
        if not em:
            continue
        wid = em.group(1)
        xm = expiry_re.search(entry)
        if not xm:
            warnings.append(f"WAIVERS.md: W-{wid} has no parseable expiry date")
            continue
        try:
            expiry = dt.date.fromisoformat(xm.group(1))
        except ValueError:
            warnings.append(f"WAIVERS.md: W-{wid} has malformed expiry `{xm.group(1)}`")
            continue
        if expiry < today:
            errors.append(
                f"WAIVERS.md: W-{wid} expired on {expiry.isoformat()}; "
                f"close it or extend the expiry"
            )


def check_required_structure(errors: list[str]) -> None:
    """3. Required markers are present in key docs."""
    readme = ROOT / "README.md"
    changelog = ROOT / "CHANGELOG.md"
    claude_md = ROOT / "CLAUDE.md"

    if readme.exists():
        text = _read(readme)
        if not re.search(r"^#\s+", text, re.MULTILINE):
            errors.append("README.md: missing top-level heading")
    else:
        errors.append("README.md: missing")

    if changelog.exists():
        text = _read(changelog)
        if "[Unreleased]" not in text:
            errors.append("CHANGELOG.md: missing `[Unreleased]` block")
    else:
        errors.append("CHANGELOG.md: missing")

    if claude_md.exists():
        text = _read(claude_md)
        if "## Skills" not in text:
            errors.append("CLAUDE.md: missing `## Skills` section")
    else:
        errors.append("CLAUDE.md: missing")


def _extract_ci_ha_matrix() -> list[str]:
    """Crude-but-stdlib extraction of the `ha:` matrix from the CI workflow."""
    wf = ROOT / ".github" / "workflows" / "ci.yml"
    if not wf.exists():
        return []
    text = _read(wf)
    m = re.search(r"^\s*ha:\s*\[(.+?)\]\s*$", text, re.MULTILINE)
    if not m:
        return []
    raw = m.group(1)
    return [v.strip().strip('"').strip("'") for v in raw.split(",") if v.strip()]


def check_versions(errors: list[str], warnings: list[str]) -> None:
    """4. hacs.json agrees with manifest.json and with the CI HA matrix."""
    hacs_path = ROOT / "hacs.json"
    manifest_path = ROOT / "custom_components" / "karcher_home_robots" / "manifest.json"

    hacs_ha: str | None = None
    if hacs_path.exists():
        try:
            hacs = json.loads(_read(hacs_path))
            hacs_ha = hacs.get("homeassistant")
        except json.JSONDecodeError as exc:
            errors.append(f"hacs.json: malformed JSON ({exc})")
            return

    manifest_ha: str | None = None
    if manifest_path.exists():
        try:
            manifest = json.loads(_read(manifest_path))
            # HA manifests use `homeassistant` for min version (string).
            manifest_ha = manifest.get("homeassistant")
        except json.JSONDecodeError as exc:
            errors.append(f"manifest.json: malformed JSON ({exc})")
            return

    if hacs_ha and manifest_ha and hacs_ha != manifest_ha:
        errors.append(
            f"version drift: hacs.json homeassistant={hacs_ha!r} "
            f"!= manifest.json homeassistant={manifest_ha!r}"
        )

    check_ha_version_sites(hacs_ha, errors)

    ci_matrix = _extract_ci_ha_matrix()
    if hacs_ha and ci_matrix and hacs_ha not in ci_matrix and "latest" not in ci_matrix:
        errors.append(
            f"CI HA matrix {ci_matrix} does not include "
            f"minimum HA version {hacs_ha!r} from hacs.json"
        )
    if hacs_ha and ci_matrix and hacs_ha not in ci_matrix:
        # `latest` alone covers the top but not the floor.
        warnings.append(
            f"CI HA matrix covers `latest` but not the floor {hacs_ha!r}; "
            f"consider pinning one job to the minimum"
        )


def check_ha_version_sites(hacs_ha: str | None, errors: list[str], root: Path = ROOT) -> None:
    """Every prose restatement of the minimum HA version matches hacs.json.

    A missing anchor is an error, not a silent pass: deleting the line must not
    become a way to dodge the check.
    """
    if not hacs_ha:
        return
    for rel, pattern in HA_VERSION_SITES:
        path = root / rel
        if not path.exists():
            errors.append(f"{rel}: missing, but it declares the minimum HA version")
            continue
        match = re.search(pattern, _read(path), re.MULTILINE)
        if match is None:
            errors.append(
                f"{rel}: no minimum-HA-version line matching {pattern!r}; "
                f"if the wording changed, update HA_VERSION_SITES in check_docs.py"
            )
            continue
        if match.group(1) != hacs_ha:
            errors.append(
                f"version drift: {rel} says minimum HA {match.group(1)!r} "
                f"but hacs.json says {hacs_ha!r}"
            )


def check_doc_index(errors: list[str]) -> None:
    """5. Every file in doc/ is listed in doc/README.md's index."""
    doc_dir = ROOT / "doc"
    index = doc_dir / "README.md"
    if not index.exists():
        return
    text = _read(index)
    for entry in sorted(doc_dir.iterdir()):
        if not entry.is_file() or entry.name == "README.md":
            continue
        if entry.suffix not in (".md", ".yaml", ".yml"):
            continue
        if entry.name not in text:
            errors.append(f"doc/README.md: {entry.name} is not listed in the index")


MODEL_PROFILE_PATH = ROOT / "custom_components" / "karcher_home_robots" / "_model_profile.py"


def _load_model_profile(path: Path = MODEL_PROFILE_PATH) -> Any:
    """Import _model_profile.py by path, without importing the package.

    Importing it as `custom_components.karcher_home_robots._model_profile` would
    execute the package `__init__.py` and pull in Home Assistant, which is not
    installed for this job. Registering the module in sys.modules is required,
    not cosmetic: @dataclass resolves its string annotations through
    sys.modules[cls.__module__] and raises AttributeError without it.
    """
    spec = importlib.util.spec_from_file_location("_karcher_model_profile", path)
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable in-repo
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _readme_model_region(text: str, begin: str, end: str) -> tuple[int, int] | None:
    """Span of the generated region in README.md, or None if absent."""
    start = text.find(begin)
    stop = text.find(end)
    if start == -1 or stop == -1 or stop < start:
        return None
    return start, stop + len(end)


def check_model_table(errors: list[str], root: Path = ROOT) -> None:
    """6. README's generated supported-models region matches PROFILES.

    Prints the entire paste-ready block on mismatch, so a contributor who has
    not run --fix-model-table can still finish the job from the CI log.
    """
    profile = _load_model_profile()
    readme = root / "README.md"
    if not readme.exists():
        errors.append("README.md: missing, but it holds the generated model table")
        return

    text = _read(readme)
    span = _readme_model_region(text, profile.README_BEGIN, profile.README_END)
    if span is None:
        errors.append(
            f"README.md: no generated region delimited by {profile.README_BEGIN} / "
            f"{profile.README_END}. Run: python tests/tools/check_docs.py --fix-model-table"
        )
        return

    expected = profile.render_readme_block()
    actual = text[span[0] : span[1]]
    if actual != expected:
        errors.append(
            "README.md: the supported-models table is out of date with "
            "_model_profile.PROFILES. Run:\n"
            "  python tests/tools/check_docs.py --fix-model-table\n"
            "Expected region:\n" + expected
        )


def fix_model_table(root: Path = ROOT) -> int:
    """Rewrite README.md's generated region from PROFILES. Returns 0 on success."""
    profile = _load_model_profile()
    readme = root / "README.md"
    text = _read(readme)
    span = _readme_model_region(text, profile.README_BEGIN, profile.README_END)
    if span is None:
        print(
            f"error: README.md has no region delimited by {profile.README_BEGIN} / "
            f"{profile.README_END}; add the markers first.",
            file=sys.stderr,
        )
        return 1

    updated = text[: span[0]] + profile.render_readme_block() + text[span[1] :]
    if updated == text:
        print("README.md model table already up to date.")
        return 0
    readme.write_text(updated, encoding="utf-8")
    print("README.md model table rewritten from _model_profile.PROFILES.")
    return 0


# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors.",
    )
    parser.add_argument(
        "--fix-model-table",
        action="store_true",
        help="Rewrite README.md's generated supported-models region from PROFILES.",
    )
    args = parser.parse_args()

    if args.fix_model_table:
        return fix_model_table()

    errors: list[str] = []
    warnings: list[str] = []

    check_links(errors)
    check_waivers(errors, warnings)
    check_required_structure(errors)
    check_versions(errors, warnings)
    check_doc_index(errors)
    check_model_table(errors)

    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    for e in errors:
        print(f"error: {e}", file=sys.stderr)

    if args.strict and warnings:
        errors.extend(warnings)

    if errors:
        print(
            f"\nDocs check failed: {len(errors)} error(s), {len(warnings)} warning(s).",
            file=sys.stderr,
        )
        return 1

    print(f"Docs check OK ({len(warnings)} warning(s))." if warnings else "Docs check OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
