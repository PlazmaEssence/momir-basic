#!/bin/bash
# One-time Raspberry Pi provisioning:
#   1. Creates wlan0's WPA2 access point profile (via NetworkManager, the
#      default network stack on Raspberry Pi OS Bookworm+) as a low-priority
#      fallback — the momir-panel control page (see below) actively manages
#      which network wlan0 joins, only falling back to this AP when none of
#      the saved Wi-Fi networks and no Ethernet connection are available.
#      Removes the old momir-home / momir-hotspot Wi-Fi *client* profiles
#      (from the now-deleted scripts/setup_pi_wifi.sh) so they don't compete
#      with the panel-managed profiles for wlan0.
#   2. Enables avahi so the Pi answers at http://momir.local
#   3. Installs + enables the momir systemd service so the app starts on boot
#   4. Installs + enables momir-panel.service — a second, always-on web app
#      on port 80 (http://momir.local) for toggling momir.service and
#      managing the saved Wi-Fi network list, with a scoped sudoers grant
#      so it can run systemctl/nmcli without running as root itself.
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
ESP32_USB_VENDOR_ID="${MOMIR_ESP32_USB_VENDOR_ID:-10c4}"
ESP32_USB_PRODUCT_ID="${MOMIR_ESP32_USB_PRODUCT_ID:-ea60}"

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

echo "==> Creating access point '$SSID' on wlan0 (lowest-priority fallback)"
nmcli connection delete "$CON_NAME" >/dev/null 2>&1 || true
nmcli connection add type wifi ifname wlan0 con-name "$CON_NAME" autoconnect yes ssid "$SSID"
nmcli connection modify "$CON_NAME" \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  connection.autoconnect-priority -10 \
  ipv4.method shared \
  ipv4.addresses "$AP_IP" \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.psk "$WIFI_PASSWORD"
nmcli connection up "$CON_NAME"

echo "==> Installing udev rule for the ESP32 display (stable /dev/momir-esp32)"
sed -e "s#__ESP32_USB_VENDOR_ID__#${ESP32_USB_VENDOR_ID}#g" -e "s#__ESP32_USB_PRODUCT_ID__#${ESP32_USB_PRODUCT_ID}#g" \
  "${PROJECT_DIR}/scripts/99-momir-esp32.rules" > /etc/udev/rules.d/99-momir-esp32.rules
udevadm control --reload-rules
udevadm trigger

echo "==> Installing systemd services (user: $REAL_USER, dir: $PROJECT_DIR)"
for unit in momir-printsvc.service momir.service momir-upload.service momir-esp32svc.service; do
  sed -e "s#__PROJECT_DIR__#${PROJECT_DIR}#g" -e "s#__USER__#${REAL_USER}#g" \
    "${PROJECT_DIR}/scripts/${unit}" > "/etc/systemd/system/${unit}"
done
systemctl daemon-reload
systemctl enable momir-printsvc.service momir.service momir-upload.service momir-esp32svc.service
# restart (not just "enable --now") so re-running this script after a unit-file
# or code change actually applies it, instead of silently no-op'ing on a
# service that's already active. printsvc first since momir.service and
# momir-upload.service both call it to actually print; esp32svc last since it
# calls momir.service's API in turn.
systemctl restart momir-printsvc.service
systemctl restart momir.service
systemctl restart momir-upload.service
systemctl restart momir-esp32svc.service

echo "==> Granting momir-panel a scoped sudoers allowlist (systemctl on momir/printsvc/upload/esp32svc + nmcli)"
SYSTEMCTL_BIN="$(command -v systemctl)"
NMCLI_BIN="$(command -v nmcli)"
SUDOERS_TMP="$(mktemp)"
cat > "$SUDOERS_TMP" <<EOF
# Managed by scripts/setup_pi_ap.sh — lets momir-panel.service (running as
# $REAL_USER, not root) toggle momir.service/momir-printsvc.service/
# momir-upload.service/momir-esp32svc.service and manage Wi-Fi without being
# root itself. systemctl is pinned to exact per-service invocations; nmcli
# is granted broadly since its argument surface (arbitrary saved connection
# names/SSIDs) doesn't work
# with literal-string sudoers pinning.
$REAL_USER ALL=(root) NOPASSWD: $SYSTEMCTL_BIN start momir.service, $SYSTEMCTL_BIN stop momir.service, $SYSTEMCTL_BIN enable momir.service, $SYSTEMCTL_BIN disable momir.service
$REAL_USER ALL=(root) NOPASSWD: $SYSTEMCTL_BIN start momir-printsvc.service, $SYSTEMCTL_BIN stop momir-printsvc.service, $SYSTEMCTL_BIN enable momir-printsvc.service, $SYSTEMCTL_BIN disable momir-printsvc.service
$REAL_USER ALL=(root) NOPASSWD: $SYSTEMCTL_BIN start momir-upload.service, $SYSTEMCTL_BIN stop momir-upload.service, $SYSTEMCTL_BIN enable momir-upload.service, $SYSTEMCTL_BIN disable momir-upload.service
$REAL_USER ALL=(root) NOPASSWD: $SYSTEMCTL_BIN start momir-esp32svc.service, $SYSTEMCTL_BIN stop momir-esp32svc.service, $SYSTEMCTL_BIN enable momir-esp32svc.service, $SYSTEMCTL_BIN disable momir-esp32svc.service
$REAL_USER ALL=(root) NOPASSWD: $NMCLI_BIN
EOF
visudo -cf "$SUDOERS_TMP"
install -m 0440 "$SUDOERS_TMP" /etc/sudoers.d/momir-panel
rm -f "$SUDOERS_TMP"

echo "==> Installing momir-panel service (user: $REAL_USER, dir: $PROJECT_DIR, port 80)"
sed -e "s#__PROJECT_DIR__#${PROJECT_DIR}#g" -e "s#__USER__#${REAL_USER}#g" \
  "${PROJECT_DIR}/scripts/momir-panel.service" > /etc/systemd/system/momir-panel.service
systemctl daemon-reload
systemctl enable momir-panel.service
# restart (not just "enable --now") so re-running this script after a
# unit-file or code change actually applies it — see the momir.service
# install above for why "enable --now" alone isn't enough here
systemctl restart momir-panel.service

cat <<EOF

Done.

Wi-Fi network (fallback) : $SSID
Password                 : $WIFI_PASSWORD
Control panel            : http://momir.local  (or http://192.168.4.1)
Print app                : http://momir.local:8000
Print upload app         : http://momir.local:8001

ESP32 display: plug it into the Pi over USB. If it doesn't show up at
/dev/momir-esp32, confirm its USB vendor/product ID with
'udevadm info -a -n /dev/ttyUSB0 | grep -i idVendor' and re-run this script
with MOMIR_ESP32_USB_VENDOR_ID / MOMIR_ESP32_USB_PRODUCT_ID set accordingly.

The control panel lets you add real Wi-Fi networks to join (in priority
order) without SSH — wlan0 only falls back to broadcasting "$SSID" when
none of those networks and no Ethernet connection are available. It also
has Start/Stop and start-on-boot toggles for the print app, the print
upload app, and the shared print service.

Internet: plug eth0 into your router (DHCP) — wlan0 clients get NATed out
through it automatically. Card art still works fine without it; cards just
render without art.

Check the apps are running with: sudo systemctl status momir.service
                                  sudo systemctl status momir-printsvc.service
                                  sudo systemctl status momir-upload.service
                                  sudo systemctl status momir-esp32svc.service
Check the panel is running with: sudo systemctl status momir-panel.service
Watch logs with:                 journalctl -u momir.service -f
                                  journalctl -u momir-printsvc.service -f
                                  journalctl -u momir-upload.service -f
                                  journalctl -u momir-esp32svc.service -f
                                  journalctl -u momir-panel.service -f
EOF
