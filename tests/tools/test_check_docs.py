"""Unit tests for tests/tools/check_docs.py — minimum-HA-version consistency."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.tools import check_docs
from tests.tools.check_docs import ROOT, check_ha_version_sites

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
