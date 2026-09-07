# SPDX-License-Identifier: MIT
"""Conformance tests: asserts the real, pinned karcher-home library still
exposes every private symbol adapter.py depends on.

tests/tools/check_imports.py verifies adapter.py's call sites via static AST
analysis against ALLOWED_PRIVATE_API — it never imports karcher-home to
confirm the symbols actually exist. This module closes that gap: it imports
the real, pinned library (`karcher-home==0.5.1`, see pyproject.toml) and
asserts each allowlisted symbol is present with the shape adapter.py expects.
A silent upstream rename would otherwise pass lint + contract + integration
green and fail only at HIL / in production.

It also covers the one non-symbol claim adapter.py makes about the installed
library: that its distribution metadata is readable under the name we probe.

Runs in the normal CI job — karcher-home is a regular pip dependency here,
no robot needed. Not HIL-gated.

One import subtlety: adapter.py patches `karcher.consts.Product` at import time,
and tests/conftest.py imports the adapter before any test module binds a name —
so `from karcher.consts import Product` here would silently bind the adapter's
own enum and assert it against itself. The library-side checks use
`adapter._LIBRARY_PRODUCT` (captured pre-patch) for that reason.
"""

from __future__ import annotations

import inspect
import warnings
from enum import StrEnum
from importlib import metadata

import pytest
from custom_components.karcher_home_robots import adapter
from custom_components.karcher_home_robots._model_profile import display_name, profile_for
from custom_components.karcher_home_robots.adapter import _LIBRARY_PRODUCT, Product
from karcher.device import Device, DeviceProperties
from karcher.karcher import KarcherHome
from karcher.mqtt import MqttClient

# Mirrors tests/tools/check_imports.py ALLOWED_PRIVATE_API. The coverage test
# at the bottom of this file guards against the two lists drifting apart.
_WORKAROUND = {
    "_mqtt": "adapter's dispatcher lookup / MQTT reconnect detection",
    "_mqtt.on_message": "adapter's threadsafe MQTT dispatcher installation",
    "_update_device_properties": (
        "adapter's property/post push workaround (karcher-home's own dispatch ignores that topic)"
    ),
    "_device_props": "adapter's post-subscribe DeviceProperties cache read",
    "_base_url": "adapter's endpoint snapshot capture / reconnect-from-snapshot seeding",
    "_mqtt_url": "adapter's endpoint snapshot capture / reconnect-from-snapshot seeding",
    "_country": "adapter's reconnect-from-snapshot create() parity seeding",
    "_language": "adapter's reconnect-from-snapshot create() parity seeding",
    "subscribe_device": "adapter's device subscription",
    "unsubscribe_device": "adapter's device unsubscription",
    "net_stauts": "adapter's typo-tolerant network-status read",
    "_download": "adapter._patch_download()'s resp.status_code -> resp.status workaround",
}


def _fail(symbol: str, detail: str) -> str:
    return (
        f"karcher-home symbol {symbol!r} is missing or changed shape ({detail}). "
        f"Depended on by: {_WORKAROUND[symbol]}. Update the ALLOWED_PRIVATE_API "
        f"entry in tests/tools/check_imports.py, the private-API table in "
        f"ARCHITECTURE.md, and the adapter.py call site together."
    )


def test_karcher_home_bare_instance_attrs_present() -> None:
    """A bare KarcherHome() (no network) must still set every attribute
    adapter.py reads or writes directly on the instance."""
    raw = KarcherHome()
    for symbol in (
        "_mqtt",
        "_device_props",
        "_base_url",
        "_mqtt_url",
        "_country",
        "_language",
    ):
        assert hasattr(raw, symbol), _fail(symbol, "attribute not set by __init__")


def test_karcher_home_device_props_is_a_dict() -> None:
    """adapter.py treats _device_props as a plain dict (subscript, `in`, .pop())
    — confirm the shape, not just presence."""
    raw = KarcherHome()
    assert isinstance(raw._device_props, dict), _fail("_device_props", "not a dict")


def _positional_arity(func: object) -> int:
    sig = inspect.signature(func)  # type: ignore[arg-type]
    return len([p for p in sig.parameters if p != "self"])


def test_karcher_home_subscribe_device_signature() -> None:
    """subscribe_device(dev) — adapter calls it positionally with one Device arg."""
    assert hasattr(KarcherHome, "subscribe_device"), _fail("subscribe_device", "method removed")
    arity = _positional_arity(KarcherHome.subscribe_device)
    assert arity == 1, _fail("subscribe_device", f"expected 1 arg, found {arity}")


def test_karcher_home_unsubscribe_device_signature() -> None:
    """unsubscribe_device(dev) — symmetric counterpart to subscribe_device."""
    assert hasattr(KarcherHome, "unsubscribe_device"), _fail("unsubscribe_device", "method removed")
    arity = _positional_arity(KarcherHome.unsubscribe_device)
    assert arity == 1, _fail("unsubscribe_device", f"expected 1 arg, found {arity}")


def test_karcher_home_update_device_properties_signature() -> None:
    """_update_device_properties(sn, data) — adapter calls this directly to
    apply property/post pushes that karcher-home's own dispatch ignores."""
    assert hasattr(KarcherHome, "_update_device_properties"), _fail(
        "_update_device_properties", "method removed"
    )
    arity = _positional_arity(KarcherHome._update_device_properties)
    assert arity == 2, _fail(
        "_update_device_properties", f"expected 2 args (sn, data), found {arity}"
    )


def test_karcher_home_download_signature() -> None:
    """_download(url) -> bytes — _patch_download() replaces this method wholesale;
    a signature change here means the replacement patches the wrong shape."""
    assert hasattr(KarcherHome, "_download"), _fail("_download", "method removed")
    arity = _positional_arity(KarcherHome._download)
    assert arity == 1, _fail("_download", f"expected 1 arg (url), found {arity}")
    assert inspect.iscoroutinefunction(KarcherHome._download), _fail(
        "_download", "no longer a coroutine function"
    )


def test_mqtt_client_on_message_attribute() -> None:
    """adapter.py reads/writes `client._mqtt.on_message` once connected. _mqtt
    becomes a MqttClient instance only after login(); test the shape via a
    bare MqttClient() construction (no network I/O in __init__) instead of
    driving a real connection.

    Constructing paho's underlying Client with the (upstream-chosen) v1
    callback API emits a DeprecationWarning unrelated to the symbol we're
    checking; suppressed locally rather than repo-wide. The object is also
    dropped inside the same suppressed scope so its __del__ (paho's own
    cleanup, not ours) can't raise an unraisable-exception warning later,
    at an unrelated test's teardown.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        mqtt = MqttClient("host", 1883, "user", "pass")
        has_on_message = hasattr(mqtt, "on_message")
        del mqtt
    assert has_on_message, _fail("_mqtt.on_message", "MqttClient no longer exposes on_message")


def test_device_properties_net_stauts_typo_still_present() -> None:
    """net_stauts (sic) is adapter.py's typo-tolerant workaround for an upstream
    misspelling. If upstream fixes the typo, this assertion FAILS on purpose —
    that is the signal to remove the workaround and switch to net_status."""
    props = DeviceProperties()
    assert hasattr(props, "net_stauts"), _fail(
        "net_stauts",
        "the misspelled field is gone — upstream likely fixed the typo; "
        "switch adapter.py to the correctly-spelled net_status and drop this workaround",
    )


def test_product_enum_matches_adapter_model_names() -> None:
    """adapter._MODEL_NAMES is keyed by karcher.consts.Product member name and
    hardcodes the numeric product_id values as test constants (tests/contract/
    test_adapter.py). Pin both so an upstream enum change — a renamed member or
    a changed value — is caught here rather than silently mislabelling devices
    or breaking test_get_devices_derives_model_per_product's inputs.

    Asserts against _LIBRARY_PRODUCT — the enum as karcher-home actually ships it,
    captured by adapter.py before it patches karcher.consts.Product. Using the
    patched enum here would assert the adapter's own constants against themselves
    and pass no matter what upstream did. RVM4 is not upstream's, so it is checked
    in test_adapter_adds_rvm4_to_the_runtime_product_enum instead."""
    library = _LIBRARY_PRODUCT
    assert library("1528986273083777024") is library.RCV3, _fail(  # type: ignore[attr-defined]
        "Product.RCV3", "value 1528986273083777024 no longer resolves to RCV3"
    )
    assert library("1540149850806333440") is library.RCV5, _fail(  # type: ignore[attr-defined]
        "Product.RCV5", "value 1540149850806333440 no longer resolves to RCV5"
    )
    assert library("1599715149861306368") is library.RCF5, _fail(  # type: ignore[attr-defined]
        "Product.RCF5", "value 1599715149861306368 no longer resolves to RCF5"
    )


def test_library_product_enum_does_not_know_rvm4() -> None:
    """The reason adapter.py patches the enum at all. If a future pinned library
    adds RVM4 itself, this fails on purpose: the patch and its ARCHITECTURE.md
    workaround note can then be revisited."""
    with pytest.raises(ValueError, match="1946123509838999552"):
        _LIBRARY_PRODUCT("1946123509838999552")


def test_adapter_adds_rvm4_to_the_runtime_product_enum() -> None:
    """adapter._merged_product() extends the library enum with the IDs it lacks."""
    assert Product("1946123509838999552") is Product.RVM4


def test_merged_product_keeps_members_only_the_installed_library_has() -> None:
    """A hand-installed patched build (e.g. gucio1200/python-karcher, which adds
    models and still declares version 0.5.1, so HA won't reinstall over it) must
    keep its extra members. Replacing the enum instead of extending it silently
    turned that model into an account-wide UnsupportedDeviceError.

    FORK_ONLY_ID is deliberately an ID that appears in NO PROFILES row. An
    earlier version of this test used the fork's RVF7, which stopped proving
    anything the moment RVF7 joined the model table: the builder then re-added
    it under the same name whether it extended the fork or replaced it, so a
    replace-not-extend mutant passed. The fixture has to carry something only
    the installed library could supply.
    """
    fork_only_id = "1234567890123456789"
    assert profile_for(fork_only_id) is None, (
        "FORK_ONLY_ID leaked into PROFILES — pick another, or this test is vacuous"
    )

    class ForkProduct(StrEnum):
        RCV5 = "1540149850806333440"
        FORK_ONLY = fork_only_id

    merged = adapter._build_product_enum(ForkProduct)

    assert merged(fork_only_id).name == "FORK_ONLY"
    assert merged("1946123509838999552").name == "RVM4"  # contributed by PROFILES
    assert merged("1540149850806333440").name == "RCV5"  # in both, not duplicated


def test_builder_falls_back_to_a_strict_enum_if_the_recipe_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_build_product_enum` runs at import time inside a user's Home Assistant.

    The member-less-base + `_missing_` recipe leans on enum internals, so a
    future Python could break it. If that happens the integration must degrade
    to the old strict-enum behaviour — an unrecognised model failing the
    account, which is bad — rather than raising here, which would make the
    integration unimportable and take down every robot including working ones.

    Simulated by breaking `_LenientProduct` itself, which is the thing that
    would actually stop working. Bad *members* are a different case and are
    correctly fatal for both paths: the installed library could not have
    defined such a member either.
    """

    class BrokenRecipe:
        def __call__(self, *_args: object, **_kwargs: object) -> object:
            raise TypeError("simulated: the enum recipe no longer works")

    monkeypatch.setattr(adapter, "_LenientProduct", BrokenRecipe())

    merged = adapter._build_product_enum(_LIBRARY_PRODUCT)

    # Still a usable enum: known models resolve, and the table's IDs were added.
    assert merged("1540149850806333440").name == "RCV5"
    assert merged("1946123509838999552").name == "RVM4"
    # Strict again — this is the degradation, stated so nobody reads it as a pass.
    with pytest.raises(ValueError, match="9999999999999999999"):
        merged("9999999999999999999")


def test_display_name_survives_a_fork_renaming_the_mislabelled_rcf5() -> None:
    """Display name is looked up by product ID, never by enum member name.

    The pinned library calls 1599715149861306368 "RCF5"; Kärcher calls it RCF3
    (doc/PROTOCOL.md §16.7). A patched build that fixes the mislabel keeps its
    own member name, and the builder preserves it. Under the old member-name
    lookup that meant carrying both spellings in a dict; keying on the product
    ID makes the member name irrelevant, whichever fork is installed.
    """

    class RenamedFork(StrEnum):
        RCV5 = "1540149850806333440"
        RCF3 = "1599715149861306368"

    merged = adapter._build_product_enum(RenamedFork)
    assert merged("1599715149861306368").name == "RCF3"

    # Same answer regardless of which spelling the installed enum carries.
    assert display_name("1599715149861306368") == "RCF 3"


def test_device_init_accepts_rvm4_product_id() -> None:
    """RVM4 is not in the pinned karcher-home Product enum, but the adapter patches
    karcher.device.Product at import time so Device.__init__ can resolve it."""
    device = Device(product_id="1946123509838999552")
    assert device.product_id is Product.RVM4


def test_library_product_enum_still_raises_for_an_unrecognised_id() -> None:
    """The upstream canary, asserted against the enum as karcher-home ships it.

    This is why `_missing_` has to exist: upstream's Product is strict, and
    `Device.__init__` coerces it eagerly inside one list comprehension over the
    whole account (karcher/karcher.py), so a single unrecognised robot failed
    discovery for every device the user owned.

    If a future pinned library stops raising here, this FAILS on purpose — the
    signal that adapter.py's `except ValueError` and the blast-radius note in
    ARCHITECTURE.md are stale and should be revisited.
    """
    with pytest.raises(ValueError, match="9999999999999999999"):
        _LIBRARY_PRODUCT("9999999999999999999")


def test_patched_device_init_mints_a_pseudo_member_instead_of_raising() -> None:
    """The other half of the canary: with the adapter's enum patched in,
    Device.__init__ accepts an ID nobody has ever seen. This is the behaviour
    that stops one unknown robot from failing the whole account."""
    device = Device(product_id="9999999999999999999")

    assert device.product_id == "9999999999999999999"
    assert device.product_id.value == "9999999999999999999"
    assert device.product_id.name == "UNKNOWN_9999999999999999999"


def test_library_version_probe_reports_the_installed_version() -> None:
    """adapter.KARCHER_HOME_VERSION is the version diagnostics publishes.

    The previous probe looked for `karcher.__version__`, which `karcher/__init__.py`
    never defines, so it never read a version at all — it always took its "unknown"
    default, on every install ever shipped, and that placeholder looks like a real
    answer in a diagnostics dump. Asserted against importlib.metadata directly,
    which is an independent path to the same fact.
    """
    installed = metadata.version("karcher-home")

    assert installed == adapter.KARCHER_HOME_VERSION
    assert adapter.KARCHER_HOME_VERSION != "unknown"


def test_library_version_probe_falls_back_when_not_installed() -> None:
    """The distribution name is `karcher-home`, not the import name `karcher`.
    Probing the wrong one — or running against an install that lacks the
    metadata — must degrade to "unknown" rather than raise at import time."""
    assert adapter._library_version("karcher") == "unknown"
    assert adapter._library_version("no-such-distribution-9999") == "unknown"


def test_library_version_probe_survives_corrupt_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raise here would fail the whole integration at import time.

    metadata.version() documents only PackageNotFoundError, but it decodes
    METADATA off disk: a truncated or non-UTF-8 file raises UnicodeDecodeError
    (verified against a hand-built dist-info on 3.14.2). That is a plausible
    state on the SD-card installs this diagnostics field exists to help debug,
    so the probe must degrade to "unknown" instead of taking the integration
    down with it.
    """

    def boom(_name: str) -> str:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(adapter.metadata, "version", boom)
    assert adapter._library_version() == "unknown"


def test_library_version_probe_handles_metadata_without_a_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """METADATA with no `Version:` header makes metadata.version() return None,
    not raise — despite its `-> str` annotation, so mypy cannot catch it. Left
    unhandled that publishes a JSON null in the diagnostics dump."""
    monkeypatch.setattr(adapter.metadata, "version", lambda _name: None)
    assert adapter._library_version() == "unknown"


def test_conformance_suite_covers_full_allowlist() -> None:
    """Guard against drift: every symbol in check_imports.ALLOWED_PRIVATE_API
    must have a matching _WORKAROUND entry (and therefore a conformance check)
    in this file, so a newly-allowlisted symbol can't go unverified."""
    from tests.tools.check_imports import ALLOWED_PRIVATE_API

    missing = ALLOWED_PRIVATE_API - _WORKAROUND.keys()
    assert not missing, (
        f"tests/tools/check_imports.py ALLOWED_PRIVATE_API added new symbol(s) "
        f"{sorted(missing)} with no matching conformance check in this file — add one."
    )
