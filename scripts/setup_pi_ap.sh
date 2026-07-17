#!/bin/bash
# One-time Raspberry Pi provisioning:
#   1. Turns wlan0 into its own WPA2 access point (via NetworkManager, the
#      default network stack on Raspberry Pi OS Bookworm+) so you can
#      connect a phone/laptop straight to the Pi with no router involved.
#   2. Enables avahi so the Pi answers at http://momir.local
#   3. Installs + enables the momir systemd service so the app starts on boot
#
# Run this ON THE PI (not on your Mac): sudo bash scripts/setup_pi_ap.sh
#
# Leaves eth0 alone — plug it into your router if you want card art to
# work (Scryfall lookups need internet; wlan0 as an isolated AP does not
# provide that by itself). Everything else works fine without it.

set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This script provisions a Raspberry Pi and must be run on the Pi itself, not on macOS." >&2
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "Run this with sudo: sudo bash scripts/setup_pi_ap.sh" >&2
  exit 1
fi

SSID="${MOMIR_SSID:-Momir-Vig}"
WIFI_PASSWORD="${MOMIR_WIFI_PASSWORD:-summonacreature}"
AP_IP="192.168.4.1/24"
CON_NAME="momir-ap"
REAL_USER="${SUDO_USER:-$(whoami)}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${#WIFI_PASSWORD}" -lt 8 ]]; then
  echo "MOMIR_WIFI_PASSWORD must be at least 8 characters (WPA2 requirement)." >&2
  exit 1
fi

if ! command -v nmcli >/dev/null 2>&1; then
  echo "nmcli not found. This script targets Raspberry Pi OS Bookworm+ (NetworkManager)." >&2
  echo "On older Raspberry Pi OS releases (dhcpcd/hostapd based) you'll need to configure the AP manually." >&2
  exit 1
fi

echo "==> Installing avahi-daemon (for http://momir.local)"
apt-get update -qq
apt-get install -y -qq avahi-daemon
systemctl enable --now avahi-daemon

echo "==> Creating access point '$SSID' on wlan0"
nmcli connection delete "$CON_NAME" >/dev/null 2>&1 || true
nmcli connection add type wifi ifname wlan0 con-name "$CON_NAME" autoconnect yes ssid "$SSID"
nmcli connection modify "$CON_NAME" \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  ipv4.method shared \
  ipv4.addresses "$AP_IP" \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.psk "$WIFI_PASSWORD"
nmcli connection up "$CON_NAME"

echo "==> Installing systemd service (user: $REAL_USER, dir: $PROJECT_DIR)"
sed -e "s#__PROJECT_DIR__#${PROJECT_DIR}#g" -e "s#__USER__#${REAL_USER}#g" \
  "${PROJECT_DIR}/scripts/momir.service" > /etc/systemd/system/momir.service
systemctl daemon-reload
systemctl enable --now momir.service

cat <<EOF

Done.

Wi-Fi network : $SSID
Password      : $WIFI_PASSWORD
Control page  : http://momir.local  (or http://192.168.4.1)

Check the app is running with: sudo systemctl status momir.service
Watch logs with:                journalctl -u momir.service -f
EOF
