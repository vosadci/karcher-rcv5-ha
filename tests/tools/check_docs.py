#!/usr/bin/env python3
"""Documentation freshness and consistency checker.

Runs a set of deterministic drift checks across the spec set and
configuration:

1. Broken relative markdown links in any `.md` under `rewrite/`.
2. ADR supersede chain consistency (`Supersedes:` / `Superseded-by:`
   fields must be mutual and the losing ADR's `Status:` must be
   `Superseded`).
3. Requirement-ID references (`FR-*`, `NFR-*`, `SEC-*`, `OPS-*`) in
   any spec file must resolve to an ID defined in
   `spec/02-requirements.md`.
4. ADR references (`ADR-NNNN`) in any file must resolve to an existing
   `adr/NNNN-*.md`.
5. Backlog references (`P<phase>-<n>`) must appear in
   `spec/09-roadmap-and-backlog.md`.
6. `WAIVERS.md` (repo root) entries with a date-form expiry in the
   past are reported. The file is created on demand when the first
   waiver lands; absence is not a problem.
7. Required structural markers: `README.md` top heading, `CHANGELOG.md`
   `[Unreleased]` block, `CLAUDE.md` skills section.
8. Version consistency: `hacs.json` `homeassistant` agrees with
   `manifest.json` (when present) and appears in the CI workflow's HA
   matrix.

Stdlib only. Exit 0 on clean, 1 on any issue.

Soft checks (warnings) are printed but do not fail the build unless
`--strict` is given.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ID_RE = re.compile(r"\b(FR-[A-Z]+-\d+|NFR-[A-Z]+-\d+|SEC-\d+|OPS-\d+)\b")
BACKLOG_RE = re.compile(r"\bP\d+-\d+\b")
ADR_REF_RE = re.compile(r"\bADR-(\d{4})\b")
LINK_RE = re.compile(r"(?<!\!)\[([^\]]+)\]\(([^)]+)\)")
ADR_FILENAME_RE = re.compile(r"^(\d{4})-[a-z0-9-]+\.md$")


# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------


def _iter_md(root: Path) -> Iterator[Path]:
    for p in root.rglob("*.md"):
        if any(seg in p.parts for seg in ("__pycache__", ".git")):
            continue
        yield p


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_fences(text: str) -> str:
    """Remove triple-backtick fenced blocks so we don't flag examples."""
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


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


def check_adr_chain(errors: list[str]) -> None:
    """2. ADR supersede fields are mutual and statuses agree."""
    adr_dir = ROOT / "adr"
    if not adr_dir.exists():
        return
    by_num: dict[str, Path] = {}
    for p in adr_dir.glob("*.md"):
        m = ADR_FILENAME_RE.match(p.name)
        if m:
            by_num[m.group(1)] = p

    status: dict[str, str] = {}
    supersedes: dict[str, str] = {}
    superseded_by: dict[str, str] = {}

    status_re = re.compile(r"^Status:\s*(.+?)\s*$", re.MULTILINE)
    sup_re = re.compile(r"^Supersedes:\s*ADR-(\d{4})\b", re.MULTILINE)
    sup_by_re = re.compile(r"^Superseded-by:\s*ADR-(\d{4})\b", re.MULTILINE)

    for num, path in by_num.items():
        text = _read(path)
        if m := status_re.search(text):
            status[num] = m.group(1).strip()
        if m := sup_re.search(text):
            supersedes[num] = m.group(1)
        if m := sup_by_re.search(text):
            superseded_by[num] = m.group(1)

    for a, b in supersedes.items():
        if b not in by_num:
            errors.append(f"adr/{by_num[a].name}: Supersedes ADR-{b} but no such ADR")
            continue
        if superseded_by.get(b) != a:
            errors.append(
                f"adr/{by_num[b].name}: missing `Superseded-by: ADR-{a}` "
                f"to match adr/{by_num[a].name}"
            )
        if status.get(b, "").lower() not in {"superseded"}:
            errors.append(
                f"adr/{by_num[b].name}: Status must be `Superseded` "
                f"because ADR-{a} supersedes it (current: {status.get(b, '<missing>')})"
            )

    for a, b in superseded_by.items():
        if b not in by_num:
            errors.append(f"adr/{by_num[a].name}: Superseded-by ADR-{b} but no such ADR")
            continue
        if supersedes.get(b) != a:
            errors.append(
                f"adr/{by_num[b].name}: missing `Supersedes: ADR-{a}` to match adr/{by_num[a].name}"
            )


def _known_requirement_ids() -> set[str]:
    reqs = ROOT / "spec" / "02-requirements.md"
    if not reqs.exists():
        return set()
    return set(ID_RE.findall(_read(reqs)))


def check_requirement_refs(errors: list[str]) -> None:
    """3. Every FR/NFR/SEC/OPS citation in any .md resolves to a real ID."""
    known = _known_requirement_ids()
    if not known:
        return
    for md in _iter_md(ROOT):
        if md.name == "02-requirements.md":
            continue
        text = _strip_fences(_read(md))
        for cid in ID_RE.findall(text):
            if cid not in known:
                errors.append(
                    f"{md.relative_to(ROOT)}: references unknown requirement `{cid}` "
                    f"(not in spec/02-requirements.md)"
                )


def check_adr_refs(errors: list[str]) -> None:
    """4. Every ADR-NNNN reference resolves to a file under adr/."""
    adr_dir = ROOT / "adr"
    existing: set[str] = set()
    if adr_dir.exists():
        for p in adr_dir.glob("*.md"):
            if m := ADR_FILENAME_RE.match(p.name):
                existing.add(m.group(1))
    # CHANGELOG.md is exempt: its historical entries cite ADRs that may have
    # been deleted as the project matures. Requiring live files for past-release
    # traceability would force lossy edits to the release history.
    for md in _iter_md(ROOT):
        if md.name == "CHANGELOG.md":
            continue
        text = _strip_fences(_read(md))
        for num in ADR_REF_RE.findall(text):
            if num not in existing:
                errors.append(
                    f"{md.relative_to(ROOT)}: references `ADR-{num}` but "
                    f"adr/{num}-*.md does not exist"
                )


def check_backlog_refs(errors: list[str]) -> None:
    """5. Every P<phase>-<n> reference appears in the backlog."""
    backlog = ROOT / "spec" / "09-roadmap-and-backlog.md"
    if not backlog.exists():
        return
    known = set(BACKLOG_RE.findall(_read(backlog)))
    if not known:
        return
    for md in _iter_md(ROOT):
        if md.name == "09-roadmap-and-backlog.md":
            continue
        text = _strip_fences(_read(md))
        for bid in BACKLOG_RE.findall(text):
            if bid not in known:
                errors.append(
                    f"{md.relative_to(ROOT)}: references backlog item `{bid}` "
                    f"not listed in spec/09-roadmap-and-backlog.md"
                )


def check_waivers(errors: list[str], warnings: list[str]) -> None:
    """6. Open waivers with a past ISO-date expiry."""
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
    """7. Required markers are present in key docs."""
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
    """8. hacs.json agrees with manifest.json and with the CI HA matrix."""
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
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    check_links(errors)
    check_adr_chain(errors)
    check_requirement_refs(errors)
    check_adr_refs(errors)
    check_backlog_refs(errors)
    check_waivers(errors, warnings)
    check_required_structure(errors)
    check_versions(errors, warnings)

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
