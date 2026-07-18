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
- On a Raspberry Pi, `wlan0` connects out to your home Wi-Fi (preferred) or
  a mobile hotspot (fallback, for when you're away from home) — control the
  app from any phone or laptop on the same network.

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
4. Run the provisioning script — this registers `wlan0` as a Wi-Fi client
   with your home network (preferred) and a mobile hotspot (fallback for
   when you're away from home), sets up `http://momir.local`, and installs
   the app as a systemd service that starts on boot:
   ```bash
   sudo MOMIR_HOME_SSID="MyHomeWifi" MOMIR_HOME_PASSWORD="homepassword" \
        MOMIR_HOTSPOT_SSID="MyPhoneHotspot" MOMIR_HOTSPOT_PASSWORD="hotspotpassword" \
        bash scripts/setup_pi_wifi.sh
   ```
   (All four are required; both passwords must be 8+ characters.)
5. Connect your phone/laptop to the same network the Pi joined (home
   Wi-Fi, or your hotspot when away) and open `http://momir.local`. Check
   which network the Pi is on with `nmcli -f NAME,DEVICE connection show --active`.
6. Plug in your thermal printer and switch the driver from `mock` to
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

**Card art needs internet.** Since `wlan0` connects out to your home
network or hotspot as a regular client, it gets internet the same way any
device on that network would — no extra configuration needed. Without
internet (e.g. neither known network is in range), summon/print still work
fine; cards just render without art.

Useful commands on the Pi:
```bash
sudo systemctl status momir.service     # is it running?
journalctl -u momir.service -f          # live logs
sudo systemctl restart momir.service    # after editing config.json by hand
```

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
data/
  AtomicCards.json.gz    source data (you provide)
  momir.sqlite3            generated
  art_cache/                cached art
  config.json                printer/art settings
scripts/
  setup_pi_wifi.sh         Pi-only: Wi-Fi client (home + hotspot fallback) + systemd service provisioning
  momir.service             systemd unit template
```
