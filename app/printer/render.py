"""
Composes a single card object into one dithered, monochrome PIL image ready
for thermal printing. Both the mock driver (saves this straight to a PNG)
and the real ESC/POS driver (prints this image via raster bit-image mode)
consume the exact same image, so what you see in the browser/PNG preview is
what comes out of the printer.
"""
import re
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS_DIR = Path(__file__).parent / "fonts"
FONT_REGULAR = FONTS_DIR / "DejaVuSans.ttf"
FONT_BOLD = FONTS_DIR / "DejaVuSans-Bold.ttf"

# Printable pixel width for common thermal paper widths at ~203dpi
PAPER_WIDTH_PX = {80: 576, 58: 384}
MARGIN = 16


def _width_for_paper(paper_width_mm: float) -> int:
    nearest = min(PAPER_WIDTH_PX, key=lambda mm: abs(mm - paper_width_mm))
    if abs(nearest - paper_width_mm) <= 5:
        return PAPER_WIDTH_PX[nearest]
    return int(paper_width_mm / 25.4 * 203)


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def format_mana_cost(raw: str | None) -> str:
    if not raw:
        return ""
    symbols = re.findall(r"\{([^}]+)\}", raw)
    return " ".join(symbols) if symbols else raw


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        words = paragraph.split(" ")
        current = ""
        for word in words:
            trial = f"{current} {word}".strip()
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = word
        lines.append(current)
    return lines


def render_card(card: dict, art_path: Path | None = None, paper_width_mm: float = 80) -> Image.Image:
    width = _width_for_paper(paper_width_mm)
    content_width = width - 2 * MARGIN

    name_font = _font(FONT_BOLD, max(18, width // 22))
    cost_font = _font(FONT_REGULAR, max(16, width // 26))
    type_font = _font(FONT_REGULAR, max(15, width // 28))
    text_font = _font(FONT_REGULAR, max(14, width // 30))
    pt_font = _font(FONT_BOLD, max(20, width // 18))
    footer_font = _font(FONT_REGULAR, max(11, width // 40))

    # Scratch canvas just to measure text before we know the final height
    scratch = Image.new("L", (width, 10), 255)
    draw = ImageDraw.Draw(scratch)

    mana_cost = format_mana_cost(card.get("mana_cost"))
    rules_text = (card.get("text") or "").strip()
    text_lines = _wrap_text(draw, rules_text, text_font, content_width) if rules_text else []

    art_img = None
    if art_path and Path(art_path).exists():
        try:
            art_img = Image.open(art_path).convert("L")
            art_target_w = content_width
            art_target_h = int(art_img.height * (art_target_w / art_img.width))
            art_img = art_img.resize((art_target_w, art_target_h), Image.LANCZOS)
        except Exception:
            art_img = None

    line_gap = 6
    name_h = name_font.size + line_gap
    type_h = type_font.size + line_gap
    text_h = (text_font.size + 4) * len(text_lines) + line_gap if text_lines else 0
    pt_h = pt_font.size + line_gap
    footer_h = footer_font.size + line_gap
    art_h = art_img.height + line_gap if art_img else 0
    divider_h = 2 + line_gap

    total_h = (
        MARGIN
        + name_h
        + type_h
        + divider_h
        + art_h
        + text_h
        + pt_h
        + divider_h
        + footer_h
        + MARGIN
    )

    img = Image.new("L", (width, total_h), 255)
    draw = ImageDraw.Draw(img)
    y = MARGIN

    display_name = card.get("name", "Unknown Creature")
    draw.text((MARGIN, y), display_name, font=name_font, fill=0)
    if mana_cost:
        cost_w = draw.textlength(mana_cost, font=cost_font)
        draw.text((width - MARGIN - cost_w, y + (name_font.size - cost_font.size)), mana_cost, font=cost_font, fill=0)
    y += name_h

    type_line = card.get("type_line") or ""
    draw.text((MARGIN, y), type_line, font=type_font, fill=0)
    y += type_h

    draw.line([(MARGIN, y), (width - MARGIN, y)], fill=0, width=2)
    y += divider_h

    if art_img:
        img.paste(art_img, (MARGIN, y))
        y += art_h

    for line in text_lines:
        draw.text((MARGIN, y), line, font=text_font, fill=0)
        y += text_font.size + 4
    if text_lines:
        y += line_gap

    power, toughness = card.get("power"), card.get("toughness")
    if power is not None and toughness is not None:
        pt_text = f"{power}/{toughness}"
        pt_w = draw.textlength(pt_text, font=pt_font)
        draw.text((width - MARGIN - pt_w, y), pt_text, font=pt_font, fill=0)
    y += pt_h

    draw.line([(MARGIN, y), (width - MARGIN, y)], fill=0, width=2)
    y += divider_h

    footer_bits = [b for b in [card.get("set_code"), "Momir Vig"] if b]
    footer = "  •  ".join(footer_bits)
    draw.text((MARGIN, y), footer, font=footer_font, fill=128)

    # Final pass: hard dither to pure black/white for thermal output
    return img.convert("1", dither=Image.FLOYDSTEINBERG)


def render_card_full_preview(image_path: Path) -> Image.Image:
    """Loads the full Scryfall card image as-is, in color, for on-screen
    preview only. The printer always gets the dithered monochrome version
    from render_card_full() below."""
    return Image.open(image_path).convert("RGB")


def render_card_full(image_path: Path, paper_width_mm: float = 80) -> Image.Image:
    """Loads the full Scryfall card image as-is (frame, art, and text baked
    in) and scales it to the paper's pixel width, preserving aspect ratio."""
    width = _width_for_paper(paper_width_mm)
    img = Image.open(image_path).convert("L")
    target_h = int(img.height * (width / img.width))
    img = img.resize((width, target_h), Image.LANCZOS)
    return img.convert("1", dither=Image.FLOYDSTEINBERG)
