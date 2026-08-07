# TODO

Outstanding work and ideas for Momir Vig.

## Features

- [x] **Full-card print mode.** Add a print mode that prints the actual Scryfall
      card image as-is (full frame, art, and text) instead of the current custom
      render (name/cost/type/text composited with just the art crop). Likely a
      setting alongside the existing driver/paper-width/art options — something
      like "Custom layout" (current) vs. "Full card image."
- [x] **Regenerate a pending card.** If a card has already been summoned/previewed
      and the print settings change before it's printed (e.g. switching between
      full-card mode and the custom render), add a "Regenerate" action that
      re-renders the *same* card with the new settings, rather than requiring a
      reroll (which picks a new random card).
- [x] **Version number on the page.** Show a version identifier somewhere on the
      control page (e.g. next to the status line) so it's easy to confirm which
      deployed version is running, especially when comparing Mac vs. Pi. Probably
      the short git commit hash, read at startup.
- [x] **Printer connection indicator (red/green icon).** Status line now shows
      a colored dot (green = connected, red = disconnected) driven by
      `printer.connected` from `/api/health`, replacing the old ●/○ text glyph.
- [x] **Color preview for full-card layout.** When `card_layout` is
      `full_card`, the web preview now shows the original color Scryfall image
      (`render_card_full_preview()` in `app/printer/render.py`) while the token
      stashed for `/api/print` still holds the dithered B&W image
      (`render_card_full()`), so printing is unaffected.
- [x] **Exclude cards never printed in paper.** `build_db.py` now cross-
      references each card's `printings` against MTGJSON's `SetList.json.gz`
      (`isOnlineOnly` per set, auto-downloaded to `data/SetList.json.gz`) and
      drops cards whose printings are all online-only — catches ~500 Arena-only
      creatures that didn't have the `A-` prefix. Falls back to no filtering if
      the file can't be fetched, rather than failing the build.
- [x] **Port-80 control panel: service toggle + Wi-Fi priority/AP fallback.**
      New `panel/` app (separate FastAPI process, `momir-panel.service`, port
      80, http://momir.local) with a page to start/stop `momir.service` and
      toggle whether it starts on boot, plus a live-editable, priority-ordered
      list of Wi-Fi networks for `wlan0` to join. A background reconciliation
      loop in `panel/network.py` picks the best available target every ~20s —
      highest-priority saved SSID in range, else idle if Ethernet has a link,
      else the `MomirVig` AP — replacing the old fixed choice between
      `setup_pi_ap.sh` (AP-only) and the now-deleted `setup_pi_wifi.sh`
      (fixed two-SSID client). Runs as the unprivileged app user via a scoped
      `/etc/sudoers.d/momir-panel` grant rather than as root.
- [x] **Print-from-upload app.** New `upload/` app (port 8001) lets anyone on
      the network print an arbitrary uploaded image or a block of text on
      the same thermal printer the card app uses — resized/dithered to the
      configured paper width, with a height clamp on tall images, upload
      size/content-type validation, and text options (bold first-line title,
      small/medium/large font size). Extracted printer-connection ownership
      into a new shared `printsvc/` (port 8002, 127.0.0.1 only) so the card
      app and the upload app never race to claim the same USB/serial device;
      both now call it over HTTP to print instead of holding their own
      driver. `panel/service_ctl.py` is now parametrized by unit name so the
      control panel has start/stop/start-on-boot cards for all three backend
      services, not just `momir.service`.
- [x] **Deckless life/hand/land tracker.** Since games are actually played with
      two piles of basic lands rather than real decks, add a toggle-able panel
      on the main page for tracking life, cards in hand, and lands in play by
      hand — no more pen and paper. Defaults to 2 players, life 20 / hand 7 /
      lands 0 each; supports adding/removing players for multiplayer (1-8) and
      a "Reset Game" button (with a confirm dialog) that puts every player back
      at the defaults. Pure client-side (`localStorage`), no backend involved.
- [ ] **ESP32 physical display/control panel.** A 2.8" ESP32 LVGL touchscreen
      wired to the Pi over USB as a physical alternative to the browser UI:
      +/- to pick a mana value, hold a button to summon+print, no card art
      shown on screen. New `esp32svc/` (port 8003, 127.0.0.1 only) owns the
      serial link and drives it by calling `app/main.py`'s existing
      `/api/summon` + `/api/print` over HTTP — no changes to the card app
      itself. Backend (`esp32svc/`, systemd unit,
      udev rule, panel integration) is done and smoke-tested against a
      virtual serial port; `firmware/esp32_display/` has the LVGL UI +
      serial protocol logic but still needs board-specific display/touch
      driver configuration (`lv_conf.h`, TFT_eSPI `User_Setup.h`, touch chip
      wiring) filled in once actual hardware is in hand — see that
      directory's README.

## Known issues

(none currently)
