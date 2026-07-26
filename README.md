# Momir Vig

A physical, print-on-thermal-paper version of the Momir Vig format: pick a
mana value, get a random creature card of that cost pulled from Magic's
entire history, printed on a receipt printer.

- Card data comes from MTGJSON's `AtomicCards.json.gz`, parsed into a local
  SQLite database (with an FTS5 name index) on first run.
- Art is fetched from Scryfall on demand and cached to disk.
- Printing goes through a swappable driver: a `mock` driver (saves a PNG,
  no hardware needed — this is the default, used for development) and a
  real `escpos` driver for USB/serial/network ESC/POS thermal printers.
- On a Raspberry Pi, a control panel at `http://momir.local` (port 80)
  manages an ordered list of Wi-Fi networks for `wlan0` to join; it falls
  back to broadcasting its own access point (`MomirVig`) only when none of
  those networks and no Ethernet connection are available. `eth0` provides
  internet (for card art) via a plain Ethernet connection.

## Requirements

- Python 3.11+
- `data/AtomicCards.json.gz` — download from https://mtgjson.com/downloads/all-files/#atomiccards
  and place it in `data/`.

## Running on your Mac (development)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000. The first request triggers the one-time
database build (parses `AtomicCards.json.gz`, ~18,800 creature cards in well
under a second). The `mock` printer driver is used by default — "printing"
just writes a timestamped PNG to `output/`, so the whole flow (summon,
reroll, search, print) is testable without a printer attached.

To rebuild the database manually (e.g. after downloading a newer
`AtomicCards.json.gz`):

```bash
python3 -m app.build_db
```

It only rebuilds when the source file's mtime/size changes, so normal app
startups after the first are instant.

## Deploying to a Raspberry Pi 4

1. Flash Raspberry Pi OS (Bookworm or newer — this uses NetworkManager,
   which the setup script depends on), enable SSH, get the Pi on your
   network long enough to provision it.
2. Copy this project to the Pi (`git clone`/`scp`/etc.), including
   `data/AtomicCards.json.gz`.
3. Install dependencies:
   ```bash
   cd momir
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
4. Plug `eth0` into your router with an Ethernet cable (this is how the Pi
   gets internet — for card art — regardless of Wi-Fi).
5. Run the provisioning script — this creates the `MomirVig` fallback
   access point on `wlan0`, sets up `http://momir.local`, and installs both
   the print app and the control panel as systemd services that start on
   boot:
   ```bash
   sudo bash scripts/setup_pi_ap.sh
   ```
   Defaults to SSID `MomirVig`; override with `MOMIR_SSID` /
   `MOMIR_WIFI_PASSWORD` env vars if you want something else (password
   must be 8+ characters).
6. Connect your phone/laptop to the `MomirVig` Wi-Fi network and open
   `http://momir.local` (or `http://192.168.4.1`) — the control panel. From
   there, add your real Wi-Fi network(s) under "Network" (reorder them if
   you have more than one; the top entry is tried first). `wlan0` only
   falls back to broadcasting `MomirVig` again when none of the saved
   networks and no Ethernet connection are available, so once you've added
   your home network the Pi will normally just join it on boot. Open the
   print app itself via the "Open Momir Vig App →" link (port 8000).
7. Plug in your thermal printer and switch the driver from `mock` to
   `escpos` — either in the "Printer settings" panel in the web UI, or by
   editing `data/config.json` directly. For USB printers, find the vendor
   and product IDs with `lsusb`, e.g.:
   ```
   Bus 001 Device 004: ID 0483:5743 STMicroelectronics Printer
   ```
   sets `usb_vendor_id: "0x0483"`, `usb_product_id: "0x5743"`.

   USB thermal printers usually need a udev rule so the app can talk to
   them without root:
   ```bash
   echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="5743", MODE="0666", GROUP="plugdev"' \
     | sudo tee /etc/udev/rules.d/99-momir-printer.rules
   sudo udevadm control --reload-rules && sudo udevadm trigger
   ```

**Card art needs internet.** Plug `eth0` into your router; NetworkManager
NATs `wlan0` clients out through it automatically, no extra configuration
needed. Without `eth0` connected, summon/print still work fine; cards just
render without art.

Useful commands on the Pi:
```bash
sudo systemctl status momir.service         # is the print app running?
sudo systemctl status momir-panel.service   # is the control panel running?
journalctl -u momir.service -f              # print app logs
journalctl -u momir-panel.service -f        # control panel logs
sudo systemctl restart momir.service        # after editing config.json by hand
nmcli -f NAME,AUTOCONNECT-PRIORITY connection show   # saved Wi-Fi networks + priority
```

The print app (`momir.service`) can also be started/stopped and included in
or excluded from boot entirely from the control panel UI, no SSH needed.

## Card pool

Every card in `AtomicCards.json.gz` whose type line includes Creature (or
the pre-6th-edition "Summon" supertype), excluding `A-`-prefixed names
(Alchemy/Arena-only rebalances with no paper printing). Multi-faced cards
(modal DFCs, transform, split, adventure) are represented by their front
face — the one you'd actually cast — using that face's own mana value.

If a requested mana value has no matching creatures (e.g. very high X
values), the app walks outward (±1, ±2, ...) the same way real Momir Vig
does when a deck runs dry at a given cost.

## Project layout

```
app/
  main.py            FastAPI app + routes
  db.py              query helpers (random-by-cmc, FTS5 search)
  build_db.py        AtomicCards.json.gz -> SQLite
  card_art.py         Scryfall art lookup + disk cache
  config.py            data/config.json load/save
  printer/
    base.py             driver interface
    mock.py              PNG-to-output/ driver (dev default)
    escpos_driver.py      real thermal printing
    render.py              composes name/cost/type/text/art into one image
    fonts/                  bundled DejaVu Sans (works the same on Mac + Pi)
  static/               vanilla HTML/CSS/JS control page (no build step, no CDN)
panel/
  main.py               FastAPI app: momir.service control + Wi-Fi management, port 80
  network.py             nmcli wrapper (scan, saved networks, AP fallback)
  service_ctl.py           systemctl wrapper scoped to momir.service
  static/                    vanilla HTML/CSS/JS control panel page
data/
  AtomicCards.json.gz    source data (you provide)
  momir.sqlite3            generated
  art_cache/                cached art
  config.json                printer/art settings
scripts/
  setup_pi_ap.sh            Pi-only: Wi-Fi access point (MomirVig) fallback + both systemd services + sudoers
  momir.service             systemd unit template (print app, port 8000)
  momir-panel.service       systemd unit template (control panel, port 80)
```
