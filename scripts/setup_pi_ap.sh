#!/bin/bash
# One-time Raspberry Pi provisioning:
#   1. Turns wlan0 into its own WPA2 access point (via NetworkManager, the
#      default network stack on Raspberry Pi OS Bookworm+) so you can
#      connect a phone/laptop straight to the Pi with no router involved.
#      Removes the old momir-home / momir-hotspot Wi-Fi *client* profiles
#      (from scripts/setup_pi_wifi.sh) so they don't compete with the AP
#      for wlan0.
#   2. Enables avahi so the Pi answers at http://momir.local
#   3. Installs + enables the momir systemd service so the app starts on boot
#
# Run this ON THE PI (not on your Mac): sudo bash scripts/setup_pi_ap.sh
#
# Plug eth0 into your router for internet (card art / Scryfall lookups).
# NetworkManager NATs wlan0 clients out through whichever interface holds
# the default route, so eth0 just needs to be plugged in and get DHCP —
# no extra configuration required.

set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This script provisions a Raspberry Pi and must be run on the Pi itself, not on macOS." >&2
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "Run this with sudo: sudo bash scripts/setup_pi_ap.sh" >&2
  exit 1
fi

SSID="${MOMIR_SSID:-MomirVig}"
WIFI_PASSWORD="${MOMIR_WIFI_PASSWORD:-merbUw-bovfu6-piqvup}"
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

echo "==> Removing old Wi-Fi client profiles from setup_pi_wifi.sh, if present"
nmcli connection delete momir-home >/dev/null 2>&1 || true
nmcli connection delete momir-hotspot >/dev/null 2>&1 || true

echo "==> Creating access point '$SSID' on wlan0"
nmcli connection delete "$CON_NAME" >/dev/null 2>&1 || true
nmcli connection add type wifi ifname wlan0 con-name "$CON_NAME" autoconnect yes ssid "$SSID"
nmcli connection modify "$CON_NAME" \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  connection.autoconnect-priority 100 \
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

Internet: plug eth0 into your router (DHCP) — wlan0 clients get NATed out
through it automatically. Card art still works fine without it; cards just
render without art.

Check the app is running with: sudo systemctl status momir.service
Watch logs with:                journalctl -u momir.service -f
EOF
