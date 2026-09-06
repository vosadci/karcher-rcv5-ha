"""Unit tests for tests/tools/check_imports.py."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from tests.tools.check_imports import (
    ALLOWED_PRIVATE_API,
    ALLOWED_STDLIB_PRIVATE_API,
    _check_rule1,
    _check_rule2,
)


def _write(tmp_path: Path, name: str, src: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(src), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Rule 1 — adapter boundary
# ---------------------------------------------------------------------------


def test_rule1_clean_adapter_passes(tmp_path: Path) -> None:
    """adapter.py importing karcher is not a violation."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    adapter = _write(pkg, "adapter.py", "import karcher\n")
    assert _check_rule1(pkg, adapter) == []


def test_rule1_non_adapter_import_karcher_fails(tmp_path: Path) -> None:
    """Any other module importing karcher is a violation."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    adapter = pkg / "adapter.py"
    adapter.write_text("", encoding="utf-8")
    _write(pkg, "coordinator.py", "import karcher\n")
    violations = _check_rule1(pkg, adapter)
    assert len(violations) == 1
    assert "coordinator.py" in violations[0]
    assert "only adapter.py" in violations[0]


def test_rule1_from_karcher_import_fails(tmp_path: Path) -> None:
    """from karcher.foo import Bar in a non-adapter module is a violation."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    adapter = pkg / "adapter.py"
    adapter.write_text("", encoding="utf-8")
    _write(pkg, "vacuum.py", "from karcher.home import KarcherHome\n")
    violations = _check_rule1(pkg, adapter)
    assert len(violations) == 1
    assert "vacuum.py" in violations[0]


def test_rule1_no_karcher_import_passes(tmp_path: Path) -> None:
    """Module with no karcher import produces no violations."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    adapter = pkg / "adapter.py"
    adapter.write_text("", encoding="utf-8")
    _write(pkg, "const.py", "DOMAIN = 'karcher_home_robots'\n")
    assert _check_rule1(pkg, adapter) == []


def test_rule1_missing_pkg_passes(tmp_path: Path) -> None:
    """Non-existent package directory produces no violations (pre-scaffold)."""
    pkg = tmp_path / "does_not_exist"
    adapter = pkg / "adapter.py"
    assert _check_rule1(pkg, adapter) == []


# ---------------------------------------------------------------------------
# Rule 2 — private-API allowlist
# ---------------------------------------------------------------------------


def test_rule2_allowlisted_symbol_passes(tmp_path: Path) -> None:
    """Access to an allowlisted private symbol is clean."""
    adapter = _write(tmp_path, "adapter.py", "x = client._mqtt\n")
    assert _check_rule2(adapter, ALLOWED_PRIVATE_API) == []


def test_rule2_allowlisted_chain_passes(tmp_path: Path) -> None:
    """Multi-level access _mqtt.on_message is in the allowlist."""
    adapter = _write(tmp_path, "adapter.py", "client._mqtt.on_message = cb\n")
    assert _check_rule2(adapter, ALLOWED_PRIVATE_API) == []


def test_rule2_unknown_private_fails(tmp_path: Path) -> None:
    """A private attribute not in the allowlist is a violation."""
    adapter = _write(tmp_path, "adapter.py", "x = client._secret\n")
    violations = _check_rule2(adapter, ALLOWED_PRIVATE_API)
    assert len(violations) == 1
    assert "_secret" in violations[0]
    assert "ALLOWED_PRIVATE_API" in violations[0]


def test_rule2_computed_getattr_fails(tmp_path: Path) -> None:
    """getattr(obj, variable) with a non-literal name is always a violation."""
    adapter = _write(
        tmp_path,
        "adapter.py",
        """\
        name = "_mqtt"
        x = getattr(client, name)
        """,
    )
    violations = _check_rule2(adapter, ALLOWED_PRIVATE_API)
    assert len(violations) == 1
    assert "non-literal" in violations[0]


def test_rule2_literal_getattr_allowlisted_passes(tmp_path: Path) -> None:
    """getattr(obj, '_mqtt') with a literal string passes if in allowlist."""
    adapter = _write(tmp_path, "adapter.py", "x = getattr(client, '_mqtt')\n")
    assert _check_rule2(adapter, ALLOWED_PRIVATE_API) == []


def test_rule2_literal_getattr_unknown_fails(tmp_path: Path) -> None:
    """getattr(obj, '_hidden') with an unknown literal private name fails."""
    adapter = _write(tmp_path, "adapter.py", "x = getattr(client, '_hidden')\n")
    violations = _check_rule2(adapter, ALLOWED_PRIVATE_API)
    assert len(violations) == 1
    assert "_hidden" in violations[0]


def test_rule2_missing_adapter_passes(tmp_path: Path) -> None:
    """Non-existent adapter.py produces no violations (pre-scaffold)."""
    adapter = tmp_path / "adapter.py"
    assert _check_rule2(adapter, ALLOWED_PRIVATE_API) == []


def test_rule2_public_attribute_ignored(tmp_path: Path) -> None:
    """Public attribute accesses (no leading underscore) are not checked."""
    adapter = _write(tmp_path, "adapter.py", "x = client.public_method()\n")
    assert _check_rule2(adapter, ALLOWED_PRIVATE_API) == []


def test_rule2_self_private_attr_ignored(tmp_path: Path) -> None:
    """self._foo is the adapter's own instance attribute and must not be flagged."""
    adapter = _write(
        tmp_path,
        "adapter.py",
        "self._hass = hass\nself._client = cast(proto, raw)\n",
    )
    assert _check_rule2(adapter, ALLOWED_PRIVATE_API) == []


def test_rule2_external_unknown_private_via_self_client_fails(tmp_path: Path) -> None:
    """self._client._hidden is an external private access and must be flagged."""
    adapter = _write(tmp_path, "adapter.py", "x = self._client._hidden\n")
    violations = _check_rule2(adapter, ALLOWED_PRIVATE_API)
    assert len(violations) == 1
    assert "_hidden" in violations[0]


@pytest.mark.parametrize(
    "symbol",
    sorted(ALLOWED_PRIVATE_API),
)
def test_rule2_every_allowlisted_symbol_passes(tmp_path: Path, symbol: str) -> None:
    """Each entry in ALLOWED_PRIVATE_API passes the checker."""
    src = f"x = obj.{symbol}\n"
    adapter = _write(tmp_path, "adapter.py", src)
    assert _check_rule2(adapter, ALLOWED_PRIVATE_API) == []


# ---------------------------------------------------------------------------
# Rule 2 — stdlib private allowlist (full-chain matched)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("chain", sorted(ALLOWED_STDLIB_PRIVATE_API))
def test_rule2_every_stdlib_chain_passes(tmp_path: Path, chain: str) -> None:
    """Each entry in ALLOWED_STDLIB_PRIVATE_API passes as written."""
    adapter = _write(tmp_path, "adapter.py", f"x = {chain}\n")
    assert _check_rule2(adapter, ALLOWED_PRIVATE_API) == []


def test_rule2_stdlib_allowlist_does_not_bless_the_same_name_elsewhere(
    tmp_path: Path,
) -> None:
    """The whole reason the stdlib set is matched on the full dotted chain.

    `str.__new__` reaches the suffix check as bare `__new__`; if it were added
    to ALLOWED_PRIVATE_API, `client.__new__` on a karcher object would pass too.
    """
    assert "str.__new__" in ALLOWED_STDLIB_PRIVATE_API
    adapter = _write(tmp_path, "adapter.py", "x = client.__new__(client)\n")
    violations = _check_rule2(adapter, ALLOWED_PRIVATE_API)
    assert len(violations) == 1
    assert "__new__" in violations[0]


def test_rule2_stdlib_allowlist_is_load_bearing(tmp_path: Path) -> None:
    """With the stdlib set emptied, the enum-protocol accesses must be flagged —
    otherwise the allowlist is decorative and proves nothing about the checker."""
    src = "obj = str.__new__(cls, value)\nobj._name_ = n\nobj._value_ = v\n"
    adapter = _write(tmp_path, "adapter.py", src)
    assert _check_rule2(adapter, ALLOWED_PRIVATE_API, frozenset()) != []


def test_rule2_real_adapter_passes_with_the_shipped_allowlists() -> None:
    """End-to-end oracle: the real adapter.py against the real allowlists.

    The synthetic cases above can drift from what adapter.py actually writes;
    this one cannot.
    """
    from tests.tools.check_imports import ADAPTER

    assert _check_rule2(ADAPTER, ALLOWED_PRIVATE_API) == []
