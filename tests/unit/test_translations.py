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
