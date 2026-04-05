"""
mitmproxy addon — capture Kärcher app REST commands
======================================================
For use on your own account and devices only.

Logs every HTTP request/response to/from the 3irobotix cloud that the Kärcher
app makes.  Run this while you press buttons in the app; command endpoints will
show up as POST/PUT requests with non-empty bodies.

Usage (run on your Mac, set phone Wi-Fi proxy to your Mac IP:8080):
    pip install mitmproxy
    mitmdump -s tools/mitm_karcher.py --listen-port 8080 --ssl-insecure

Certificate setup (Android):
    1. Install mitmproxy CA on the phone:
       - Browse to http://mitm.it on the phone → download Android cert
       - Settings → Security → Install certificate → CA certificate
    2. For Android 7+ (API 24+) user certs are NOT trusted by apps by default.
       Options:
         a) Use an emulator with API 23 or below
         b) Root the phone/emulator and install the cert as a SYSTEM cert:
              adb root && adb remount
              adb push ~/.mitmproxy/mitmproxy-ca-cert.cer /system/etc/security/cacerts/<hash>.0
              adb shell chmod 644 /system/etc/security/cacerts/<hash>.0
         c) Use Frida to bypass SSL pinning:
              frida -U -f com.kaercher.homerobots -l frida_bypass_ssl.js
"""

from mitmproxy import http

KARCHER_HOSTS = {"3irobotix.net", "kaercher.com"}


def _is_karcher(flow: http.HTTPFlow) -> bool:
    host = flow.request.pretty_host
    return any(h in host for h in KARCHER_HOSTS)


def request(flow: http.HTTPFlow) -> None:
    if not _is_karcher(flow):
        return

    body = flow.request.get_text(strict=False) or ""
    print(
        f"\n[→ REQUEST]  {flow.request.method} {flow.request.pretty_url}\n"
        f"  headers: {dict(flow.request.headers)}\n"
        f"  body:    {body[:2000]}"
    )


def response(flow: http.HTTPFlow) -> None:
    if not _is_karcher(flow):
        return

    body = flow.response.get_text(strict=False) or ""
    print(
        f"\n[← RESPONSE] {flow.request.method} {flow.request.pretty_url}\n"
        f"  status:  {flow.response.status_code}\n"
        f"  body:    {body[:2000]}"
    )
