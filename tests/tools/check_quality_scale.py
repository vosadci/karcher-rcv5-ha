#!/usr/bin/env python3
"""Quality-scale tier-claim audit.

Reads quality_scale.yaml and manifest.json; fails if the manifest
`quality_scale` claim exceeds the highest tier whose every item is
`done` or `exempt`.

Tier order (lowest to highest): bronze < silver < gold < platinum.

A tier is "earned" when every rule belonging to it and every rule in
all lower tiers is `done` or `exempt`. The highest earned tier is the
maximum the manifest may claim.

Exit status: 0 = claim is valid, 1 = claim exceeds earned tier.

Stdlib only — runs without a venv bootstrap.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "custom_components" / "karcher_home_robots" / "manifest.json"
QS_YAML = ROOT / "custom_components" / "karcher_home_robots" / "quality_scale.yaml"

# Canonical tier order and membership.  Keys are the slugs used in
# manifest.json; values are the ordered list of rule slugs belonging to
# that tier.  Order matters: a tier is earned only if all lower tiers
# are also fully earned.
TIERS: dict[str, list[str]] = {
    "bronze": [
        "action-setup",
        "appropriate-polling",
        "brands",
        "common-modules",
        "config-flow",
        "config-flow-test-coverage",
        "dependency-transparency",
        "docs-actions",
        "docs-high-level-description",
        "docs-installation-instructions",
        "docs-removal-instructions",
        "entity-event-setup",
        "entity-unique-id",
        "has-entity-name",
        "runtime-data",
        "test-before-configure",
        "test-before-setup",
        "unique-config-entry",
    ],
    "silver": [
        "action-exceptions",
        "config-entry-unloading",
        "docs-configuration-parameters",
        "docs-installation-parameters",
        "entity-unavailable",
        "integration-owner",
        "log-when-unavailable",
        "parallel-updates",
        "reauthentication-flow",
        "test-coverage",
    ],
    "gold": [
        "devices",
        "diagnostics",
        "discovery",
        "discovery-update-info",
        "docs-data-update",
        "docs-examples",
        "docs-known-limitations",
        "docs-supported-devices",
        "docs-supported-functions",
        "docs-troubleshooting",
        "docs-use-cases",
        "dynamic-devices",
        "entity-category",
        "entity-device-class",
        "entity-disabled-by-default",
        "entity-translations",
        "exception-translations",
        "icon-translations",
        "reconfiguration-flow",
        "repair-issues",
        "stale-devices",
    ],
    "platinum": [
        "async-dependency",
        "inject-websession",
        "strict-typing",
    ],
}

TIER_ORDER = list(TIERS.keys())  # bronze, silver, gold, platinum


def _parse_yaml_rules(text: str) -> dict[str, str]:
    """Minimal YAML parser for the quality_scale.yaml rules block.

    Handles two forms:
      rule-slug: done
      rule-slug:
        status: done
        comment: ...

    Returns {slug: status}.  Stdlib only — no PyYAML.
    """
    rules: dict[str, str] = {}
    lines = text.splitlines()
    i = 0
    in_rules = False
    current_slug: str | None = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip comments and blank lines
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # Top-level `rules:` key
        if stripped == "rules:":
            in_rules = True
            i += 1
            continue

        if not in_rules:
            i += 1
            continue

        # Indented content inside rules block (2-space indent)
        indent = len(line) - len(line.lstrip())

        if indent == 2:
            # Either "  slug: status" or "  slug:" (expanded form)
            if ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip()
                if value in ("done", "todo", "exempt"):
                    rules[key] = value
                    current_slug = None
                elif value == "":
                    # Expanded form — look for `status:` on the next lines
                    current_slug = key
                else:
                    current_slug = None
        elif indent == 4 and current_slug is not None and ":" in stripped:
            key, _, value = stripped.partition(":")
            if key.strip() == "status":
                rules[current_slug] = value.strip()

        i += 1

    return rules


def _load_manifest_claim() -> str:
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read manifest.json: {exc}", file=sys.stderr)
        sys.exit(1)
    claim = manifest.get("quality_scale", "")
    if claim not in TIER_ORDER:
        print(
            f"error: manifest.json quality_scale={claim!r} is not a recognised tier "
            f"({', '.join(TIER_ORDER)})",
            file=sys.stderr,
        )
        sys.exit(1)
    return claim


def _highest_earned_tier(rules: dict[str, str]) -> str | None:
    """Return the highest tier slug where every rule up to and including
    that tier is done or exempt, or None if even bronze is not earned."""
    earned: str | None = None
    for tier in TIER_ORDER:
        for slug in TIERS[tier]:
            status = rules.get(slug, "")
            if status not in ("done", "exempt"):
                return earned
        earned = tier
    return earned


def main() -> int:
    if not QS_YAML.exists():
        print(
            f"error: {QS_YAML.relative_to(ROOT)} not found",
            file=sys.stderr,
        )
        return 1

    text = QS_YAML.read_text(encoding="utf-8")
    rules = _parse_yaml_rules(text)

    # Warn about any rule slug in TIERS not present in the YAML
    missing: list[str] = []
    for tier_rules in TIERS.values():
        for slug in tier_rules:
            if slug not in rules:
                missing.append(slug)
    if missing:
        for slug in missing:
            print(f"warning: rule {slug!r} not found in quality_scale.yaml", file=sys.stderr)

    earned = _highest_earned_tier(rules)
    claimed = _load_manifest_claim()

    earned_idx = TIER_ORDER.index(earned) if earned else -1
    claimed_idx = TIER_ORDER.index(claimed)

    print(f"Earned tier : {earned or 'none'}")
    print(f"Claimed tier: {claimed}")

    if claimed_idx > earned_idx:
        # Identify which rules are blocking the claimed tier
        blockers: list[str] = []
        for tier in TIER_ORDER[: claimed_idx + 1]:
            for slug in TIERS[tier]:
                if rules.get(slug, "") not in ("done", "exempt"):
                    blockers.append(f"  {tier}/{slug}: {rules.get(slug, 'MISSING')!r}")
        earned_label = repr(earned) if earned else "none"
        print(
            f"\nerror: manifest claims {claimed!r} but earned tier is "
            f"{earned_label}. Blocking items:",
            file=sys.stderr,
        )
        for b in blockers:
            print(b, file=sys.stderr)
        return 1

    print("Quality-scale claim OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
