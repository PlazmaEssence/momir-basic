# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Setup & run (Mac dev)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn printsvc.main:app --reload --port 8002 &
uvicorn app.main:app --reload
```
App runs at http://localhost:8000. First request triggers a one-time DB build from
`data/AtomicCards.json.gz`, which must be downloaded manually and placed in `data/`
(see README.md for the source URL) — it isn't committed to the repo.

`printsvc` (port 8002) owns the actual printer connection; `app/main.py` calls it
over HTTP rather than holding its own driver, so it needs to be running for
printing or the Settings panel to work — see the Architecture section. To also
run the upload app: `uvicorn upload.main:app --reload --port 8001`.

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
sudo systemctl restart momir-printsvc.service  # only if printsvc/ or app/printer/ changed
sudo systemctl restart momir.service
sudo systemctl restart momir-upload.service    # only if upload/ changed
sudo systemctl restart momir-panel.service     # only if panel/ changed
```
Networking is provisioned once via `scripts/setup_pi_ap.sh`, which also installs
all four systemd services and a sudoers grant — see the Architecture section below.

## Architecture

- `app/main.py` — FastAPI app and all routes. Holds one in-process `AppState`:
  the local `art_config` (the "art" section of `data/config.json` — this app owns
  writes to that section only, see the `printsvc/` bullet below for "printer"), and
  an in-memory `pending` dict mapping summon tokens to rendered images (capped at
  `MAX_PENDING`, oldest evicted first). Summon/preview/search all funnel through
  `_build_preview()`, which renders the card and stashes the image under a token;
  `/api/print` looks the token up and POSTs the rendered image to printsvc's
  `/api/print` over `http://127.0.0.1:8002` (`MOMIR_PRINTSVC_URL` env var
  override) rather than holding a driver itself. Nothing is persisted between
  summon and print — an app restart drops any pending (summoned but not yet
  printed) card. `_printer_render_config()` fetches `paper_width_mm`/`card_layout`
  from printsvc for rendering, falling back to defaults (80mm/custom) if printsvc
  is unreachable so summon/preview still work — the print itself then reports a
  clear `{"ok": false, ...}` instead of silently succeeding. `GET`/`POST
  /api/settings` proxy the "printer" portion straight through to printsvc so the
  existing Settings UI in `app/static/` didn't need any changes; that means the
  Settings panel requires printsvc to be reachable (503 otherwise).
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
  eventually surfaces as `[Errno 16] Resource busy` on print. Only `printsvc/main.py`
  ever instantiates a driver (see below) — `app/main.py` and `upload/main.py` don't
  import `app.printer.get_driver` at all, only `app.printer.render`/`upload.render`
  for image composition.
- `printsvc/` — a third, independent FastAPI app (own uvicorn process, own systemd
  unit `momir-printsvc.service`, port 8002, bound to `127.0.0.1` only — it's an
  internal dependency for the other two apps, not something phones/laptops on the
  LAN talk to). It's the single process that calls `app.printer.get_driver()` and
  holds the resulting `PrinterDriver`, so `app/main.py` (the card app) and
  `upload/main.py` never each open their own connection to the same physical
  printer and race for it — the `.close()`-before-replace constraint above is only
  actually exercised in one place now. Owns the `"printer"` section of
  `data/config.json` (paper width, driver/connection settings, `card_layout`);
  `POST /api/settings` re-`load_config()`s from disk immediately before merging and
  saving, so a near-simultaneous edit to the `"art"` section by `app/main.py`
  (which does the same before writing its own section) is unlikely to be clobbered
  — there's no file lock, this is a best-effort mitigation, acceptable given how
  infrequently either section actually changes. `POST /api/print` takes a
  base64-encoded PNG and hands it straight to the driver — no pending-token
  bookkeeping, that's specific to the card app's summon flow.
- `upload/` — a fourth FastAPI app (own systemd unit `momir-upload.service`, port
  8001, bound to `0.0.0.0` like the card app since people upload from their own
  phones/laptops). Lets anyone on the network print an arbitrary uploaded image or
  a block of text on the same printer. `upload/render.py` reuses
  `app.printer.render._width_for_paper()` and the bundled DejaVu fonts rather than
  duplicating that logic; `render_image()` resizes to the paper's pixel width and
  clamps runaway height to `MAX_IMAGE_HEIGHT_RATIO` (3x the paper width) so a
  tall/high-res photo can't print a multi-foot receipt, and `render_text()`
  word-wraps a block of text with an optional bold "title" first line and a
  small/medium/large font-size choice. `POST /api/print/image` validates the
  upload's content-type against an allowlist and caps its size
  (`MAX_UPLOAD_BYTES`, 10MB) before handing bytes to PIL. Like `app/main.py`, it
  never holds a `PrinterDriver` itself — it renders locally then POSTs the
  finished image to printsvc's `/api/print`.
- `esp32svc/` — a fifth FastAPI app (own systemd unit `momir-esp32svc.service`,
  port 8003, bound to `127.0.0.1` only, same internal-dependency role as
  printsvc). Owns the wired USB/serial link to an optional physical control
  panel (a 2.8" ESP32 LVGL touchscreen, `firmware/esp32_display/`) that lets a
  player pick a mana value with +/- and hold a button to summon+print without
  a phone/laptop. `esp32svc/serial_bridge.py` reads newline-delimited JSON
  commands off the port (`{"cmd": "summon_print", "cmc": N}`) and drives them
  by calling `app/main.py`'s existing `POST /api/summon` then `POST
  /api/print` over `http://127.0.0.1:8000` (`MOMIR_ESP32_APP_URL` override) —
  the same two calls the browser UI makes, so `app/main.py` needed no changes.
  pyserial is synchronous, so the read loop runs in a background thread
  (started/stopped in the FastAPI lifespan) rather than as an asyncio task
  like `panel/main.py`'s `ReconcileLoop`. The port is opened lazily and
  reopened with backoff on any error — same "swallow and degrade" pattern as
  `app/card_art.py` and `escpos_driver.py` — so an unplugged or not-yet-flashed
  ESP32 doesn't take the service down. `MOMIR_ESP32_SERIAL_PORT` defaults to
  `/dev/momir-esp32`, a stable name from the udev rule installed by
  `setup_pi_ap.sh` (see below) rather than whatever `/dev/ttyUSB*`/`ttyACM*`
  the board happens to enumerate as. The firmware itself
  (`firmware/esp32_display/`, a PlatformIO project) has the LVGL UI and serial
  protocol client written, but its display/touch driver config (`lv_conf.h`,
  TFT_eSPI `User_Setup.h`, touch chip selection) is intentionally left as
  board-specific TODOs — see that directory's README.
- `app/printer/render.py` — composes name/mana cost/type/text/art into the single
  PIL image both drivers consume, sized off the configured `paper_width_mm`.
  `render_card_full()` (full-card layout) dithers straight to monochrome for the
  printer; `render_card_full_preview()` returns the same source image in color,
  used only for the web preview in `_build_preview()` (`app/main.py`) — the token
  stashed in `state.pending` still holds the dithered image, so `/api/print` always
  prints B&W regardless of what the preview showed.
- `app/tokens.py` / `app/build_tokens.py` — the Tokens panel's data and renderer.
  `tokens.TOKENS` is a hand-curated "Common" starter list (Treasure, Clue,
  Soldier, ...) that always works offline. `build_tokens.py` builds
  `data/tokens.json` (gitignored), every distinct paper token/emblem from
  MTGJSON (~900). MTGJSON has no standalone token file — tokens only exist in
  each set's own `<CODE>.json.gz` (a `tokens` array) and in the ~180MB
  AllPrintings — so it reads `SetList.json.gz` (shared with `build_db.py`), fetches
  the ~337 sets with a `tokenSetCode` one at a time (4 workers, ~40s, ~1MB each),
  keeps entries whose `types` include Token/Emblem plus a few tracker cards
  (`MARKER_NAMES`: The Monarch, City's Blessing, ...), and dedupes on
  name/type/P-T/colors/text, ranking by how many sets printed it. The set files
  also hold art cards, substitute cards, checklists and ads typed "Card"; those
  are filtered out. It's on demand, not at startup: `POST /api/tokens/rebuild`
  (the panel's "Download full token list" button) runs it on a background thread
  and `GET /api/tokens/build_status` reports progress; or
  `python3 -m app.build_tokens`. Sets that fail to download are skipped and counted.
  `tokens.full_tokens()` reloads when the file's mtime changes, so a finished
  rebuild needs no restart. `GET /api/tokens/search?q=` searches the full list
  (falling back to the Common list if it hasn't been built).
  `render_token()` is a text-only monochrome renderer reusing
  `app/printer/render.py`'s font/wrap helpers. `POST /api/tokens/preview` takes a
  `token_id` (from either list) or the fields of a one-off custom token and
  stashes the image in `state.pending` like a summoned card, so the existing
  `/api/print` prints it. The response carries `is_token: true` so the UI hides
  Reroll/Regenerate. Recent tokens live in `localStorage` as whole objects
  (`momir_token_recent_v2`), so they work for any token in the full list;
  custom tokens aren't saved.
  Art: each full-list token keeps the `scryfall_id` (and `face`, front/back, since
  double-faced tokens share one Scryfall card) of its newest printing — the builder
  walks sets newest-first, so the first sighting wins. `card_art.fetch_token_art()`
  gets the art crop in one request to Scryfall's `/cards/<id>?format=image`
  (it redirects straight to the image), caches it in `data/art_cache/` as
  `token_<id>[_back]`, and returns None on any failure, so offline just prints
  without art. It honors the same "Fetch card art" setting as cards. The Common
  list and custom tokens carry no id: `tokens.art_source()` borrows the
  most-printed full-list token with the same name and power/toughness, and a custom
  token with no match prints text-only. `render_token()` crops the art to
  `ART_ASPECT` and autocontrasts it before the final dither. A token list built
  before this (schema 1) has no ids and needs a rebuild to get art.
- `app/static/` — vanilla HTML/CSS/JS, no build step, no CDN dependencies. The `/`
  route in `main.py` does not serve `index.html` as a static file as-is — it injects
  a content-hash query string (`?v=<md5>`) onto the `/static/app.js` and
  `/static/style.css` URLs so browsers can't silently keep serving a stale cached
  copy after a deploy. Also holds a toggle-able life/hand/land tracker (for games
  played with two piles of basic lands instead of real decks) that's entirely
  client-side — state (enabled flag + per-player life/hand/lands) lives in
  `localStorage` under `momir_tracker_state`, no server route involved. Player
  count (1-8, default 2) and the three per-player counters are rendered fresh
  from that state on every mutation; "Reset Game" puts every current player back
  to 20 life / 7 cards / 0 lands after a `window.confirm()`.
- `panel/` — a second, independent FastAPI app (own uvicorn process, own systemd
  unit `momir-panel.service`, port 80) that's always on regardless of whether the
  print app itself is running — that's the point of it. `panel/main.py` holds the
  routes plus a lifespan-managed background reconciliation loop (`ReconcileLoop`)
  that re-evaluates wlan0's target connection every ~20s (and immediately after any
  saved-network mutation, via an `asyncio.Event` nudge). `panel/network.py` wraps
  `nmcli` for scanning, saved-network CRUD/reorder, and AP up/down; `connection
  .autoconnect-priority` on each saved nmcli profile is the only place ordering is
  stored — no separate JSON list to drift out of sync. `panel/service_ctl.py`
  wraps `systemctl` via a `ServiceController` class parametrized by unit name;
  `panel/main.py` instantiates one per managed service (`momir.service`,
  `momir-printsvc.service`, `momir-upload.service`, `momir-esp32svc.service`)
  and registers the same four routes
  (`status`/`start`/`stop`/`enable`/`disable` under `/api/<prefix>/...`)
  for each via a loop, rather than tripling the route definitions. Both wrapper
  modules check `shutil.which(...)` and degrade to `{"supported": False}` rather
  than erroring, the same "swallow and degrade" pattern `app/card_art.py` uses for
  offline art lookups — this is what lets the panel run for frontend iteration on
  a Mac, where neither binary exists. All subprocess calls pass argument lists,
  never a shell string, since SSIDs/passwords are user-supplied. `panel/main.py`
  runs as the same unprivileged user as the services it controls (not root); it
  gets `systemctl start/stop/enable/disable` on each of the four managed units
  (sixteen literal invocations total) plus full `nmcli` access via a scoped
  `/etc/sudoers.d/momir-panel` grant installed by `setup_pi_ap.sh` (systemctl is
  pinned to those literal invocations; nmcli is granted broadly, since its
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
  avahi for `http://momir.local`, installs `scripts/momir-printsvc.service`,
  `scripts/momir.service`, `scripts/momir-upload.service`,
  `scripts/momir-esp32svc.service`, and `scripts/momir-panel.service` as
  systemd units (printsvc first, then the apps that depend on it), installs
  `scripts/99-momir-esp32.rules` as a udev rule mapping the ESP32's USB
  vendor/product ID (`MOMIR_ESP32_USB_VENDOR_ID`/`MOMIR_ESP32_USB_PRODUCT_ID`
  env vars, defaulting to the common CP2102 USB-serial chip's IDs) to a
  stable `/dev/momir-esp32`, and installs the `/etc/sudoers.d/momir-panel`
  grant described above.

## Outstanding work

See TODO.md for planned/in-progress features and known issues.

## Workflow

Changes are made on a branch, pushed, and opened as a PR against `main` on GitHub
(`PlazmaEssence/momir-basic`); there's no CI, so "testing before merge" means running
locally with the mock driver and/or checking out the branch directly on the Pi to
exercise it against the real printer hardware. The Pi's own checkout (`~/momir`)
tracks `main` and is updated with a plain `git pull` after merging.
