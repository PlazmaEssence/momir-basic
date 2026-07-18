#!/bin/bash
# One-time Raspberry Pi provisioning:
#   1. Registers wlan0 as a Wi-Fi client with two profiles: your home
#      network (preferred) and a mobile hotspot (fallback, used away from
#      home). NetworkManager auto-connects to whichever is in range,
#      preferring home when both are.
#   2. Enables avahi so the Pi answers at http://momir.local on whichever
#      network it's joined.
#   3. Installs + enables the momir systemd service so the app starts on boot
#
# Run this ON THE PI (not on your Mac): sudo bash scripts/setup_pi_wifi.sh
#
# wlan0 gets internet directly from whichever network it joins, so no
# separate eth0 connection is required for card art (Scryfall lookups).
# To reach the control page, connect your phone/laptop to the same
# network as the Pi (home Wi-Fi, or your hotspot when away) and open
# http://momir.local.

set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This script provisions a Raspberry Pi and must be run on the Pi itself, not on macOS." >&2
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "Run this with sudo: sudo bash scripts/setup_pi_wifi.sh" >&2
  exit 1
fi

HOME_SSID="${MOMIR_HOME_SSID:-}"
HOME_PASSWORD="${MOMIR_HOME_PASSWORD:-}"
HOTSPOT_SSID="${MOMIR_HOTSPOT_SSID:-}"
HOTSPOT_PASSWORD="${MOMIR_HOTSPOT_PASSWORD:-}"
REAL_USER="${SUDO_USER:-$(whoami)}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "$HOME_SSID" || -z "$HOME_PASSWORD" || -z "$HOTSPOT_SSID" || -z "$HOTSPOT_PASSWORD" ]]; then
  cat >&2 <<EOF
Missing required settings. Run with all four env vars set, e.g.:

  sudo MOMIR_HOME_SSID="MyHomeWifi" MOMIR_HOME_PASSWORD="homepassword" \\
       MOMIR_HOTSPOT_SSID="MyPhoneHotspot" MOMIR_HOTSPOT_PASSWORD="hotspotpassword" \\
       bash scripts/setup_pi_wifi.sh
EOF
  exit 1
fi

if [[ "${#HOME_PASSWORD}" -lt 8 || "${#HOTSPOT_PASSWORD}" -lt 8 ]]; then
  echo "Both passwords must be at least 8 characters (WPA2 requirement)." >&2
  exit 1
fi

if ! command -v nmcli >/dev/null 2>&1; then
  echo "nmcli not found. This script targets Raspberry Pi OS Bookworm+ (NetworkManager)." >&2
  exit 1
fi

echo "==> Installing avahi-daemon (for http://momir.local)"
apt-get update -qq
apt-get install -y -qq avahi-daemon
systemctl enable --now avahi-daemon

echo "==> Removing any old AP-mode profile from a previous setup"
nmcli connection delete momir-ap >/dev/null 2>&1 || true

echo "==> Registering Wi-Fi profiles on wlan0 (home preferred, hotspot fallback)"
nmcli connection delete momir-home >/dev/null 2>&1 || true
nmcli connection delete momir-hotspot >/dev/null 2>&1 || true

nmcli connection add type wifi ifname wlan0 con-name momir-home autoconnect yes ssid "$HOME_SSID"
nmcli connection modify momir-home \
  connection.autoconnect-priority 100 \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.psk "$HOME_PASSWORD"

nmcli connection add type wifi ifname wlan0 con-name momir-hotspot autoconnect yes ssid "$HOTSPOT_SSID"
nmcli connection modify momir-hotspot \
  connection.autoconnect-priority 10 \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.psk "$HOTSPOT_PASSWORD"

echo "==> Connecting now (prefers home, falls back to hotspot)"
nmcli connection up momir-home || nmcli connection up momir-hotspot || \
  echo "Neither network is in range right now — it'll connect automatically once one is." >&2

echo "==> Installing systemd service (user: $REAL_USER, dir: $PROJECT_DIR)"
sed -e "s#__PROJECT_DIR__#${PROJECT_DIR}#g" -e "s#__USER__#${REAL_USER}#g" \
  "${PROJECT_DIR}/scripts/momir.service" > /etc/systemd/system/momir.service
systemctl daemon-reload
systemctl enable --now momir.service

cat <<EOF

Done.

Home network    : $HOME_SSID (preferred)
Hotspot fallback: $HOTSPOT_SSID (used when home isn't in range)
Control page    : http://momir.local (from a device on the same network)

Check the app is running with: sudo systemctl status momir.service
Watch logs with:                journalctl -u momir.service -f
Check which network is active: nmcli -f NAME,DEVICE connection show --active
EOF
