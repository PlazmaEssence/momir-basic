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

## Known issues

(none currently)
