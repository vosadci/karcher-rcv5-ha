"""
Probe for the REST command endpoint
=====================================
Commands go via REST (phone → cloud REST → cloud MQTT → robot).
This script tries likely command endpoint patterns against the authenticated
Kärcher cloud API and logs the responses.

Usage:
    KARCHER_EMAIL=you@example.com KARCHER_PASSWORD=secret \\
    KARCHER_DEVICE_SN=12696400049596 \\
    python tools/probe_rest_commands.py

Set KARCHER_DRY_RUN=1 to list candidates without sending anything.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
_LOGGER = logging.getLogger("probe")

KARCHER_EMAIL      = os.environ.get("KARCHER_EMAIL",      "YOUR_EMAIL_HERE")
KARCHER_PASSWORD   = os.environ.get("KARCHER_PASSWORD",   "YOUR_PASSWORD_HERE")
KARCHER_COUNTRY    = os.environ.get("KARCHER_COUNTRY",    "GB")
KARCHER_DEVICE_SN  = os.environ.get("KARCHER_DEVICE_SN",  "")
DRY_RUN            = os.environ.get("KARCHER_DRY_RUN",    "0") == "1"

# ── Candidate REST endpoints ──────────────────────────────────────────────────
# Previous run confirmed only /smart-home-service/smartHome/device/property/set
# exists (returned 892 signature error vs 404 for all others).
# 892 = genSign mismatch, caused by list values being str()-serialised instead
# of JSON-serialised in the signing code.  All variants below use dict or scalar
# values so they sign correctly.
_PROP_LIST = [{"name": "mode", "value": 1}]
_PROP_DICT = {"mode": 1}

CANDIDATES = [
    # ── service/invoke style (mirrors MQTT topic thing/service_invoke) ────────
    ("POST", "/smart-home-service/smartHome/device/service/invoke", {
        "deviceId": "{device_id}", "sn": "{sn}",
        "method": "service_invoke", "params": _PROP_DICT,
    }),
    ("POST", "/smart-home-service/smartHome/device/service/invoke", {
        "deviceId": "{device_id}", "sn": "{sn}", "params": _PROP_DICT,
    }),
    ("POST", "/smart-home-service/smartHome/device/thing/service/invoke", {
        "deviceId": "{device_id}", "sn": "{sn}", "params": _PROP_DICT,
    }),
    # ── path-param deviceId ───────────────────────────────────────────────────
    ("POST", "/smart-home-service/smartHome/device/{device_id}/service/invoke", {
        "sn": "{sn}", "params": _PROP_DICT,
    }),
    ("POST", "/smart-home-service/smartHome/device/{device_id}/invoke", {
        "sn": "{sn}", "params": _PROP_DICT,
    }),
    ("POST", "/smart-home-service/smartHome/device/{device_id}/command", {
        "sn": "{sn}", "params": _PROP_DICT,
    }),
    ("POST", "/smart-home-service/smartHome/device/{device_id}/property/set", {
        "sn": "{sn}", "properties": _PROP_LIST,
    }),
    # ── robot-specific paths ──────────────────────────────────────────────────
    ("POST", "/smart-home-service/smartHome/robot/serviceInvoke", {
        "deviceId": "{device_id}", "sn": "{sn}", "params": _PROP_DICT,
    }),
    ("POST", "/smart-home-service/smartHome/robot/command", {
        "deviceId": "{device_id}", "sn": "{sn}", "params": _PROP_DICT,
    }),
    ("POST", "/smart-home-service/smartHome/robot/setMode", {
        "deviceId": "{device_id}", "sn": "{sn}", "mode": 1,
    }),
    # ── DEV-api prefix (seen in Domains response) ─────────────────────────────
    ("POST", "/dev-service/device/service/invoke", {
        "deviceId": "{device_id}", "sn": "{sn}", "params": _PROP_DICT,
    }),
    ("POST", "/dev-service/device/property/set", {
        "deviceId": "{device_id}", "sn": "{sn}", "properties": _PROP_LIST,
    }),
    # ── product/sn in path ───────────────────────────────────────────────────
    ("POST", "/smart-home-service/smartHome/device/{product_id}/{sn}/invoke", {
        "params": _PROP_DICT,
    }),
    ("POST", "/smart-home-service/smartHome/device/{product_id}/{sn}/service/invoke", {
        "params": _PROP_DICT,
    }),
]
# ─────────────────────────────────────────────────────────────────────────────


def _sub(template, **kw):
    if isinstance(template, str):
        return template.format(**kw)
    if isinstance(template, dict):
        return {k: _sub(v, **kw) for k, v in template.items()}
    if isinstance(template, list):
        return [_sub(v, **kw) for v in template]
    return template


def _patched_request(client):
    """Return a _request coroutine with fixed list signing.

    python-karcher's _request uses str() on list values when building the
    signature string, producing Python repr instead of JSON.  This patch
    applies json.dumps to ALL non-string, non-None values so lists are
    serialised correctly.
    """
    import collections
    import urllib.parse
    from karcher.utils import get_nonce, get_timestamp, md5
    from karcher.consts import TENANT_ID

    async def _request(method, url, **kwargs):
        import aiohttp
        from karcher.consts import SSL_CERTIFICATE_THUMBPRINT

        headers = kwargs.pop("headers", {})
        headers["User-Agent"] = "Android_" + TENANT_ID
        auth = ""
        if client._session and client._session.auth_token:
            auth = client._session.auth_token
            headers["authorization"] = auth
        if client._session and client._session.user_id:
            headers["id"] = client._session.user_id
        headers["tenantId"] = TENANT_ID

        nonce = get_nonce()
        ts = str(get_timestamp())
        data = ""

        if method == "GET":
            params = kwargs.get("params") or {}
            if isinstance(params, str):
                params = urllib.parse.parse_qs(params)
            buf = urllib.parse.urlencode(params)
            data = buf
            kwargs["params"] = buf
        elif method in ("POST", "PUT"):
            v = kwargs.get("json") or {}
            if isinstance(v, dict):
                v = collections.OrderedDict(v.items())
                for key, val in v.items():
                    data += key
                    if val is None:
                        data += "null"
                    elif isinstance(val, str):
                        data += val
                    else:
                        # FIX: use json.dumps for both dicts AND lists
                        data += json.dumps(val, separators=(",", ":"))
                kwargs["json"] = v

        headers["sign"] = md5(auth + ts + nonce + data)
        headers["ts"] = ts
        headers["nonce"] = nonce
        kwargs["headers"] = headers
        kwargs["ssl"] = aiohttp.Fingerprint(SSL_CERTIFICATE_THUMBPRINT)

        return await client._http.request(method, client._base_url + url, **kwargs)

    return _request


async def main():
    from karcher.karcher import KarcherHome

    _LOGGER.info("Authenticating as %s...", KARCHER_EMAIL)
    client = await KarcherHome.create(country=KARCHER_COUNTRY)
    await client.login(KARCHER_EMAIL, KARCHER_PASSWORD)
    _LOGGER.info("Logged in  user_id=%s", client._session.user_id)

    # Patch _request to fix list signing
    import types
    client._request = types.MethodType(
        lambda self, method, url, **kw: _patched_request(self)(method, url, **kw),
        client,
    )
    # Simpler: just replace bound method
    _fixed = _patched_request(client)
    client._request = _fixed

    devices = await client.get_devices()
    if not devices:
        _LOGGER.error("No devices found.")
        return

    dev = devices[0]
    if KARCHER_DEVICE_SN:
        dev = next((d for d in devices if d.sn == KARCHER_DEVICE_SN), dev)

    _LOGGER.info("Using device: %s  sn=%s  device_id=%s  product_id=%s",
                 dev.nickname, dev.sn, dev.device_id, dev.product_id.value)

    subs = {
        "device_id": dev.device_id,
        "sn":        dev.sn,
        "product_id": dev.product_id.value,
    }

    for method, path_tpl, body_tpl in CANDIDATES:
        path = _sub(path_tpl, **subs)
        body = _sub(body_tpl, **subs)

        if DRY_RUN:
            _LOGGER.info("[DRY RUN] %s %s\n  body: %s", method, path, json.dumps(body))
            continue

        _LOGGER.info("Trying %s %s  body: %s", method, path, json.dumps(body))
        try:
            resp = await _fixed(method, path, json=body)
            raw = await resp.text()
            _LOGGER.info("  → HTTP %d  body: %s", resp.status, raw[:600])
            resp.close()

            try:
                data = json.loads(raw)
                if data.get("code") == 0:
                    _LOGGER.info("  ★★★ SUCCESS: %s %s", method, path)
                    _LOGGER.info("  ★★★ Body: %s", json.dumps(body, indent=2))
            except Exception:
                pass

        except Exception as exc:
            _LOGGER.warning("  → Error: %s", exc)

    await client.close()
    _LOGGER.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
