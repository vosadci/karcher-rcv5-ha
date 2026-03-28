"""
Fetch OTA firmware update URL and download the firmware image.
=============================================================
Authenticates with the Kärcher cloud, calls the OTA check endpoint,
and downloads the firmware image if one is available.

Usage:
    KARCHER_EMAIL=you@example.com KARCHER_PASSWORD=secret \\
    KARCHER_DEVICE_SN=12696400029226 \\
    python tools/fetch_ota.py

The firmware image (if found) is saved to /tmp/karcher_firmware.*
and its contents are listed / analysed automatically.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
import zipfile

import aiohttp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
_LOGGER = logging.getLogger("fetch_ota")

KARCHER_EMAIL     = os.environ.get("KARCHER_EMAIL",     "YOUR_EMAIL_HERE")
KARCHER_PASSWORD  = os.environ.get("KARCHER_PASSWORD",  "YOUR_PASSWORD_HERE")
KARCHER_COUNTRY   = os.environ.get("KARCHER_COUNTRY",   "EU")
KARCHER_DEVICE_SN = os.environ.get("KARCHER_DEVICE_SN", "12696400029226")

# OTA endpoint discovered in APK strings
_OTA_PATH = "/service-publish/open/upgrade/try_upgrade"
_OTA_BASE = "https://ota.3irobotix.net:8001"


async def main() -> None:
    from karcher.karcher import KarcherHome
    from karcher.consts import TENANT_ID

    _LOGGER.info("Authenticating as %s (country=%s)...", KARCHER_EMAIL, KARCHER_COUNTRY)
    client = await KarcherHome.create(country=KARCHER_COUNTRY)
    await client.login(KARCHER_EMAIL, KARCHER_PASSWORD)
    _LOGGER.info("Logged in. user_id=%s", client._session.user_id)

    devices = await client.get_devices()
    dev = next((d for d in devices if d.sn == KARCHER_DEVICE_SN), devices[0] if devices else None)
    if dev is None:
        _LOGGER.error("No devices found.")
        return
    _LOGGER.info("Device: %s  sn=%s  product_id=%s", dev.nickname, dev.sn, dev.product_id.value)

    # Build OTA check request matching BaseUrlReq from MainActivity.java:
    #   new BaseUrlReq(tenantId, projectType, versionName, versionCode, username)
    #   baseUrlReq.setRobotType("sweeper")
    #
    # Confirmed values from APK decompilation:
    #   robotType   = "sweeper"          (hardcoded in MainActivity)
    #   projectType = "android_iot.karcher" (IotBase.projectType constant)
    #   factoryId   = TENANT_ID
    #   username    = account phone number (we use email as fallback)
    payload = {
        "factoryId":       TENANT_ID,
        "projectType":     "android_iot.karcher",
        "robotType":       "sweeper",
        "versionName":     "1.4.32",
        "versionCode":     10432,
        "username":        KARCHER_EMAIL,
        "packageVersions": [{"packageType": "android", "version": 10432}],
        # Also include device identifiers in case the server filters by them
        "sn":              dev.sn,
        "productId":       dev.product_id.value,
        "deviceId":        dev.device_id,
        "tenantId":        TENANT_ID,
    }

    headers = {
        "User-Agent": f"Android_{TENANT_ID}",
        "tenantId": TENANT_ID,
        "authorization": client._session.auth_token or "",
        "id": client._session.user_id or "",
        "Content-Type": "application/json",
    }

    # REST API base URL (uses the signed REST API, not the OTA CDN server)
    rest_base = f"https://eu-appaiot.3irobotix.net"

    # Firmware OTA check endpoint: POST /upgrade-service/firmware/tryUpgrade
    # Source: @POST annotation in CommonApiService.java
    # Response fields: packageUrl, versionCode, versionName, md5, packageSize, publishDesc
    # FirmwareOtaReq constructor (from RobotUpgradeActivity.java):
    #   new FirmwareOtaReq(curVersionCode, "host_fw", productId, getModeType(), deviceSn, null, 32, null)
    # dev.product_mode_code == getModeType() == modeType field from device list REST response
    # username is the device SN (not the user's email)
    firmware_payload = {
        "productId":        dev.product_id.value,
        "productModelCode": dev.product_mode_code,  # getModeType() from DeviceInfo
        "curVersionCode":   "0",                    # 0 = always return latest
        "packageType":      "host_fw",              # from RobotUpgradeActivity.java
        "username":         dev.sn,                 # device serial number, not email
        "phoneBrand":       "android",
    }
    _LOGGER.info("product_mode_code=%s  sn=%s", dev.product_mode_code, dev.sn)

    # CDN endpoint discovery endpoints (try_upgrade and try_upgrade2 from CommonApiService.java)
    # These return CDN server lists, NOT firmware URLs — kept here for reference.
    cdn_endpoints = [_OTA_PATH, "/service-publish/open/upgrade/try_upgrade2"]

    async with aiohttp.ClientSession() as session:
        # ── 1. Robot firmware check (most likely to contain packageUrl) ──────────
        fw_url_path = "/upgrade-service/firmware/tryUpgrade"
        _LOGGER.info("=== Firmware OTA check: %s%s ===", rest_base, fw_url_path)
        _LOGGER.info("Payload: %s", json.dumps(firmware_payload, indent=2))
        # Use python-karcher's signed _request (same signing used for all REST calls)
        try:
            resp = await client._request("POST", fw_url_path, json=firmware_payload)
            raw = await resp.text()
            _LOGGER.info("HTTP %d  response:\n%s", resp.status, raw[:2000])
            resp.close()
            data = json.loads(raw)
            result = data.get("result") or {}
            fw_url = result.get("packageUrl") if isinstance(result, dict) else None
            fw_url = fw_url or _find_url(data)
            if fw_url:
                _LOGGER.info("★ Found firmware packageUrl: %s", fw_url)
                async with aiohttp.ClientSession() as dl_session:
                    await _download_and_analyse(dl_session, fw_url)
            else:
                _LOGGER.info("No packageUrl in firmware response (code=%s result=%s).",
                             data.get("code"), result)
        except Exception as exc:
            _LOGGER.error("Firmware OTA request failed: %s", exc)

        # ── 2. CDN endpoint discovery (returns server lists, not firmware) ───────
        for path in cdn_endpoints:
            url = _OTA_BASE + path
            _LOGGER.info("=== CDN check: %s ===", url)
            try:
                async with session.post(
                    url, json=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    raw = await resp.text()
                    _LOGGER.info("HTTP %d  response:\n%s", resp.status, raw[:1000])
            except Exception as exc:
                _LOGGER.error("CDN request failed: %s", exc)

    await client.close()


def _find_url(obj, _depth=0) -> str | None:
    """Recursively search a JSON object for anything that looks like a download URL."""
    if _depth > 6:
        return None
    if isinstance(obj, str):
        if obj.startswith("http") and any(
            ext in obj for ext in (".zip", ".tar", ".bin", ".img", ".gz", ".pak", "firmware", "upgrade", "ota")
        ):
            return obj
        return None
    if isinstance(obj, dict):
        for v in obj.values():
            found = _find_url(v, _depth + 1)
            if found:
                return found
    if isinstance(obj, list):
        for item in obj:
            found = _find_url(item, _depth + 1)
            if found:
                return found
    return None


async def _download_and_analyse(session: "aiohttp.ClientSession", url: str) -> None:
    _LOGGER.info("Downloading firmware from %s ...", url)
    out_path = "/tmp/karcher_firmware"

    async with session.get(url, timeout=aiohttp.ClientTimeout(total=300)) as resp:
        if resp.status != 200:
            _LOGGER.error("Download failed: HTTP %d", resp.status)
            return
        content_type = resp.headers.get("Content-Type", "")
        data = await resp.read()
        _LOGGER.info("Downloaded %d bytes  content-type=%s", len(data), content_type)

    # Save raw file
    raw_path = out_path + ".bin"
    with open(raw_path, "wb") as f:
        f.write(data)
    _LOGGER.info("Saved to %s", raw_path)

    # Detect and unpack
    _analyse_firmware(data, raw_path)


def _analyse_firmware(data: bytes, raw_path: str) -> None:
    _LOGGER.info("=== Firmware analysis ===")

    # ZIP?
    if data[:2] == b"PK":
        _LOGGER.info("Format: ZIP")
        try:
            with zipfile.ZipFile(raw_path) as zf:
                names = zf.namelist()
                _LOGGER.info("Contents (%d files):", len(names))
                for n in names[:60]:
                    info = zf.getinfo(n)
                    _LOGGER.info("  %8d  %s", info.file_size, n)
                if len(names) > 60:
                    _LOGGER.info("  ... (%d more)", len(names) - 60)
                # Extract to /tmp/karcher_fw_extracted/
                extract_dir = "/tmp/karcher_fw_extracted"
                zf.extractall(extract_dir)
                _LOGGER.info("Extracted to %s", extract_dir)
                _scan_extracted(extract_dir)
        except Exception as e:
            _LOGGER.error("ZIP unpack failed: %s", e)
        return

    # Rockchip RKFW update.img?
    if data[:4] == b"RKFW":
        _LOGGER.info("Format: Rockchip RKFW update.img")
        _LOGGER.info("Header: version=%s", data[4:8].hex())
        _unpack_rkfw(data, raw_path)
        return

    # squashfs?
    if data[:4] == b"sqsh" or data[:4] == b"hsqs":
        _LOGGER.info("Format: squashfs")
        _LOGGER.info("Run: sudo unsquashfs -d /tmp/karcher_squash %s", raw_path)
        return

    # gzip?
    if data[:2] == b"\x1f\x8b":
        _LOGGER.info("Format: gzip")
        gz_path = raw_path + ".gz"
        import shutil
        shutil.copy(raw_path, gz_path)
        subprocess.run(["gunzip", "-f", gz_path])
        _LOGGER.info("Decompressed to %s", raw_path)
        with open(raw_path, "rb") as f:
            _analyse_firmware(f.read(), raw_path)
        return

    # Generic: print magic bytes and strings containing cert/mqtt/ssl keywords
    _LOGGER.info("Format: unknown (magic: %s)", data[:16].hex())
    _LOGGER.info("Searching for relevant strings...")
    _search_firmware_strings(raw_path)


def _search_firmware_strings(path: str) -> None:
    """Run strings and filter for meaningful MQTT/TLS/cert hits (whole-word or long patterns)."""
    import re
    result = subprocess.run(["strings", "-n", "8", path], capture_output=True, text=True)
    # Require the keyword to appear as a recognisable word (not embedded in random binary noise).
    # Use whole-word boundary or min-length anchoring.
    pattern = re.compile(
        r'(?i)'
        r'(?:mqtt|broker|3irobotix|eu-gam|eu-mq|cafile|cacert|ca_cert|ca_file'
        r'|tls_insecure|ssl_verify|verify_peer|verify_host'
        r'|BEGIN CERT|BEGIN RSA|BEGIN EC|-----'
        r'|\.pem|\.bks|\.crt|\.p12'
        r'|8883|1883|2883'
        r'|mosquitto|paho)'
    )
    relevant = [l for l in result.stdout.splitlines() if pattern.search(l)]
    _LOGGER.info("Relevant strings (%d):", len(relevant))
    for line in relevant[:120]:
        _LOGGER.info("  %s", line)


def _unpack_rkfw(data: bytes, raw_path: str) -> None:
    """Parse a Rockchip RKFW update.img and extract embedded partition images.

    RKFW layout (all little-endian):
      0x00  4B  magic "RKFW"
      0x04  4B  version
      0x08  4B  merge version
      0x0C  4B  date  (BCD YYYYMMDD)
      0x10  4B  chip  (e.g. 0x110 = RV1126)
      0x14  4B  image type
      0x18  4B  number of partitions (used only in RKAF sub-images)
      ...
      The main payload is an RKAF "Android Firmware" block starting with magic "RKAF".
      RKAF header at offset 0x66 in many images, or searchable by magic.
    """
    import struct, os

    _LOGGER.info("Searching for RKAF sub-image within RKFW...")
    rkaf_offset = data.find(b"RKAF")
    if rkaf_offset == -1:
        _LOGGER.warning("No RKAF sub-image found inside RKFW; trying direct string search.")
        _search_firmware_strings(raw_path)
        return

    _LOGGER.info("RKAF sub-image at offset 0x%x (%d)", rkaf_offset, rkaf_offset)
    af = data[rkaf_offset:]

    # RKAF header:
    #   0x00  4B  "RKAF"
    #   0x04  4B  total length
    #   0x08  32B manufacturer
    #   0x28  32B model
    #   0x48  4B  version (BCD MMDDYYYY)
    #   0x4C  4B  number of partition entries
    #   0x50  start of partition table (entry = 32+4+4+4+4 bytes)
    try:
        n_parts = struct.unpack_from("<I", af, 0x4C)[0]
        _LOGGER.info("RKAF partitions: %d", n_parts)
    except Exception:
        _LOGGER.warning("Could not parse RKAF partition count.")
        _search_firmware_strings(raw_path)
        return

    # Each partition entry (92 bytes total):
    #   0x00  32B  name (null-terminated)
    #   0x20  32B  file name (null-terminated)
    #   0x40  4B   flash offset (sectors × 512)
    #   0x44  4B   flash size   (sectors × 512)
    #   0x48  4B   file offset within RKAF (bytes from start of RKAF)
    #   0x4C  4B   file size (bytes)
    ENTRY_SIZE = 0x5C
    table_offset = 0x50
    extract_dir = "/tmp/karcher_rkfw"
    os.makedirs(extract_dir, exist_ok=True)
    _LOGGER.info("Extracting partitions to %s ...", extract_dir)

    for i in range(min(n_parts, 32)):
        entry_off = table_offset + i * ENTRY_SIZE
        if entry_off + ENTRY_SIZE > len(af):
            break
        entry = af[entry_off:entry_off + ENTRY_SIZE]
        name     = entry[0x00:0x20].rstrip(b"\x00").decode("latin-1", "replace")
        filename = entry[0x20:0x40].rstrip(b"\x00").decode("latin-1", "replace")
        file_off = struct.unpack_from("<I", entry, 0x48)[0]
        file_sz  = struct.unpack_from("<I", entry, 0x4C)[0]
        _LOGGER.info("  [%02d] %-20s  file=%-30s  off=0x%08x  size=%d",
                     i, name, filename, file_off, file_sz)
        if file_sz == 0 or file_off == 0:
            continue
        part_data = af[file_off:file_off + file_sz]
        out_name = filename if filename else f"part_{i:02d}_{name}"
        out_path = os.path.join(extract_dir, out_name)
        try:
            with open(out_path, "wb") as f:
                f.write(part_data)
        except Exception as e:
            _LOGGER.warning("    could not write %s: %s", out_path, e)

    _LOGGER.info("Done extracting. Scanning partitions for MQTT/TLS config...")
    _scan_extracted(extract_dir)

    # Also run string search on full image for quick overview
    _LOGGER.info("--- String search on full RKFW image ---")
    _search_firmware_strings(raw_path)


def _scan_extracted(directory: str) -> None:
    """Scan an extracted firmware directory for MQTT/TLS configuration and binaries."""
    import os

    _LOGGER.info("=== Scanning extracted firmware ===")

    # Look for cert files
    for root, dirs, files in os.walk(directory):
        for fname in files:
            fpath = os.path.join(root, fname)
            rel = fpath[len(directory):]
            lower = fname.lower()

            if any(ext in lower for ext in [".pem", ".crt", ".cer", ".key", ".bks", ".p12", ".der"]):
                size = os.path.getsize(fpath)
                _LOGGER.info("  CERT FILE: %s  (%d bytes)", rel, size)
                # Try to parse as X.509
                r = subprocess.run(
                    ["openssl", "x509", "-in", fpath, "-text", "-noout"],
                    capture_output=True, text=True
                )
                if r.returncode == 0:
                    for line in r.stdout.splitlines():
                        if any(x in line for x in ["Issuer", "Subject", "Not After"]):
                            _LOGGER.info("    %s", line.strip())

            if any(kw in lower for kw in ["mqtt", "mosquitto", "paho", "broker"]):
                _LOGGER.info("  MQTT FILE: %s", rel)
                # Scan for relevant strings
                r = subprocess.run(["strings", fpath], capture_output=True, text=True)
                for line in r.stdout.splitlines():
                    if any(kw in line.lower() for kw in
                           ["3irobotix", "verify", "ssl_verify", "tls_insecure", "8883", "cafile"]):
                        _LOGGER.info("    string: %s", line)


if __name__ == "__main__":
    asyncio.run(main())
