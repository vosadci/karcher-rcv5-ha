"""Unit tests for tests/tools/check_venv.py — HA release-channel guard."""

from __future__ import annotations

from importlib import metadata

import pytest
from tests.tools import check_venv
from tests.tools.check_venv import _check_ha_channel


def _fake_version(value: str | type[Exception]) -> object:
    def _version(name: str) -> str:
        assert name == "homeassistant"
        if isinstance(value, str):
            return value
        raise value("homeassistant")

    return _version


def test_stable_ha_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_venv.metadata, "version", _fake_version("2026.9.0"))
    assert _check_ha_channel() is None


@pytest.mark.parametrize("version", ["2026.9.0b0", "2026.9.0b6", "2027.1.0rc1", "2026.10.0a1"])
def test_prerelease_ha_is_rejected(monkeypatch: pytest.MonkeyPatch, version: str) -> None:
    """The whole point: a beta HA must fail, whatever pre-release flavour it is."""
    monkeypatch.setattr(check_venv.metadata, "version", _fake_version(version))
    problem = _check_ha_channel()
    assert problem is not None
    assert "PRE-RELEASE" in problem
    # Names the actual lever, since HA is never pinned directly.
    assert "pytest-homeassistant-custom-component" in problem


def test_ha_absent_is_not_this_checks_business(monkeypatch: pytest.MonkeyPatch) -> None:
    """HA is not a declared dependency; a lint-only env must not fail here."""
    monkeypatch.setattr(
        check_venv.metadata, "version", _fake_version(metadata.PackageNotFoundError)
    )
    assert _check_ha_channel() is None


def test_unparseable_version_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_venv.metadata, "version", _fake_version("not-a-version"))
    problem = _check_ha_channel()
    assert problem is not None
    assert "unparseable" in problem


def test_installed_home_assistant_is_stable() -> None:
    """Independent oracle: the environment this suite actually runs in.

    Unmocked on purpose — this is the assertion that catches a beta-pinned
    dependabot bump, in the `tests` CI job as well as the `type` one.
    """
    assert _check_ha_channel() is None, "this environment is on a pre-release Home Assistant"


# ---------------------------------------------------------------------------
# main() exit code — the wiring CI depends on. Unit-testing _check_ha_channel
# alone leaves this untested: a mutant that drops `channel` from main()'s
# return condition passes every test above while disabling the CI guard.
# ---------------------------------------------------------------------------


def test_main_exits_nonzero_on_prerelease(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_venv, "_requirements", list)
    monkeypatch.setattr(check_venv.metadata, "version", _fake_version("2026.9.0b0"))
    assert check_venv.main() == 1


def test_main_exits_zero_on_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_venv, "_requirements", list)
    monkeypatch.setattr(check_venv.metadata, "version", _fake_version("2026.9.0"))
    assert check_venv.main() == 0
