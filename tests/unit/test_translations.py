# SPDX-License-Identifier: MIT
"""Parity gates for the integration's translation files.

``strings.json`` is the source of truth; ``translations/en.json`` must mirror it,
and every other ``translations/<lang>.json`` must carry the exact same key tree.
This is strict on purpose: a missing key does not error at runtime — HA silently
falls back to English — so without this gate an untranslated string ships unseen.
Languages are discovered from the directory, so a newly added file is checked
automatically.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parents[2] / "custom_components" / "karcher_home_robots"
_STRINGS = _PKG / "strings.json"
_TRANSLATIONS = _PKG / "translations"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _key_paths(obj: object, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}/{key}"
            keys.add(path)
            keys |= _key_paths(value, path)
    return keys


def _lang_files() -> list[Path]:
    return sorted(_TRANSLATIONS.glob("*.json"))


def test_en_translation_exists() -> None:
    assert (_TRANSLATIONS / "en.json").is_file(), "translations/en.json is required"


def test_strings_json_matches_en() -> None:
    """en.json is the runtime mirror of the strings.json source — keep identical."""
    assert _load(_STRINGS) == _load(_TRANSLATIONS / "en.json")


@pytest.mark.parametrize("lang_file", _lang_files(), ids=lambda p: p.stem)
def test_language_key_parity(lang_file: Path) -> None:
    """Every language has exactly en's key tree — no missing or extra keys."""
    en_keys = _key_paths(_load(_TRANSLATIONS / "en.json"))
    lang_keys = _key_paths(_load(lang_file))
    missing = sorted(en_keys - lang_keys)
    extra = sorted(lang_keys - en_keys)
    assert not missing, f"{lang_file.name} missing keys: {missing}"
    assert not extra, f"{lang_file.name} extra keys: {extra}"


@pytest.mark.parametrize("lang_file", _lang_files(), ids=lambda p: p.stem)
def test_reauth_email_placeholder_preserved(lang_file: Path) -> None:
    """The {email} placeholder must survive translation or the reauth text breaks."""
    desc = _load(lang_file)["config"]["step"]["reauth_confirm"]["description"]
    assert "{email}" in desc, f"{lang_file.name} dropped the {{email}} placeholder"


def _config_flow_error_keys() -> set[str]:
    """Error keys `config_flow.py` can hand Home Assistant, read from its source.

    Parsed rather than imported: the point is an oracle independent of the code
    under test, and importing config_flow would only let it agree with itself.
    Two syntactic positions produce a key — `return "<key>", []` from the
    validation helpers, and a literal assigned to `errors["base"]`.
    """
    tree = ast.parse((_PKG / "config_flow.py").read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
            first = node.value.elts[0] if node.value.elts else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                keys.add(first.value)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "errors"
                    and isinstance(node.value.value, str)
                ):
                    keys.add(node.value.value)
    return keys


def test_every_config_flow_error_key_has_a_string() -> None:
    """A renamed error key with a stale strings.json shows the raw key name to
    the user — Home Assistant does not warn, and the parity gates above only
    compare the JSON files to each other, so nothing else would catch it."""
    keys = _config_flow_error_keys()
    assert "malformed_device" in keys, "parser found no keys — it has drifted from the source"

    defined = set(_load(_STRINGS)["config"]["error"])
    assert keys <= defined, f"config_flow returns keys with no string: {sorted(keys - defined)}"
