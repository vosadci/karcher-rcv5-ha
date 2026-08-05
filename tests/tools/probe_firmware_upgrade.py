# SPDX-License-Identifier: MIT
"""Probe the OTA endpoint to learn what image it serves for a given version code.

Background (doc/PROTOCOL.md §9, §11): this repo's static analysis originally covered
only ``I3.12.26``, a 2022 build obtained by asking ``tryUpgrade`` with
``curVersionCode: "0"``. That was believed to mean "return the latest". It does
not — a live RCV5 runs ``I3.12.90`` and the cloud offers it no upgrade, so
``.90`` is the newest published build while ``0`` yields the factory baseline.
``.90`` has since been extracted and audited too (§9.3) — the version gap is closed.

Answered 2026-08-04: the server walks an upgrade chain, returning the newest
build that supersedes the code passed. ``0`` yields the baseline ``.26``; any
code in ``26..89`` yields the current ``.90``; ``90`` returns error 838
("no matching package configuration policy") because nothing supersedes it.
The package arrives under the top-level ``result`` key — reading ``data``
instead makes every success look like an empty response.

READ-ONLY. This calls exactly one REST endpoint, ``POST
/upgrade-service/firmware/tryUpgrade``, which returns firmware metadata and a
download URL. It downloads nothing, publishes no MQTT, and cannot start an
update on the robot — the real OTA trigger is a separate MQTT path
(``ota/service/upgrade/...``), which this script never touches.

Usage
-----
    python tests/tools/probe_firmware_upgrade.py
    python tests/tools/probe_firmware_upgrade.py --codes 0,26,50,89,90

Credentials are prompted for at runtime and are never read from argv or the
environment, so they cannot end up in shell history.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from custom_components.karcher_home_robots.adapter import AdapterConfig, KarcherAdapter

TRY_UPGRADE = "/upgrade-service/firmware/tryUpgrade"

# Version codes worth probing by default: 0 (the value that produced the stored
# baseline), a few points along the way, and just below the known-current 90.
DEFAULT_CODES = (0, 26, 27, 50, 89, 90)


class _ExecutorShim:
    """Stand-in for HomeAssistant; the adapter only calls async_add_executor_job."""

    @staticmethod
    def async_add_executor_job(func: Any, *args: Any) -> Any:
        return asyncio.get_running_loop().run_in_executor(None, func, *args)


def _prompt_credentials() -> tuple[str, str] | None:
    """Ask for account details at runtime, keeping them out of shell history."""
    if not sys.stdin.isatty():
        print(
            "stdin is not a terminal — this tool prompts for credentials interactively.",
            file=sys.stderr,
        )
        return None
    try:
        email = input("Kärcher account email: ").strip()
        password = getpass.getpass("Password (not echoed): ")
    except EOFError:
        print("\nAborted.", file=sys.stderr)
        return None
    if not (email and password):
        print("Email and password are both required.", file=sys.stderr)
        return None
    return email, password


def _shorten(url: str) -> str:
    """Keep the filename, drop the host and long query string."""
    if not url:
        return "(no url)"
    return url.rsplit("/", maxsplit=1)[-1].split("?", maxsplit=1)[0] or url


async def _try_upgrade(
    client: Any, device: Any, code: int, package_type: str = "host_fw"
) -> dict[str, Any] | None:
    """One tryUpgrade call. Returns the parsed payload, or None on error."""
    body = {
        "productId": device.product_id,
        "productModelCode": device.product_mode_code,
        "curVersionCode": str(code),
        "packageType": package_type,
        "username": device.sn,
        "phoneBrand": "android",
    }
    try:
        resp = await client._request("POST", TRY_UPGRADE, json=body)
        payload: dict[str, Any] = await resp.json()
    except Exception as exc:
        # Broad by design: one bad code should report and continue, not abort the sweep.
        print(f"  {code:>4}  ERROR: {type(exc).__name__}: {exc}")
        return None
    return payload


def _report(code: int, payload: dict[str, Any] | None, *, raw: bool = False) -> str | None:
    """Print one row; return the offered version name, if any."""
    if payload is None:
        return None
    if raw:
        print(f"  {code:>4}  raw: {payload}")

    # The server nests the package under "result". An earlier version of this
    # probe read only "data" and so reported every successful response as
    # "nothing offered" — the exact opposite of the truth.
    data = payload.get("result") or payload.get("data")
    if not data:
        # Distinguish "success, nothing to offer" from a server-side error:
        # both arrive without a data block, and conflating them hid the real
        # answer on the first run of this probe.
        status = payload.get("code")
        msg = payload.get("msg") or payload.get("message") or ""
        if status not in (0, None):
            print(f"  {code:>4}  !! server error code={status}: {msg or '(no message)'}")
        else:
            keys = ",".join(sorted(payload)) or "(empty payload)"
            print(f"  {code:>4}  —  no data returned (code={status}, msg={msg or 'none'}) [{keys}]")
        return None

    if isinstance(data, list):
        data = data[0] if data else {}
    version_name = data.get("versionName") or data.get("version_name") or "?"
    version_code = data.get("versionCode") or data.get("version") or "?"
    url = data.get("packageUrl") or data.get("url") or data.get("downloadUrl") or ""
    md5 = data.get("md5") or ""
    offer = f"{version_name} (code {version_code})  md5={md5 or '?'}"
    print(f"  {code:>4}  -> {offer}  {_shorten(url)}")
    return str(version_name)


async def _choose_device(client: Any, devices: list[Any], requested: int | None) -> int | None:
    """List devices with their reported versions and resolve which to probe.

    Returns None (after explaining why) if the choice is ambiguous or invalid.
    """
    raw = await client.get_devices()

    print(f"{len(devices)} device(s) on this account:")
    for idx, dev in enumerate(devices):
        match = next((d for d in raw if str(d.sn) == dev.sn), None)
        vers = " ".join(
            f"{v.package_type}={v.version_name}({v.version})"
            for v in (getattr(match, "versions", []) or [])
        )
        print(
            f"  [{idx}] {dev.nickname or '(unnamed)'}  product={dev.product_id}  "
            f"sn=…{dev.sn[-4:]}  {vers or '(no versions reported)'}"
        )

    if requested is not None:
        if not 0 <= requested < len(devices):
            print(f"--device must be 0..{len(devices) - 1}", file=sys.stderr)
            return None
        return requested
    if len(devices) == 1:
        return 0
    # Never silently pick one when several exist — the probe result is
    # meaningless if it ran against the wrong robot.
    print("\nSeveral devices present; re-run with --device N to choose.", file=sys.stderr)
    return None


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_codes = ",".join(str(c) for c in DEFAULT_CODES)
    parser.add_argument(
        "--codes",
        default=default_codes,
        help=f"comma-separated curVersionCode values (default: {default_codes})",
    )
    parser.add_argument("--region", default="eu", help="account region (default: eu)")
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="index of the device to probe (required when the account has several)",
    )
    parser.add_argument("--raw", action="store_true", help="dump each full JSON response")
    parser.add_argument(
        "--package-type",
        default="host_fw",
        help="packageType to query (default: host_fw)",
    )
    args = parser.parse_args()

    try:
        codes = [int(c) for c in args.codes.split(",") if c.strip()]
    except ValueError:
        print("--codes must be a comma-separated list of integers.", file=sys.stderr)
        return 2

    credentials = _prompt_credentials()
    if credentials is None:
        return 2
    email, password = credentials

    adapter = KarcherAdapter(_ExecutorShim(), AdapterConfig(region=args.region))  # type: ignore[arg-type]
    await adapter.async_setup()
    try:
        await adapter.authenticate(email, password)
        devices = await adapter.get_devices()
        if not devices:
            print("No devices on this account.", file=sys.stderr)
            return 1
        client = adapter._client
        index = await _choose_device(client, devices, args.device)
        if index is None:
            return 2

        device = devices[index]
        print(f"\nProbing device [{index}] (sn …{device.sn[-4:]}).")

        print(f"Probing {TRY_UPGRADE} packageType={args.package_type!r} (read-only):")
        print("  code  offered")
        offered = {
            code: _report(
                code,
                await _try_upgrade(client, device, code, args.package_type),
                raw=args.raw,
            )
            for code in codes
        }

        distinct = {v for v in offered.values() if v}
        print("\nConclusion:")
        if not distinct:
            print("  The endpoint offered nothing for any probed code.")
        elif len(distinct) == 1:
            only = next(iter(distinct))
            print(f"  Every probed code returned the same image ({only}).")
            print("  => this endpoint serves one fixed image, not an upgrade chain.")
            print("     A newer build is not obtainable here; it is likely pushed to the")
            print("     device over MQTT instead (ota/service/upgrade/...).")
        else:
            print(f"  Different codes returned different images: {sorted(distinct)}")
            print("  => the server walks an upgrade chain; the newest image is reachable")
            print("     by probing upward from the running version code.")
    finally:
        with contextlib.suppress(Exception):
            await adapter.close()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
