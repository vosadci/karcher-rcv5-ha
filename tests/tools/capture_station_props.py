# SPDX-License-Identifier: MIT
"""Capture raw MQTT property traffic to pin down Suction Station field values.

Answers the three open questions in doc/PROTOCOL.md §15.5:

  1. the real non-zero value of ``charge_station_type`` (station attached)
  2. the ``dust_action`` transitions during an empty cycle
  3. whether ``station_act`` as a property takes values other than 1

The integration's typed DTOs drop unknown fields, so this taps the raw
``on_message`` payloads instead and records everything verbatim.

Usage
-----
    # 1. robot docked, idle — establishes the baseline
    python tests/tools/capture_station_props.py --out docked.jsonl

    # 2. same, then trigger an empty and watch the transitions
    python tests/tools/capture_station_props.py --out emptying.jsonl --empty

Account email, password and serial number are prompted for at runtime and are
never read from argv or the environment, so they cannot end up in shell
history. The password is not echoed.

Ctrl-C to stop. Serial number and msgId are replaced with the placeholders
used by tests/fixtures/captures/ before anything is written to disk.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import json
import sys
import threading
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from custom_components.karcher_home_robots.adapter import (
    AdapterConfig,
    KarcherAdapter,
    _device_topic,
    _envelope,
)

# Fields §15.2 identifies; requested explicitly because the app polls
# charge_station_type rather than relying on push for it.
STATION_FIELDS = ("charge_station_type", "dust_action", "station_act")

# Enough context to correlate the station fields with what the robot is doing.
CONTEXT_FIELDS = ("status", "charge_state", "work_mode", "fault", "quantity")

SYNTH_SN = "SYNTH0000001"
SYNTH_MSG_ID = "1743175200000"

# Keys whose values are identifying and must never reach disk. The robot's
# net_status block carries its LAN IP and MAC, which a plain SN search-replace
# does not catch — these are redacted by key name instead.
REDACTED_KEYS: dict[str, str] = {
    "msgId": SYNTH_MSG_ID,
    "serial_number": SYNTH_SN,
    "sn": SYNTH_SN,
    "ip": "192.0.2.1",  # RFC 5737 documentation range
    "mac": "00:00:5e:00:53:00",  # RFC 7042 documentation range
}


class _ExecutorShim:
    """Stand-in for HomeAssistant outside HA.

    The adapter touches exactly one hass method — async_add_executor_job — so
    this is the whole surface needed to drive it from a plain script.
    """

    @staticmethod
    def async_add_executor_job(func: Any, *args: Any) -> Any:
        return asyncio.get_running_loop().run_in_executor(None, func, *args)


def _properties_of(parsed: Any) -> dict[str, Any] | None:
    """Pull the property dict out of either envelope shape.

    Push (``thing/event/property/post``) nests properties under ``params``;
    the ``prop.get`` reply (``thing/service/property/get_reply``) nests them
    under ``data`` instead — see karcher's ``_process_mqtt_message``. Reading
    only ``params`` would silently miss ``charge_station_type``, which is the
    one field the app polls rather than receives by push.
    """
    if not isinstance(parsed, dict):
        return None
    for key in ("params", "data"):
        value = parsed.get(key)
        if isinstance(value, dict):
            return value
    return None


def _redact(obj: Any, real_sn: str) -> Any:
    """Strip identifying values so the capture is safe to commit.

    Two passes are needed: a string replace for the serial number wherever it
    is embedded (topics, nested strings), and a by-key replace for values the
    serial search cannot reach — notably net_status.ip and net_status.mac.
    """
    if isinstance(obj, str):
        return obj.replace(real_sn, SYNTH_SN) if real_sn else obj
    if isinstance(obj, list):
        return [_redact(v, real_sn) for v in obj]
    if isinstance(obj, dict):
        return {
            k: (REDACTED_KEYS[k] if k in REDACTED_KEYS else _redact(v, real_sn))
            for k, v in obj.items()
        }
    return obj


class Recorder:
    """Appends every raw MQTT message to a JSONL file and reports station fields."""

    def __init__(self, path: Path, real_sn: str) -> None:
        self._path = path
        self._real_sn = real_sn
        self._lock = threading.Lock()
        self._seen: dict[str, Any] = {}
        self._context: dict[str, Any] = {}
        self._count = 0

    def record(self, topic: str, payload: bytes) -> None:
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError, TypeError, UnicodeDecodeError:
            # Map payloads and similar binaries are not JSON — skip rather than
            # abort; this tool only cares about the property stream.
            return

        line = {
            "topic": _redact(topic, self._real_sn),
            "payload": _redact(parsed, self._real_sn),
            "direction": "rx",
        }
        with self._lock:
            self._count += 1
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
            self._report(parsed)

    def _report(self, parsed: Any) -> None:
        """Print station fields whenever one appears or changes value."""
        props = _properties_of(parsed)
        if props is None:
            return

        # Track context separately from station fields: the --empty gate needs
        # the latest status even on messages that carry no station field.
        self._context.update({k: props[k] for k in CONTEXT_FIELDS if k in props})

        changed = {
            k: props[k] for k in STATION_FIELDS if k in props and self._seen.get(k) != props[k]
        }
        if not changed:
            return
        self._seen.update(changed)

        marks = " ".join(f"{k}={v!r}" for k, v in changed.items())
        ctx = " ".join(f"{k}={v}" for k, v in self._context.items())
        print(f"  [station] {marks}" + (f"    ({ctx})" if ctx else ""), flush=True)

    @property
    def docked(self) -> bool:
        """True if the last reported status was 4 (docked) — see PROTOCOL.md §15.3."""
        return self._context.get("status") == 4

    def summary(self) -> None:
        print(f"\nWrote {self._count} messages to {self._path}")
        if self._seen:
            print("Station fields observed:")
            for key in STATION_FIELDS:
                if key in self._seen:
                    print(f"  {key} = {self._seen[key]!r}")
            missing = [k for k in STATION_FIELDS if k not in self._seen]
            if missing:
                print(f"  never seen: {', '.join(missing)}")
        else:
            print(
                "No station fields seen in any message. If the station is attached, grep the\n"
                "JSONL directly — the robot may report them under an envelope shape this tool\n"
                "does not recognise:  grep -o 'charge_station_type[^,]*' " + str(self._path)
            )


def _property_get_payload() -> str:
    """prop.get for the station fields plus enough context to interpret them."""
    return _envelope("prop.get", {"property": [*STATION_FIELDS, *CONTEXT_FIELDS]})


def _prompt_credentials() -> tuple[str, str, str] | None:
    """Ask for account details at runtime.

    Deliberately reads neither argv nor the environment: both `export VAR=...`
    and `cmd --password=...` are recorded in shell history, which is exactly
    what this avoids. Returns None if anything is missing or unavailable.
    """
    if not sys.stdin.isatty():
        print(
            "stdin is not a terminal — this tool prompts for credentials interactively\n"
            "and will not read them from the environment or argv.",
            file=sys.stderr,
        )
        return None

    try:
        email = input("Kärcher account email: ").strip()
        password = getpass.getpass("Password (not echoed): ")
        sn = input("Robot serial number (SN): ").strip()
    except EOFError:
        print("\nAborted.", file=sys.stderr)
        return None

    if not (email and password and sn):
        print("Email, password and serial number are all required.", file=sys.stderr)
        return None
    return email, password, sn


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="JSONL output path")
    parser.add_argument(
        "--empty",
        action="store_true",
        help="trigger a manual empty (start_station_act) after the baseline poll",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=30.0,
        help="seconds between prop.get polls (default: 30)",
    )
    parser.add_argument(
        "--region",
        default="eu",
        help="account region (default: eu). Not sensitive — safe on the command line.",
    )
    return parser.parse_args()


def _install_tap(adapter: KarcherAdapter, recorder: Recorder) -> tuple[Any, Any]:
    """Chain a recording tap in front of the adapter's MQTT dispatcher.

    Returns (mqtt, previous_handler) so the caller can restore it on exit.
    Reaches into adapter internals deliberately: this is a research tool, and
    the typed push callback would have already discarded the unknown fields.
    """
    mqtt = adapter._client._mqtt
    previous = mqtt.on_message

    def _tap(topic: str, payload: bytes) -> None:
        with contextlib.suppress(Exception):
            recorder.record(topic, payload)
        if previous is not None:
            previous(topic, payload)

    mqtt.on_message = _tap
    return mqtt, previous


async def main() -> int:
    args = _parse_args()

    # Check the output path before prompting, so a stale path does not waste
    # the user's typing.
    if args.out.exists():
        print(f"{args.out} already exists — refusing to append to it.", file=sys.stderr)
        return 2

    credentials = _prompt_credentials()
    if credentials is None:
        return 2
    email, password, sn = credentials

    adapter = KarcherAdapter(_ExecutorShim(), AdapterConfig(region=args.region))  # type: ignore[arg-type]
    recorder = Recorder(args.out, sn)

    await adapter.async_setup()
    await adapter.authenticate(email, password)
    devices = await adapter.get_devices()
    device = next((d for d in devices if d.sn == sn), None)
    if device is None:
        # SN deliberately not echoed, matching the repo rule that it never
        # appears in output; the account has these serials instead:
        print("That serial number is not on this account.", file=sys.stderr)
        print(f"Found {len(devices)} device(s) with SN ending: ", file=sys.stderr, end="")
        print(", ".join(f"…{d.sn[-4:]}" for d in devices) or "(none)", file=sys.stderr)
        await adapter.close()
        return 1

    # Subscribe first so the adapter installs its dispatcher, then chain ours in
    # front of it — the adapter's handler keeps working untouched.
    await adapter.subscribe(device, lambda _props: None)
    mqtt, previous = _install_tap(adapter, recorder)

    # Matches adapter._fetch_properties_sync; note service *invocations* use a
    # different prefix (service_invoke/), which is why the empty command below
    # goes through adapter.send_command rather than being hand-rolled here.
    get_topic = _device_topic(device.product_id, sn, "service/property/get")

    print(f"Capturing to {args.out} — Ctrl-C to stop.")
    print("Polling for station fields; move/dock the robot to see transitions.\n")

    loop = asyncio.get_running_loop()
    try:
        # Baseline poll: charge_station_type is poll-driven in the app.
        await loop.run_in_executor(None, mqtt.publish, get_topic, _property_get_payload())
        await asyncio.sleep(3)

        if args.empty:
            # The app only enables the empty button while docked (status == 4).
            # Sending it otherwise yields a rejected command and a useless capture.
            if not recorder.docked:
                print(
                    "  !! skipping --empty: robot does not report status=4 (docked).\n"
                    "     Dock it and re-run. Capture continues regardless.\n",
                    flush=True,
                )
            else:
                print(
                    "  -> sending start_station_act {station_act: 3, ctrl_value: 1}\n", flush=True
                )
                await adapter.send_command(
                    device, "start_station_act", {"station_act": 3, "ctrl_value": 1}
                )

        while True:
            await asyncio.sleep(args.poll_interval)
            await loop.run_in_executor(None, mqtt.publish, get_topic, _property_get_payload())
    except KeyboardInterrupt, asyncio.CancelledError:
        pass
    finally:
        mqtt.on_message = previous
        with contextlib.suppress(Exception):
            await adapter.close()
        recorder.summary()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
