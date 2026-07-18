# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Setup & run (Mac dev)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
App runs at http://localhost:8000. First request triggers a one-time DB build from
`data/AtomicCards.json.gz`, which must be downloaded manually and placed in `data/`
(see README.md for the source URL) — it isn't committed to the repo.

### Rebuild the card database manually
```bash
python3 -m app.build_db
```
Only rebuilds when the source file's mtime/size changed (`build_db.needs_rebuild`).
The running app also exposes a "Redownload & rebuild card database" button under
Settings (`POST /api/rebuild_db`) that re-fetches `AtomicCards.json.gz` from MTGJSON
and rebuilds in place.

There is no test suite, linter, or frontend build step in this repo — plain Python
plus vanilla JS/CSS served straight from `app/static/`.

### Deploying to the Raspberry Pi
Full first-time provisioning steps are in README.md. For an already-provisioned Pi,
deploying a change is:
```bash
ssh momir.local
cd ~/momir && git pull origin main
sudo systemctl restart momir.service
```
Wi-Fi is provisioned once via `scripts/setup_pi_wifi.sh` (NetworkManager client
profiles: home network preferred, mobile hotspot fallback — `wlan0` no longer runs
as its own access point).

## Architecture

- `app/main.py` — FastAPI app and all routes. Holds one in-process `AppState`:
  current config, the active `printer_driver`, and an in-memory `pending` dict
  mapping summon tokens to rendered images (capped at `MAX_PENDING`, oldest evicted
  first). Summon/preview/search all funnel through `_build_preview()`, which renders
  the card and stashes the image under a token; `/api/print` looks the token up and
  hands the image to the driver. Nothing is persisted between summon and print — an
  app restart drops any pending (summoned but not yet printed) card.
- `app/db.py` — read-only queries against `data/momir.sqlite3`. `random_creature_by_cmc()`
  implements the Momir Vig "walk outward" rule: if the requested mana value has zero
  matches, it tries ±1, ±2, ... up to `MAX_CMC_WALK` before giving up.
- `app/build_db.py` — turns `data/AtomicCards.json.gz` (MTGJSON) into the SQLite
  database. Keeps only entries whose `types` include Creature/Summon, skips
  `A-`-prefixed (Alchemy-only) names, and for multi-faced cards keeps only the front
  face (`side` is `None`/`"a"`) using that face's own mana value. Fingerprints the
  source file (mtime+size) in a `meta` table to skip rebuilding when nothing changed.
- `app/card_art.py` — Scryfall art lookup with an on-disk cache (`data/art_cache/`).
  All network failures are swallowed here; callers get `None` back and render a
  text-only card rather than an error.
- `app/config.py` — loads/saves `data/config.json`, deep-merged against
  `DEFAULT_CONFIG` so config keys added in later versions don't break existing files.
- `app/printer/` — driver interface (`base.PrinterDriver`: abstract `print_image` /
  `status`, overridable `close()`). `mock.py` writes a PNG to `output/` (the dev
  default, no hardware needed). `escpos_driver.py` wraps `python-escpos` for real
  USB/serial/network thermal printers; it connects lazily and swallows connection
  errors into a status string instead of raising. **Any code that replaces or drops
  a driver instance must call `.close()` on the old one first** — python-escpos does
  not release a claimed USB interface on garbage collection, only on explicit
  `.close()` (`usb.util.dispose_resources()`). Skipping this leaks USB handles and
  eventually surfaces as `[Errno 16] Resource busy` on print.
- `app/printer/render.py` — composes name/mana cost/type/text/art into the single
  PIL image both drivers consume, sized off the configured `paper_width_mm`.
- `app/static/` — vanilla HTML/CSS/JS, no build step, no CDN dependencies. The `/`
  route in `main.py` does not serve `index.html` as a static file as-is — it injects
  a content-hash query string (`?v=<md5>`) onto the `/static/app.js` and
  `/static/style.css` URLs so browsers can't silently keep serving a stale cached
  copy after a deploy.
- `scripts/setup_pi_wifi.sh` — Pi-only provisioning script: registers `wlan0` as a
  NetworkManager Wi-Fi client (home network profile at `autoconnect-priority 100`,
  mobile-hotspot fallback at `10`), sets up avahi for `http://momir.local`, and
  installs `scripts/momir.service` as a systemd unit.

## Outstanding work

See TODO.md for planned/in-progress features and known issues.

## Workflow

Changes are made on a branch, pushed, and opened as a PR against `main` on GitHub
(`PlazmaEssence/momir-basic`); there's no CI, so "testing before merge" means running
locally with the mock driver and/or checking out the branch directly on the Pi to
exercise it against the real printer hardware. The Pi's own checkout (`~/momir`)
tracks `main` and is updated with a plain `git pull` after merging.
