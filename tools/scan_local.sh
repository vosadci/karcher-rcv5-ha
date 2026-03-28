#!/usr/bin/env bash
# Scan the robot's local IP for open ports that might indicate a local API.
# Usage: ./tools/scan_local.sh <robot_ip>
#
# Ports to check:
#   80, 443        - HTTP/HTTPS local API (older Robart/Karcher models)
#   1883           - MQTT (plaintext)
#   8883           - MQTT (TLS)
#   4196           - 3irobotix-specific port seen in some models
#   10009          - Local REST API on older Kärcher RC3 (robart)
#   6080, 7080     - Alternative REST ports

set -euo pipefail

ROBOT_IP="${1:?Usage: $0 <robot_ip>}"

echo "Scanning ${ROBOT_IP}..."
nmap -sV -p 80,443,1883,8883,4196,6080,7080,10009 --open "${ROBOT_IP}"

echo
echo "Trying HTTP endpoints on port 80..."
for path in / /status /get/status /get/robot_id /api/v1/status; do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "http://${ROBOT_IP}${path}" 2>/dev/null || echo "ERR")
    echo "  GET http://${ROBOT_IP}${path}  →  ${code}"
done

echo
echo "Trying HTTP endpoints on port 10009 (RC3 local API)..."
for path in /get/status /get/robot_id /set/go_home; do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "http://${ROBOT_IP}:10009${path}" 2>/dev/null || echo "ERR")
    echo "  GET http://${ROBOT_IP}:10009${path}  →  ${code}"
done
