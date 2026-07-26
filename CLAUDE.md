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

### Running the control panel (Mac dev)
```bash
uvicorn panel.main:app --reload --port 8080
```
Separate app from the print app (`app/`), on a separate port. `nmcli`/`systemctl`
aren't present on a Mac, so `panel/network.py` and `panel/service_ctl.py` degrade
to `{"supported": False}` responses instead of erroring — the UI still loads for
frontend iteration, it just can't actually toggle anything.

### Deploying to the Raspberry Pi
Full first-time provisioning steps are in README.md. For an already-provisioned Pi,
deploying a change is:
```bash
ssh momir.local
cd ~/momir && git pull origin main
sudo systemctl restart momir.service
sudo systemctl restart momir-panel.service   # only if panel/ changed
```
Networking is provisioned once via `scripts/setup_pi_ap.sh`, which also installs
both systemd services and a sudoers grant — see the Architecture section below.

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
  face (`side` is `None`/`"a"`) using that face's own mana value. Also drops cards
  never printed in paper: it auto-downloads MTGJSON's `SetList.json.gz` (small,
  unlike `AtomicCards.json.gz` this isn't a manual step) to `data/SetList.json.gz`
  and excludes any card whose `printings` are *all* sets with `isOnlineOnly` set —
  catches Arena-only cards that don't have the `A-` prefix. If `SetList.json.gz`
  can't be fetched (no network), this filtering step is skipped rather than failing
  the whole build. Fingerprints the source file (mtime+size) plus a `SCHEMA_VERSION`
  constant in a `meta` table to skip rebuilding when nothing changed — bump
  `SCHEMA_VERSION` whenever the filtering logic changes so existing installs rebuild
  on next startup even though `AtomicCards.json.gz` itself didn't change.
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
  `render_card_full()` (full-card layout) dithers straight to monochrome for the
  printer; `render_card_full_preview()` returns the same source image in color,
  used only for the web preview in `_build_preview()` (`app/main.py`) — the token
  stashed in `state.pending` still holds the dithered image, so `/api/print` always
  prints B&W regardless of what the preview showed.
- `app/static/` — vanilla HTML/CSS/JS, no build step, no CDN dependencies. The `/`
  route in `main.py` does not serve `index.html` as a static file as-is — it injects
  a content-hash query string (`?v=<md5>`) onto the `/static/app.js` and
  `/static/style.css` URLs so browsers can't silently keep serving a stale cached
  copy after a deploy.
- `panel/` — a second, independent FastAPI app (own uvicorn process, own systemd
  unit `momir-panel.service`, port 80) that's always on regardless of whether the
  print app itself is running — that's the point of it. `panel/main.py` holds the
  routes plus a lifespan-managed background reconciliation loop (`ReconcileLoop`)
  that re-evaluates wlan0's target connection every ~20s (and immediately after any
  saved-network mutation, via an `asyncio.Event` nudge). `panel/network.py` wraps
  `nmcli` for scanning, saved-network CRUD/reorder, and AP up/down; `connection
  .autoconnect-priority` on each saved nmcli profile is the only place ordering is
  stored — no separate JSON list to drift out of sync. `panel/service_ctl.py` wraps
  `systemctl`, scoped to `momir.service` only. Both wrapper modules check
  `shutil.which(...)` and degrade to `{"supported": False}` rather than erroring,
  the same "swallow and degrade" pattern `app/card_art.py` uses for offline art
  lookups — this is what lets the panel run for frontend iteration on a Mac, where
  neither binary exists. All subprocess calls pass argument lists, never a shell
  string, since SSIDs/passwords are user-supplied. `panel/main.py` runs as the same
  unprivileged user as `momir.service` (not root); it gets `systemctl
  start/stop/enable/disable momir.service` and full `nmcli` access via a scoped
  `/etc/sudoers.d/momir-panel` grant installed by `setup_pi_ap.sh` (systemctl is
  pinned to those four literal invocations; nmcli is granted broadly, since its
  argument surface — arbitrary saved connection names/SSIDs — doesn't work with
  literal-string sudoers pinning). Binding port 80 as non-root needs
  `AmbientCapabilities=CAP_NET_BIND_SERVICE` in `scripts/momir-panel.service`. That
  unit must *not* set `NoNewPrivileges=yes` **or** `CapabilityBoundingSet=` to
  anything narrower than the default full set — either one silently breaks the
  `sudo` calls the panel depends on, because `sudo` is a setuid-root binary that
  needs to regain capabilities (`CAP_SETUID`/`CAP_SETGID`/`CAP_AUDIT_WRITE`, etc.)
  outside whatever's left in the bounding set; a narrowed bounding set fails with
  `sudo: unable to change to root gid: Operation not permitted` even though the
  exact same sudoers grant works fine from an interactive shell. (Hit this for
  real on hardware: an earlier version of this unit also set
  `CapabilityBoundingSet=CAP_NET_BIND_SERVICE`, which broke every sudo call from
  the running service while working perfectly over SSH — the giveaway that it's a
  bounding-set issue and not a sudoers issue.)
- `scripts/setup_pi_ap.sh` — Pi-only provisioning script: creates `wlan0`'s
  NetworkManager WPA2 access point profile (SSID `MomirVig` by default, `ipv4
  .method shared` so NetworkManager handles DHCP/NAT out through `eth0`) as a
  low-priority (`autoconnect-priority -10`) fallback — `panel/network.py`'s
  reconciliation loop is what actually decides live whether wlan0 joins a saved
  network, sits idle (Ethernet already up), or falls back to this AP, but the low
  priority also makes the AP NetworkManager's own last resort as defense in depth.
  Deletes the old `momir-home`/`momir-hotspot` client profiles from the
  now-removed `setup_pi_wifi.sh` so they don't compete for `wlan0`. Also sets up
  avahi for `http://momir.local`, installs `scripts/momir.service` and
  `scripts/momir-panel.service` as systemd units, and installs the
  `/etc/sudoers.d/momir-panel` grant described above.

## Outstanding work

See TODO.md for planned/in-progress features and known issues.

## Workflow

Changes are made on a branch, pushed, and opened as a PR against `main` on GitHub
(`PlazmaEssence/momir-basic`); there's no CI, so "testing before merge" means running
locally with the mock driver and/or checking out the branch directly on the Pi to
exercise it against the real printer hardware. The Pi's own checkout (`~/momir`)
tracks `main` and is updated with a plain `git pull` after merging.
