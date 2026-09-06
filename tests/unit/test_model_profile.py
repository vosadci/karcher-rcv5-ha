# SPDX-License-Identifier: MIT
"""Unit tests for the model profile table.

Every assertion here checks PROFILES against an **independent** oracle —
Python's own rules for identifiers, the table's internal uniqueness, or an
exhaustive walk of SupportTier. Iterating PROFILES and comparing it to PROFILES
would prove nothing; that vacuous shape is how a self-referential test shipped
alongside the RVM 4 addition and had to be fixed the next day.

The cross-checks against the real merged enum and the full adapter path live in
tests/contract/, where the library is available.
"""

from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

import pytest
from custom_components.karcher_home_robots._model_profile import (
    PROFILES,
    README_BEGIN,
    README_END,
    ModelProfile,
    SupportTier,
    display_name,
    profile_for,
    render_readme_block,
    repair_key_for_tier,
    tier_for,
)

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "custom_components" / "karcher_home_robots" / "_model_profile.py"


def test_member_names_are_valid_python_identifiers() -> None:
    """These become enum member names. A non-identifier fails at import time
    inside a user's Home Assistant, which no linter here would catch."""
    for profile in PROFILES:
        assert profile.member_name.isidentifier(), (
            f"{profile.display_name}: member_name {profile.member_name!r} is not an identifier"
        )
        assert not profile.member_name.startswith("_"), (
            f"{profile.display_name}: leading underscore is not a usable enum member name"
        )


def test_product_ids_are_decimal_strings() -> None:
    """The cloud reports these as decimal strings and they are concatenated
    straight into MQTT topics. A stray space or quote would build a bad topic."""
    for profile in PROFILES:
        assert profile.product_id.isdigit(), (
            f"{profile.display_name}: product_id {profile.product_id!r} is not decimal"
        )


def test_product_ids_are_unique() -> None:
    """Lookup is by product ID; a duplicate silently shadows a model."""
    ids = [p.product_id for p in PROFILES]
    assert len(ids) == len(set(ids)), f"duplicate product_id in PROFILES: {sorted(ids)}"


def test_member_names_are_unique() -> None:
    """Duplicate member names collapse into one enum member, dropping a model."""
    names = [p.member_name for p in PROFILES]
    assert len(names) == len(set(names)), f"duplicate member_name in PROFILES: {sorted(names)}"


def test_display_names_are_unique() -> None:
    """Two models sharing a registry name are indistinguishable to a user."""
    names = [p.display_name for p in PROFILES]
    assert len(names) == len(set(names)), f"duplicate display_name in PROFILES: {sorted(names)}"


def test_evidence_is_one_non_empty_line() -> None:
    """Evidence renders into a markdown table cell; a newline breaks the table
    and an empty string means the tier was asserted without saying why."""
    for profile in PROFILES:
        assert profile.evidence.strip(), f"{profile.display_name}: empty evidence"
        assert "\n" not in profile.evidence, f"{profile.display_name}: evidence spans lines"
        assert "|" not in profile.evidence, f"{profile.display_name}: evidence contains a pipe"


def test_exactly_one_maintainer_verified_model() -> None:
    """The maintainer owns one robot. More than one row claiming it means
    someone raised a tier without hardware behind it."""
    owned = [p for p in PROFILES if p.tier is SupportTier.MAINTAINER_VERIFIED]
    assert [p.display_name for p in owned] == ["RCV 5"]


@pytest.mark.parametrize("tier", list(SupportTier))
def test_repair_key_returns_a_usable_value_for_every_tier(tier: SupportTier) -> None:
    """Every tier resolves to a repair key or an explicit no-prompt."""
    key = repair_key_for_tier(tier)
    assert key is None or key.startswith("model_support_")


def test_every_tier_is_named_explicitly_in_the_match() -> None:
    """Adding a tier must be a deliberate repair decision, not a fall-through.

    This assertion is here because the parametrised test above CANNOT catch it:
    an unhandled tier falls through the match and returns None, which satisfies
    "key is None or ...". Verified by adding a fifth member and watching that
    test still pass.

    `mypy --strict` does catch it — as "Missing return statement", which does
    not explain itself — so this test states the requirement in the suite too,
    and names the tier that was forgotten.
    """
    source = inspect.getsource(repair_key_for_tier)
    for tier in SupportTier:
        assert f"SupportTier.{tier.name}" in source, (
            f"SupportTier.{tier.name} is not named in repair_key_for_tier(); "
            f"decide whether it raises a repair issue rather than letting it "
            f"fall through to no prompt"
        )


def test_only_uncertain_and_unlisted_raise_a_repair() -> None:
    """The negative half is the one that protects users: prompting on EXPECTED
    would hit most new users and train them to dismiss repairs."""
    assert repair_key_for_tier(SupportTier.UNCERTAIN) == "model_support_uncertain"
    assert repair_key_for_tier(None) == "model_support_unlisted"
    assert repair_key_for_tier(SupportTier.EXPECTED) is None
    assert repair_key_for_tier(SupportTier.COMMUNITY_VERIFIED) is None
    assert repair_key_for_tier(SupportTier.MAINTAINER_VERIFIED) is None


def test_lookup_is_by_product_id_not_member_name() -> None:
    """The load-bearing invariant. The pinned library calls 1599715149861306368
    "RCF5" while Kärcher calls it RCF3 (doc/PROTOCOL.md §16.7); keying on the ID
    makes that mislabel — and any fork that fixes it — irrelevant here."""
    profile = profile_for("1599715149861306368")
    assert profile is not None
    assert profile.display_name == "RCF 3"
    assert profile.member_name == "RCF3"


def test_unlisted_product_id_falls_back_to_the_raw_id() -> None:
    """An unlisted robot must register honestly, not under another model's name."""
    assert profile_for("9999999999999999999") is None
    assert tier_for("9999999999999999999") is None
    assert display_name("9999999999999999999") == "9999999999999999999"


def test_render_block_is_delimited_and_lists_every_model() -> None:
    """The README region is generated; every row must reach it."""
    block = render_readme_block()
    assert block.startswith(README_BEGIN)
    assert block.endswith(README_END)
    for profile in PROFILES:
        assert profile.display_name in block, f"{profile.display_name} missing from README block"
        assert profile.product_id in block, f"{profile.product_id} missing from README block"
        assert profile.evidence in block, f"{profile.display_name}: evidence missing"


_PATH_LOAD_PROBE = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("_mp", {path!r})
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module          # @dataclass resolves annotations through this
spec.loader.exec_module(module)
leaked = sorted({{m.split(".")[0] for m in sys.modules}} & {{"homeassistant", "karcher"}})
print(len(module.PROFILES), ",".join(leaked))
"""


def test_module_loads_by_path_without_dragging_in_home_assistant() -> None:
    """check_docs.py imports this file by path, with no venv and no package
    import, so it must stay stdlib-only with no relative imports — importing it
    through the package would execute __init__.py and pull in Home Assistant.

    Run in a subprocess on purpose. Inside pytest, `homeassistant` is already in
    sys.modules because conftest imported it, so an in-process check would pass
    no matter what this module imports. A clean interpreter is the only oracle
    that actually tests the claim.

    Registering the module in sys.modules is part of the contract, not
    incidental: @dataclass resolves its string annotations through
    sys.modules[cls.__module__] and raises AttributeError without it.
    """
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _PATH_LOAD_PROBE.format(path=str(MODULE_PATH))],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, f"loading by path failed:\n{proc.stderr}"

    count, _, leaked = proc.stdout.strip().partition(" ")
    assert int(count) == len(PROFILES)
    assert leaked == "", f"_model_profile.py pulled in {leaked} — it must stay stdlib-only"


def test_profiles_is_immutable() -> None:
    """A tuple of frozen dataclasses: nothing can mutate the table at runtime."""
    assert isinstance(PROFILES, tuple)
    with pytest.raises(AttributeError):
        PROFILES[0].tier = SupportTier.UNCERTAIN  # type: ignore[misc]


def test_profile_fields_are_all_populated() -> None:
    """A row added with a field left empty would render a blank table cell."""
    for profile in PROFILES:
        assert isinstance(profile, ModelProfile)
        assert profile.display_name.strip()
        assert profile.product_id.strip()
        assert profile.member_name.strip()
