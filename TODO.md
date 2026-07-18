# TODO

Outstanding work and ideas for Momir Vig.

## Features

- [ ] **Full-card print mode.** Add a print mode that prints the actual Scryfall
      card image as-is (full frame, art, and text) instead of the current custom
      render (name/cost/type/text composited with just the art crop). Likely a
      setting alongside the existing driver/paper-width/art options — something
      like "Custom layout" (current) vs. "Full card image."
- [ ] **Regenerate a pending card.** If a card has already been summoned/previewed
      and the print settings change before it's printed (e.g. switching between
      full-card mode and the custom render), add a "Regenerate" action that
      re-renders the *same* card with the new settings, rather than requiring a
      reroll (which picks a new random card).
- [ ] **Version number on the page.** Show a version identifier somewhere on the
      control page (e.g. next to the status line) so it's easy to confirm which
      deployed version is running, especially when comparing Mac vs. Pi. Probably
      the short git commit hash, read at startup.

## Known issues

(none currently)
