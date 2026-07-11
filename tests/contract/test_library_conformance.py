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

Runs in the normal CI job — karcher-home is a regular pip dependency here,
no robot needed. Not HIL-gated.
"""

from __future__ import annotations

import inspect
import warnings

from karcher.device import DeviceProperties
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
    "_wait_events": "adapter's prop.get reply-wait registration workaround",
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
        "_wait_events",
        "_base_url",
        "_mqtt_url",
        "_country",
        "_language",
    ):
        assert hasattr(raw, symbol), _fail(symbol, "attribute not set by __init__")


def test_karcher_home_device_props_and_wait_events_are_dicts() -> None:
    """adapter.py treats _device_props / _wait_events as plain dicts (subscript,
    `in`, .pop()) — confirm the shape, not just presence."""
    raw = KarcherHome()
    assert isinstance(raw._device_props, dict), _fail("_device_props", "not a dict")
    assert isinstance(raw._wait_events, dict), _fail("_wait_events", "not a dict")


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
