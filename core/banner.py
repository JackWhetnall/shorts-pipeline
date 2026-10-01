"""
A channel's YouTube banner, drawn from its own logo, colours and font
(decision 058).

Drawn locally rather than by an image model: it costs nothing, it can be
made again in a second when the tagline changes, and the name is always
spelled right (image models misspell). The colours and typeface are the
channel's own (core.channels Style), so it matches its videos' cards.

YouTube shows the 2560x1440 picture differently on each screen. A TV shows
all of it, a desktop a 2560x423 strip across the middle, and a phone only
the middle 1546x423. So everything that must be seen sits inside that
"safe area" in the centre, and the rest is just background that carries
the colour out to the edges.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core import fonts
from core.logging_setup import get_logger
from core.paths import CHANNELS_DIR, channel_logo_dir

log = get_logger(__name__)

SIZE = (2560, 1440)
SAFE_W, SAFE_H = 1546, 423
SAFE = ((SIZE[0] - SAFE_W) // 2, (SIZE[1] - SAFE_H) // 2, (SIZE[0] + SAFE_W) // 2, (SIZE[1] + SAFE_H) // 2)
VARIANTS = ("split", "centered")
LABELS = {"split": "Logo beside the name", "centered": "Name in the middle"}
MAX_TAGLINE = 60


def banner_dir(channel_key: str) -> Path:
    return CHANNELS_DIR / channel_key / "banner"


def path_for(channel_key: str, variant: str) -> Path:
    return banner_dir(channel_key) / f"banner_{variant}.png"


def exists(channel_key: str) -> bool:
    return any(path_for(channel_key, v).exists() for v in VARIANTS)


def _rgb(value, default=(10, 10, 14)) -> tuple:
    if isinstance(value, str) and value.startswith("#") and len(value) >= 7:
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return tuple(int(c) for c in value[:3])
    return default


def _luma(rgb: tuple) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _mix(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _font(face_key: str, size: int):
    path = fonts.resolve_or_default(face_key)
    try:
        return ImageFont.truetype(str(path), size) if path else ImageFont.load_default()
    except OSError:
        return ImageFont.load_default()


def _width(draw, text: str, font) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left


def _wrap(draw, text: str, face_key: str, max_w: int, max_size: int, min_size: int, max_lines: int):
    """(font, lines) at the largest size where `text` fits `max_w` in at
    most `max_lines` lines, shrinking to `min_size` before giving up."""
    words = text.split()
    size = max_size
    while True:
        font = _font(face_key, size)
        lines, line = [], ""
        for word in words:
            trial = f"{line} {word}".strip()
            if _width(draw, trial, font) <= max_w or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
        fits = len(lines) <= max_lines and all(_width(draw, ln, font) <= max_w for ln in lines)
        if fits or size <= min_size:
            return font, lines
        size -= 6


def _background(colors: dict) -> Image.Image:
    """The brand colour, lifted a little in the middle so it isn't flat,
    with a soft glow of the accent colour behind where the logo sits."""
    base, accent = colors["bg"], colors["accent"]
    w, h = SIZE
    image = Image.new("RGB", SIZE, base)
    lift = Image.new("RGB", SIZE, _mix(base, colors["ink"], 0.10))
    mask = Image.new("L", SIZE, 0)
    ImageDraw.Draw(mask).ellipse((w * 0.12, -h * 0.25, w * 0.88, h * 1.25), fill=255)
    image.paste(lift, mask=mask.filter(ImageFilter.GaussianBlur(260)))
    glow = Image.new("RGB", SIZE, _mix(base, accent, 0.45))
    glow_mask = Image.new("L", SIZE, 0)
    cx, cy = SAFE[0] + 220, h // 2
    ImageDraw.Draw(glow_mask).ellipse((cx - 330, cy - 330, cx + 330, cy + 330), fill=110)
    image.paste(glow, mask=glow_mask.filter(ImageFilter.GaussianBlur(120)))
    # Quiet diagonal bars at both ends, in what a desktop crops away.
    draw = ImageDraw.Draw(image, "RGBA")
    for i, x in enumerate(range(-200, 360, 120)):
        alpha = 20 - i * 3
        if alpha > 0:
            draw.polygon([(x, h), (x + 90, h), (x + 90 + 700, 0), (x + 700, 0)], fill=(*accent, alpha))
    for i, x in enumerate(range(w + 200, w - 360, -120)):
        alpha = 20 - i * 3
        if alpha > 0:
            draw.polygon([(x, h), (x - 90, h), (x - 90 - 700, 0), (x - 700, 0)], fill=(*accent, alpha))
    return image


def _logo(channel_key: str, size: int):
    path = channel_logo_dir(channel_key) / "logo.png"
    if not path.exists():
        return None
    logo = Image.open(path).convert("RGBA")
    return logo.resize((size, size), Image.LANCZOS)


def _colors(channel) -> dict:
    style = channel.style
    bg = _rgb(style.outro_bg_color)
    title = _rgb(style.outro_title_color, (255, 255, 255))
    accent = _rgb(style.outro_subtext_color, (255, 212, 0))
    # Text must read against the background whatever the palette is.
    if abs(_luma(title) - _luma(bg)) < 90:
        title = (255, 255, 255) if _luma(bg) < 128 else (20, 20, 20)
    if abs(_luma(accent) - _luma(bg)) < 60:
        accent = title
    return {"bg": bg, "title": title, "accent": accent, "ink": title}


def render(channel, tagline: str = "", variant: str = "split") -> Image.Image:
    """The banner as a 2560x1440 picture."""
    if variant not in VARIANTS:
        variant = VARIANTS[0]
    colors = _colors(channel)
    image = _background(colors)
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = SAFE
    face = channel.style.font_face
    name = (channel.channel_display_name or channel.key).strip()
    tagline = " ".join((tagline or "").split())[:MAX_TAGLINE]
    cy = (y0 + y1) // 2

    if variant == "split":
        logo = _logo(channel.key, 340)
        text_x = x0 + (340 + 70 if logo else 20)
        if logo:
            image.paste(logo, (x0 + 20, cy - 170), logo)
        max_w = x1 - text_x - 70
        name_font, name_lines = _wrap(draw, name, face, max_w, 170, 70, 2)
        tag_font, tag_lines = _wrap(draw, tagline, face, max_w, 58, 36, 2) if tagline else (None, [])
        name_h = sum(_font_height(draw, name_font) for _ in name_lines)
        tag_h = sum(_font_height(draw, tag_font) for _ in tag_lines) if tag_lines else 0
        gap = 34 if tag_lines else 0
        top = cy - (name_h + gap + tag_h + (14 if tag_lines else 0)) // 2
        for line in name_lines:
            draw.text((text_x, top), line, font=name_font, fill=colors["title"])
            top += _font_height(draw, name_font)
        if tag_lines:
            top += gap - 6
            draw.rectangle((text_x, top - 14, text_x + 150, top - 8), fill=colors["accent"])
            for line in tag_lines:
                draw.text((text_x, top + 6), line, font=tag_font, fill=colors["accent"])
                top += _font_height(draw, tag_font)
    else:
        logo = _logo(channel.key, 210)
        max_w = SAFE_W - 40 - (210 + 50 if logo else 0)
        name_font, name_lines = _wrap(draw, name, face, max_w, 170, 70, 2)
        name_w = max(_width(draw, ln, name_font) for ln in name_lines)
        name_h = sum(_font_height(draw, name_font) for _ in name_lines)
        group_w = name_w + (210 + 50 if logo else 0)
        left = (SIZE[0] - group_w) // 2
        tag_font, tag_lines = _wrap(draw, tagline, face, SAFE_W - 40, 58, 36, 2) if tagline else (None, [])
        tag_h = sum(_font_height(draw, tag_font) for _ in tag_lines) if tag_lines else 0
        block_h = max(name_h, 210 if logo else 0) + (40 + tag_h if tag_lines else 0)
        top = cy - block_h // 2
        row_h = max(name_h, 210 if logo else 0)
        if logo:
            image.paste(logo, (left, top + (row_h - 210) // 2), logo)
        ty = top + (row_h - name_h) // 2
        tx = left + (210 + 50 if logo else 0)
        for line in name_lines:
            draw.text((tx, ty), line, font=name_font, fill=colors["title"])
            ty += _font_height(draw, name_font)
        if tag_lines:
            ty = top + row_h + 40
            for line in tag_lines:
                width = _width(draw, line, tag_font)
                draw.text(((SIZE[0] - width) // 2, ty), line, font=tag_font, fill=colors["accent"])
                ty += _font_height(draw, tag_font)
    return image


def _font_height(draw, font) -> int:
    left, top, right, bottom = draw.textbbox((0, 0), "Hgy", font=font)
    return int((bottom - top) * 1.18)


def make(channel, tagline: str = "") -> dict:
    """Draw both layouts into the channel's folder. {variant: path}."""
    folder = banner_dir(channel.key)
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for variant in VARIANTS:
        path = path_for(channel.key, variant)
        render(channel, tagline, variant).save(path, optimize=True)
        out[variant] = path
    return out
