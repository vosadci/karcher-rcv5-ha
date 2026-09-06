"""Unit tests for tests/tools/check_docs.py — minimum-HA-version consistency."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.tools import check_docs
from tests.tools.check_docs import (
    ROOT,
    _load_model_profile,
    check_ha_version_sites,
    check_model_table,
    fix_model_table,
)

_SITES = {
    "README.md": (
        "[![HA Version](https://img.shields.io/badge/HA-{v}%2B-blue.svg)](https://x/)\n"
        "\n"
        "- **Home Assistant** {v} or newer\n"
    ),
    "ARCHITECTURE.md": "- Minimum HA version: {v}\n",
    "doc/CONSTRAINTS.md": "| Minimum HA version: {v} | Soft | Declared in `hacs.json`. |\n",
}


def _tree(tmp_path: Path, version: str = "2026.9.0") -> Path:
    for rel, template in _SITES.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template.format(v=version), encoding="utf-8")
    return tmp_path


def test_consistent_tree_passes(tmp_path: Path) -> None:
    errors: list[str] = []
    check_ha_version_sites("2026.9.0", errors, root=_tree(tmp_path))
    assert errors == []


def test_drifted_site_is_reported(tmp_path: Path) -> None:
    """The failure this check exists for: prose left behind a hacs.json bump."""
    root = _tree(tmp_path, version="2026.9.0")
    (root / "ARCHITECTURE.md").write_text("- Minimum HA version: 2026.7.1\n", encoding="utf-8")
    errors: list[str] = []
    check_ha_version_sites("2026.9.0", errors, root=root)
    assert len(errors) == 1
    assert "ARCHITECTURE.md" in errors[0]
    assert "2026.7.1" in errors[0]


def test_every_site_is_actually_checked(tmp_path: Path) -> None:
    """Drift in any one site must fail — not just the first in the table."""
    for rel, template in _SITES.items():
        root = _tree(tmp_path / rel.replace("/", "_"))
        (root / rel).write_text(template.format(v="1999.1.1"), encoding="utf-8")
        errors: list[str] = []
        check_ha_version_sites("2026.9.0", errors, root=root)
        assert errors, f"drift in {rel} was not detected"
        assert all(rel in e for e in errors), errors


def test_reworded_line_is_an_error_not_a_silent_pass(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "ARCHITECTURE.md").write_text("- Min HA: 2026.9.0\n", encoding="utf-8")
    errors: list[str] = []
    check_ha_version_sites("2026.9.0", errors, root=root)
    assert len(errors) == 1
    assert "HA_VERSION_SITES" in errors[0]


def test_missing_file_is_an_error(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "ARCHITECTURE.md").unlink()
    errors: list[str] = []
    check_ha_version_sites("2026.9.0", errors, root=root)
    assert len(errors) == 1
    assert "missing" in errors[0]


def test_no_hacs_version_means_nothing_to_compare(tmp_path: Path) -> None:
    errors: list[str] = []
    check_ha_version_sites(None, errors, root=_tree(tmp_path, version="1999.1.1"))
    assert errors == []


def test_real_repository_is_consistent() -> None:
    """Independent oracle: the actual tree, against the actual hacs.json."""
    hacs_ha = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))["homeassistant"]
    errors: list[str] = []
    check_ha_version_sites(hacs_ha, errors, root=ROOT)
    assert errors == [], errors


def test_check_versions_invokes_the_site_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """The wiring, not just the function.

    Every test above passes with the call deleted from check_versions(), which
    would disable the gate while leaving the suite green.
    """
    seen: list[str | None] = []

    def _spy(hacs_ha: str | None, errors: list[str], root: Path = ROOT) -> None:
        seen.append(hacs_ha)

    monkeypatch.setattr(check_docs, "check_ha_version_sites", _spy)
    check_docs.check_versions([], [])

    expected = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))["homeassistant"]
    assert seen == [expected]


# ---------------------------------------------------------------------------
# Generated supported-models table
# ---------------------------------------------------------------------------


def _readme_tree(tmp_path: Path, block: str) -> Path:
    (tmp_path / "README.md").write_text(
        f"# Title\n\nIntro paragraph.\n\n{block}\n\nTrailing prose.\n",
        encoding="utf-8",
    )
    return tmp_path


def test_real_repository_model_table_is_current() -> None:
    """The oracle that actually matters: the checked-in README against PROFILES.

    Every synthetic case below can drift from the real files; this one cannot.
    """
    errors: list[str] = []
    check_model_table(errors)
    assert errors == []


def test_generated_region_matching_profiles_passes(tmp_path: Path) -> None:
    profile = _load_model_profile()
    root = _readme_tree(tmp_path, profile.render_readme_block())
    errors: list[str] = []
    check_model_table(errors, root=root)
    assert errors == []


def test_stale_table_is_reported_with_the_paste_ready_block(tmp_path: Path) -> None:
    """A contributor who has not run --fix-model-table must be able to finish
    from the CI log alone, so the whole expected region is printed."""
    profile = _load_model_profile()
    stale = profile.render_readme_block().replace("RCV 5", "RCV 5 EDITED", 1)
    root = _readme_tree(tmp_path, stale)

    errors: list[str] = []
    check_model_table(errors, root=root)

    assert len(errors) == 1
    assert "--fix-model-table" in errors[0]
    assert profile.render_readme_block() in errors[0]


def test_missing_markers_are_an_error_not_a_silent_pass(tmp_path: Path) -> None:
    """Deleting the region must not become a way to dodge the check."""
    root = _readme_tree(tmp_path, "| Model | Status |\n|---|---|\n| RCV 5 | fine |")
    errors: list[str] = []
    check_model_table(errors, root=root)
    assert len(errors) == 1
    assert "no generated region" in errors[0]


def test_missing_readme_is_an_error(tmp_path: Path) -> None:
    errors: list[str] = []
    check_model_table(errors, root=tmp_path)
    assert len(errors) == 1
    assert "README.md" in errors[0]


def test_fix_rewrites_a_stale_region_in_place(tmp_path: Path) -> None:
    """--fix-model-table is what keeps adding a model a one-file edit."""
    profile = _load_model_profile()
    stale = profile.render_readme_block().replace("RCV 5", "WRONG", 1)
    root = _readme_tree(tmp_path, stale)

    assert fix_model_table(root=root) == 0

    errors: list[str] = []
    check_model_table(errors, root=root)
    assert errors == []
    text = (root / "README.md").read_text(encoding="utf-8")
    assert "Intro paragraph." in text, "--fix must not clobber prose outside the region"
    assert "Trailing prose." in text
    assert "WRONG" not in text


def test_fix_refuses_a_readme_without_markers(tmp_path: Path) -> None:
    root = _readme_tree(tmp_path, "no markers here")
    assert fix_model_table(root=root) == 1


def test_adding_a_profile_row_changes_the_expected_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The check is driven by PROFILES, not by a copy of the table.

    Renders the current block, then adds a row and confirms the previously-good
    README is now reported stale — otherwise the gate would pass a README that
    silently omits a model.
    """
    profile = _load_model_profile()
    root = _readme_tree(tmp_path, profile.render_readme_block())

    extra = profile.ModelProfile(
        product_id="1111111111111111111",
        member_name="TESTONLY",
        display_name="Test Only",
        tier=profile.SupportTier.UNCERTAIN,
        evidence="Synthetic row for this test.",
    )
    monkeypatch.setattr(profile, "PROFILES", (*profile.PROFILES, extra))
    monkeypatch.setattr(check_docs, "_load_model_profile", lambda *a, **k: profile)

    errors: list[str] = []
    check_model_table(errors, root=root)

    assert len(errors) == 1
    assert "Test Only" in errors[0]


def test_main_runs_the_model_table_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wiring, not just the function. A check that main() never calls is dead —
    the same gap that let a version-drift mutant survive in this file before.
    """
    called: list[str] = []
    monkeypatch.setattr(check_docs, "check_model_table", lambda errors, **kw: called.append("yes"))
    monkeypatch.setattr("sys.argv", ["check_docs.py"])
    check_docs.main()
    assert called == ["yes"]
