"""Turns an uploaded image or a block of text into a single printable PIL
image at the configured paper width, with the same monochrome dithering step
app/printer/render.py uses for cards — so what's printed here comes out the
same way through the shared print service."""
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont

from app.printer.render import FONT_BOLD, FONT_REGULAR, _width_for_paper

MARGIN = 16
# An uploaded image can be scaled to at most this many multiples of the
# paper's width in height before being cropped, so a tall/high-res photo
# can't accidentally print a multi-foot receipt.
MAX_IMAGE_HEIGHT_RATIO = 3

FONT_POINT_SIZES = {"small": 20, "medium": 26, "large": 34}


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


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


def render_image(image: Image.Image, paper_width_mm: float) -> Image.Image:
    """Resizes an arbitrary uploaded image to the paper's pixel width
    (preserving aspect ratio), clamps runaway height, and dithers to
    monochrome for thermal printing."""
    width = _width_for_paper(paper_width_mm)
    image = image.convert("L")
    scaled_h = int(image.height * (width / image.width))
    image = image.resize((width, scaled_h), Image.LANCZOS)
    max_h = int(width * MAX_IMAGE_HEIGHT_RATIO)
    if scaled_h > max_h:
        image = image.crop((0, 0, width, max_h))
    return image.convert("1", dither=Image.FLOYDSTEINBERG)


def render_text(text: str, paper_width_mm: float, font_size: str = "medium", bold_title: bool = False) -> Image.Image:
    """Renders a plain-text block for printing. If bold_title, the first
    non-empty line prints larger and bold, like a receipt header."""
    width = _width_for_paper(paper_width_mm)
    content_width = width - 2 * MARGIN
    size = FONT_POINT_SIZES.get(font_size, FONT_POINT_SIZES["medium"])
    body_font = _font(FONT_REGULAR, size)
    title_font = _font(FONT_BOLD, int(size * 1.3))

    lines = text.strip("\n").split("\n")
    title_line = None
    body_lines = lines
    if bold_title and lines and lines[0].strip():
        title_line = lines[0]
        body_lines = lines[1:]

    scratch = Image.new("L", (width, 10), 255)
    draw = ImageDraw.Draw(scratch)

    wrapped_title = _wrap_text(draw, title_line, title_font, content_width) if title_line else []
    wrapped_body = _wrap_text(draw, "\n".join(body_lines), body_font, content_width)

    line_gap = 6
    title_h = (title_font.size + 4) * len(wrapped_title) + (line_gap if wrapped_title else 0)
    body_h = (body_font.size + 4) * len(wrapped_body)
    total_h = MARGIN * 2 + title_h + body_h

    img = Image.new("L", (width, total_h), 255)
    draw = ImageDraw.Draw(img)
    y = MARGIN
    for line in wrapped_title:
        draw.text((MARGIN, y), line, font=title_font, fill=0)
        y += title_font.size + 4
    if wrapped_title:
        y += line_gap
    for line in wrapped_body:
        draw.text((MARGIN, y), line, font=body_font, fill=0)
        y += body_font.size + 4

    return img.convert("1", dither=Image.FLOYDSTEINBERG)


def render_qr(data: str, paper_width_mm: float) -> Image.Image:
    """Renders `data` (typically a URL) as a QR code sized to the paper's
    pixel width. Picks a whole-pixel module size (box_size) that fits the
    printable width rather than generating at a fixed size and resizing —
    resizing a QR code with interpolation blurs module edges and can make it
    unscannable once dithered/thresholded to monochrome."""
    width = _width_for_paper(paper_width_mm)
    content_width = width - 2 * MARGIN

    probe = qrcode.QRCode()
    probe.add_data(data)
    probe.make(fit=True)
    modules = len(probe.get_matrix())

    box_size = max(1, content_width // modules)
    qr = qrcode.QRCode(box_size=box_size)
    qr.add_data(data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("L")

    img = Image.new("L", (width, qr_img.height + 2 * MARGIN), 255)
    x = max(0, (width - qr_img.width) // 2)
    img.paste(qr_img, (x, MARGIN))
    return img.convert("1")
