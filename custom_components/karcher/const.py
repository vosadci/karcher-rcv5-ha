"""Constants for the Kärcher Home Robots integration."""
from __future__ import annotations

DOMAIN = "karcher"

CONF_COUNTRY = "country"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_SN = "device_sn"
CONF_DEVICE_NICKNAME = "device_nickname"

# Regions shown in config flow
REGIONS = {
    "EU": "Europe",
    "US": "United States",
    "CN": "China",
}

# work_mode values observed via traffic capture (2026-03-28)
# Primary state field — use this for all state mapping, not 'mode' (stays 0).
WORK_MODE_IDLE = {0, 35, 85, 29, 40, 14, 23}
WORK_MODE_PAUSE = {4, 31, 82, 27, 37, 9}
WORK_MODE_CLEANING = {1, 30, 81, 25, 36, 7}
WORK_MODE_GO_HOME = {5, 10, 11, 12, 21, 26, 32, 47, 38}

# status values observed via traffic capture
# Used together with work_mode and charge_state to detect Docked state.
STATUS_IDLE = 1
STATUS_PAUSED = 2
STATUS_RETURNING = 3
STATUS_DOCKED = 4
STATUS_CLEANING = 5

# ── Confirmed MQTT commands (captured 2026-03-28) ────────────────────────────
# Topic pattern:
#   /mqtt/{product_id}/{sn}/thing/service_invoke/{SERVICE_NAME}
# Payload pattern:
#   {"method": "service.{SERVICE_NAME}", "msgId": "{ms_timestamp}",
#    "params": {...}, "tenantId": "1528983614213726208", "version": "3.0"}

# Start cleaning (from docked or idle) OR resume after pause — same command.
CMD_START = {
    "service": "set_room_clean",
    "params": {"room_ids": [], "ctrl_value": 1, "clean_type": 0},
}
# Pause during active cleaning.
CMD_PAUSE = {
    "service": "set_room_clean",
    "params": {"room_ids": [], "ctrl_value": 2, "clean_type": 0},
}
# Return to dock (from cleaning or paused).
CMD_GO_HOME = {
    "service": "start_recharge",
    "params": {},
}
# Cancel return-to-dock → leaves robot idle on floor.
# Also used as HA "stop": the app has no dedicated stop-in-place during cleaning;
# stop_recharge is the closest equivalent (stops motion, leaves robot on floor).
CMD_STOP = {
    "service": "stop_recharge",
    "params": {},
}

# ── Suction power (wind) levels ──────────────────────────────────────────────
# Confirmed via traffic capture (2026-03-28):
# Topic:   /mqtt/{product_id}/{sn}/thing/service/property/set
# Payload: {"method": "prop.set", "msgId": "...", "params": {"wind": N},
#           "tenantId": "...", "version": "1.0"}
# Note: version "1.0" and method "prop.set" — different from service_invoke commands.
FAN_SPEED_LIST = ["Silent", "Standard", "Medium", "Turbo"]
FAN_SPEED_MAP  = {"Silent": 0, "Standard": 1, "Medium": 2, "Turbo": 3}
FAN_SPEED_REVERSE: dict[int, str] = {v: k for k, v in FAN_SPEED_MAP.items()}

# Polling interval fallback (seconds) when MQTT push is unavailable
POLL_INTERVAL = 30
