#!/usr/bin/env bash
# Setup mitmproxy CA cert as a system-trusted cert in a running Android emulator.
# For use on your own account and devices only.
#
# IMPORTANT: The emulator MUST be started with -writable-system, otherwise
# the system partition is read-only even with root.  This script will handle
# that automatically when given --start flag, or you can start it manually:
#
#   emulator -avd <avd_name> -writable-system &
#
# Requirements:
#   - AVD created with "Google APIs" image (NOT "Google Play"), API 28 or below.
#     Create in Android Studio: Device Manager → Create Device → select
#     "API 28 / Google APIs / x86" system image (no Google Play store icon).
#   - adb in PATH  (comes with Android Studio platform-tools)
#   - mitmproxy installed: pip install mitmproxy
#   - openssl in PATH (comes with macOS)
#
# Usage:
#   # Option A — let this script start the emulator:
#   ./tools/setup_emulator_proxy.sh --start <avd_name>
#
#   # Option B — you already started the emulator with -writable-system:
#   ./tools/setup_emulator_proxy.sh

set -euo pipefail

MITM_DIR="${HOME}/.mitmproxy"
CERT_PEM="${MITM_DIR}/mitmproxy-ca-cert.pem"
PROXY_PORT=8080
AVD_NAME=""
START_EMU=false

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --start) START_EMU=true; AVD_NAME="${2:-}"; shift 2 ;;
        --list-avds)
            echo "Available AVDs:"
            "${HOME}/Library/Android/sdk/emulator/emulator" -list-avds 2>/dev/null \
                || emulator -list-avds
            exit 0 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# ── Locate tools ──────────────────────────────────────────────────────────────
SDK_ROOT="${ANDROID_HOME:-${HOME}/Library/Android/sdk}"
export PATH="${SDK_ROOT}/platform-tools:${SDK_ROOT}/emulator:${PATH}"

echo "==> Checking mitmproxy..."
if ! command -v mitmdump &>/dev/null; then
    echo "mitmproxy not found. Installing..."
    pip install mitmproxy
fi

# Generate CA certs if they don't exist yet
if [[ ! -f "${CERT_PEM}" ]]; then
    echo "==> Generating mitmproxy CA certificates..."
    mitmdump --quiet &
    MITM_PID=$!
    sleep 3
    kill ${MITM_PID} 2>/dev/null || true
fi

echo "==> Checking adb..."
adb version

# ── Start emulator if requested ───────────────────────────────────────────────
if [[ "${START_EMU}" == true ]]; then
    if [[ -z "${AVD_NAME}" ]]; then
        echo "Available AVDs:"
        emulator -list-avds
        echo ""
        read -r -p "Enter AVD name: " AVD_NAME
    fi
    echo "==> Starting emulator '${AVD_NAME}' with -writable-system..."
    emulator -avd "${AVD_NAME}" -writable-system -no-snapshot-load &
    EMU_PID=$!
    echo "    emulator PID: ${EMU_PID}"
    echo "==> Waiting for device to boot..."
    adb wait-for-device
    # Wait until boot is complete
    until [[ "$(adb shell getprop sys.boot_completed 2>/dev/null)" == "1" ]]; do
        sleep 2; printf "."
    done
    echo " booted."
else
    echo "==> Waiting for emulator device..."
    adb wait-for-device
fi

# ── Install certificate ───────────────────────────────────────────────────────
HASH=$(openssl x509 -inform PEM -subject_hash_old -in "${CERT_PEM}" | head -1)
CERT_NAME="${HASH}.0"
echo "==> Certificate hash: ${HASH}  →  /system/etc/security/cacerts/${CERT_NAME}"

echo "==> Gaining root..."
adb root
sleep 2

echo "==> Remounting system partition as writable..."
# -writable-system flag is required when starting the emulator (see above).
# If this still fails, kill the emulator and use --start flag.
adb remount

echo "==> Pushing certificate..."
adb push "${CERT_PEM}" "/system/etc/security/cacerts/${CERT_NAME}"
adb shell chmod 644 "/system/etc/security/cacerts/${CERT_NAME}"

echo "==> Verifying..."
adb shell ls -la "/system/etc/security/cacerts/${CERT_NAME}"

HOST_IP="10.0.2.2"

echo ""
echo "============================================================"
echo "  Certificate installed!"
echo ""
echo "  1. Set emulator proxy (run this now):"
echo "     adb shell settings put global http_proxy ${HOST_IP}:${PROXY_PORT}"
echo ""
echo "  2. Start mitmproxy (separate terminal):"
echo "     mitmdump -s tools/mitm_karcher.py --listen-port ${PROXY_PORT} --ssl-insecure"
echo ""
echo "  3. Install the Kärcher APK:"
echo "     # Extract from your phone:"
echo "     adb -s <phone_serial> shell pm path com.kaercher.homerobots"
echo "     adb -s <phone_serial> pull /data/app/...base.apk karcher.apk"
echo "     adb install karcher.apk"
echo ""
echo "  4. Open Kärcher app in emulator → log in → press Start/Pause/Return."
echo "     All traffic to *.3irobotix.net appears in mitmdump."
echo ""
echo "  To remove proxy when done:"
echo "     adb shell settings delete global http_proxy"
echo "============================================================"
