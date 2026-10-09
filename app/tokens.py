"""
Curated list of common Commander tokens plus a renderer that composes one
token into the same dithered, monochrome PIL image the card renderer produces,
so it flows through the existing pending-token -> /api/print path unchanged.
"""
import json

from PIL import Image, ImageDraw

from .build_tokens import TOKENS_PATH
from .printer.render import FONT_BOLD, FONT_REGULAR, MARGIN, _font, _width_for_paper, _wrap_text

# "colors" is only used for the swatch dots in the web UI; the print is B&W.
TOKENS = [
    {"id": "treasure", "name": "Treasure", "type_line": "Token Artifact — Treasure", "colors": ["C"],
     "text": "{T}, Sacrifice this artifact: Add one mana of any color."},
    {"id": "clue", "name": "Clue", "type_line": "Token Artifact — Clue", "colors": ["C"],
     "text": "{2}, Sacrifice this artifact: Draw a card."},
    {"id": "food", "name": "Food", "type_line": "Token Artifact — Food", "colors": ["C"],
     "text": "{2}, {T}, Sacrifice this artifact: You gain 3 life."},
    {"id": "blood", "name": "Blood", "type_line": "Token Artifact — Blood", "colors": ["C"],
     "text": "{1}, {T}, Discard a card, Sacrifice this artifact: Draw a card."},
    {"id": "soldier", "name": "Soldier", "type_line": "Token Creature — Soldier", "colors": ["W"],
     "power": "1", "toughness": "1", "text": ""},
    {"id": "spirit", "name": "Spirit", "type_line": "Token Creature — Spirit", "colors": ["W"],
     "power": "1", "toughness": "1", "text": "Flying"},
    {"id": "angel", "name": "Angel", "type_line": "Token Creature — Angel", "colors": ["W"],
     "power": "4", "toughness": "4", "text": "Flying, vigilance"},
    {"id": "thopter", "name": "Thopter", "type_line": "Token Artifact Creature — Thopter", "colors": ["C"],
     "power": "1", "toughness": "1", "text": "Flying"},
    {"id": "zombie", "name": "Zombie", "type_line": "Token Creature — Zombie", "colors": ["B"],
     "power": "2", "toughness": "2", "text": ""},
    {"id": "rat", "name": "Rat", "type_line": "Token Creature — Rat", "colors": ["B"],
     "power": "1", "toughness": "1", "text": ""},
    {"id": "goblin", "name": "Goblin", "type_line": "Token Creature — Goblin", "colors": ["R"],
     "power": "1", "toughness": "1", "text": ""},
    {"id": "dragon", "name": "Dragon", "type_line": "Token Creature — Dragon", "colors": ["R"],
     "power": "5", "toughness": "5", "text": "Flying"},
    {"id": "elemental", "name": "Elemental", "type_line": "Token Creature — Elemental", "colors": ["R"],
     "power": "3", "toughness": "1", "text": "Haste"},
    {"id": "saproling", "name": "Saproling", "type_line": "Token Creature — Saproling", "colors": ["G"],
     "power": "1", "toughness": "1", "text": ""},
    {"id": "elf-warrior", "name": "Elf Warrior", "type_line": "Token Creature — Elf Warrior", "colors": ["G"],
     "power": "1", "toughness": "1", "text": ""},
    {"id": "beast", "name": "Beast", "type_line": "Token Creature — Beast", "colors": ["G"],
     "power": "3", "toughness": "3", "text": ""},
    {"id": "wolf", "name": "Wolf", "type_line": "Token Creature — Wolf", "colors": ["G"],
     "power": "2", "toughness": "2", "text": ""},
    {"id": "human", "name": "Human", "type_line": "Token Creature — Human", "colors": ["W"],
     "power": "1", "toughness": "1", "text": ""},
    {"id": "squirrel", "name": "Squirrel", "type_line": "Token Creature — Squirrel", "colors": ["G"],
     "power": "1", "toughness": "1", "text": ""},
    {"id": "insect", "name": "Insect", "type_line": "Token Creature — Insect", "colors": ["G"],
     "power": "1", "toughness": "1", "text": ""},
]

_BY_ID = {t["id"]: t for t in TOKENS}

# The full list from MTGJSON (see build_tokens.py), loaded lazily and reloaded
# when the file changes so a finished rebuild shows up without a restart.
_full_cache: dict = {"mtime": None, "tokens": [], "by_id": {}}


def full_tokens() -> list[dict]:
    try:
        mtime = TOKENS_PATH.stat().st_mtime_ns
    except OSError:
        return []
    if _full_cache["mtime"] != mtime:
        try:
            tokens = json.loads(TOKENS_PATH.read_text())["tokens"]
        except (OSError, ValueError, KeyError):
            return []
        _full_cache.update(mtime=mtime, tokens=tokens, by_id={t["id"]: t for t in tokens})
    return _full_cache["tokens"]


def get_token(token_id: str) -> dict | None:
    if token_id in _BY_ID:
        return _BY_ID[token_id]
    full_tokens()
    return _full_cache["by_id"].get(token_id)


def search(query: str, limit: int = 60) -> list[dict]:
    """Name/type search over the full list (or the starter list if the full
    one hasn't been built). Names that start with the query rank first, then
    by how many sets the token was printed in (a proxy for how common it is)."""
    corpus = full_tokens() or TOKENS
    terms = query.lower().split()
    if not terms:
        return []

    def haystack(t):
        return f"{t['name']} {t['type_line']}".lower()

    matches = [t for t in corpus if all(term in haystack(t) for term in terms)]
    first = terms[0]
    matches.sort(key=lambda t: (not t["name"].lower().startswith(first), -t.get("printings", 0), t["name"]))
    return matches[:limit]


def _clean_rules(text: str) -> str:
    # The printer can't draw mana/tap symbols: spell out tap, and drop the
    # braces on mana costs the same way the card renderer does ("{2}" -> "2").
    return text.replace("{T}", "Tap").replace("{", "").replace("}", "")


def render_token(token: dict, paper_width_mm: float = 80) -> Image.Image:
    width = _width_for_paper(paper_width_mm)
    inner = width - 2 * MARGIN
    pad = 14

    label_font = _font(FONT_REGULAR, max(12, width // 36))
    type_font = _font(FONT_REGULAR, max(15, width // 28))
    text_font = _font(FONT_REGULAR, max(15, width // 28))
    pt_font = _font(FONT_BOLD, max(40, width // 8))

    scratch = ImageDraw.Draw(Image.new("L", (width, 10), 255))

    # Shrink the name until it fits on one line, down to a floor; past that,
    # wrap it rather than letting it run off the edge.
    name = token.get("name", "Token")
    name_size = max(36, width // 9)
    name_font = _font(FONT_BOLD, name_size)
    while name_size > 24 and scratch.textlength(name, font=name_font) > inner - 2 * pad:
        name_size -= 2
        name_font = _font(FONT_BOLD, name_size)
    name_lines = _wrap_text(scratch, name, name_font, inner - 2 * pad)

    rules = _clean_rules((token.get("text") or "").strip())
    text_lines = _wrap_text(scratch, rules, text_font, inner - 2 * pad) if rules else []
    type_lines = _wrap_text(scratch, token.get("type_line", ""), type_font, inner - 2 * pad)

    power, toughness = token.get("power"), token.get("toughness")
    has_pt = bool(power) and bool(toughness)

    gap = 8
    label_h = label_font.size + gap
    name_h = (name_font.size + 4) * len(name_lines) + gap * 2
    type_h = (type_font.size + 4) * len(type_lines) + gap
    text_h = (text_font.size + 4) * len(text_lines) + gap if text_lines else 0
    pt_h = pt_font.size + gap * 2 if has_pt else 0
    box_h = pad + label_h + name_h + type_h + text_h + pt_h + pad

    img = Image.new("L", (width, box_h + 2 * MARGIN), 255)
    draw = ImageDraw.Draw(img)
    draw.rectangle([MARGIN, MARGIN, width - MARGIN, MARGIN + box_h], outline=0, width=4)

    x = MARGIN + pad
    y = MARGIN + pad
    draw.text((x, y), "TOKEN", font=label_font, fill=0)
    y += label_h

    for line in name_lines:
        draw.text((x, y), line, font=name_font, fill=0)
        y += name_font.size + 4
    y += gap * 2
    draw.line([(x, y - gap), (width - MARGIN - pad, y - gap)], fill=0, width=2)

    for line in type_lines:
        draw.text((x, y), line, font=type_font, fill=0)
        y += type_font.size + 4
    y += gap

    for line in text_lines:
        draw.text((x, y), line, font=text_font, fill=0)
        y += text_font.size + 4
    if text_lines:
        y += gap

    if has_pt:
        pt_text = f"{power}/{toughness}"
        pt_w = scratch.textlength(pt_text, font=pt_font)
        draw.text((width - MARGIN - pad - pt_w, y), pt_text, font=pt_font, fill=0)

    return img.convert("1", dither=Image.FLOYDSTEINBERG)
