"""
Thumbnail styles for a documentary channel's films (decision 115).

Every film's thumbnail used to come out of one layout: the subject on the
left, two or three words on a dark panel on the right. The tests could
only nudge its text size, accent and tilt, so three "different"
thumbnails were the same thumbnail. The owner's point: find the style
first (layout, font, colours, the kind of picture, straight or angled
text), then refine it, and only then test each film's own words and
picture.

A style is a recipe of a few settings. `FAMILIES` are whole, distinct
styles to test against each other; `PARAMS` are the settings a winning
style is then refined over, one at a time. `draw` renders any recipe.
The family "panel" is the original look, drawn by `thumbs.compose`, so a
channel that hasn't tested anything still gets exactly what it had.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from core.logging_setup import get_logger

log = get_logger(__name__)

SIZE = (1280, 720)
FONTS_DIR = Path("C:/Windows/Fonts")

# Font key: (file, variation name or None). A face that isn't installed
# falls back to the channel's thumbnail face.
FONTS = {
    "black": ("seguibl.ttf", None),               # Segoe UI Black: the original
    "impact": ("impact.ttf", None),
    "arial_black": ("ariblk.ttf", None),
    "condensed": ("bahnschrift.ttf", b"Bold Condensed"),
    "serif": ("georgiab.ttf", None),
    "slab": ("ROCKEB.TTF", None),                 # Rockwell Extra Bold
    "rounded": ("GILSANUB.TTF", None),            # Gill Sans Ultra Bold
}

# The whole styles tested against each other first. Each is a full recipe.
FAMILIES = {
    "panel": {"layout": "panel_right", "font": "black", "colours": "accent_white", "tilt": 0,
              "picture": "art", "effect": "outline", "grade": "punchy", "text_scale": 1.0},
    "band": {"layout": "band_bottom", "font": "impact", "colours": "dark_on_accent", "tilt": 0,
             "picture": "scene", "effect": "none", "grade": "punchy", "text_scale": 1.0},
    "sticker": {"layout": "sticker", "font": "arial_black", "colours": "dark_on_accent", "tilt": -5,
                "picture": "art", "effect": "none", "grade": "punchy", "text_scale": 1.0},
    "overlay": {"layout": "overlay", "font": "condensed", "colours": "white", "tilt": 0,
                "picture": "scene", "effect": "shadow", "grade": "natural", "text_scale": 1.0},
    "pop": {"layout": "center", "font": "impact", "colours": "yellow_pop", "tilt": 4,
            "picture": "art", "effect": "outline", "grade": "punchy", "text_scale": 1.0},
    "classic": {"layout": "panel_left", "font": "serif", "colours": "white", "tilt": 0,
                "picture": "scene", "effect": "shadow", "grade": "natural", "text_scale": 1.0},
    "playful": {"layout": "overlay_top", "font": "rounded", "colours": "accent", "tilt": -3,
                "picture": "art", "effect": "outline", "grade": "punchy", "text_scale": 0.9},
}
FAMILY_NAMES = {"panel": "Side panel", "band": "Bottom band", "sticker": "Sticker", "overlay": "Text over picture",
                "pop": "Big centred", "classic": "Classic serif", "playful": "Playful"}

# The settings a winning style is refined over, one change at a time:
# name: (options or (low, high), step for a number).
PARAMS = {
    "text_scale": ((0.75, 1.35), 0.15),
    "tilt": ((-10.0, 10.0), 4.0),
    "colours": (("accent_white", "white", "accent", "dark_on_accent", "yellow_pop"), None),
    "font": (tuple(FONTS), None),
    "picture": (("art", "scene"), None),
    "effect": (("outline", "shadow", "none"), None),
    "grade": (("punchy", "natural"), None),
}
SETTING_NAMES = {"text_scale": "text size", "tilt": "tilt", "colours": "colours", "font": "font",
                 "picture": "picture", "effect": "text edge", "grade": "colour grade"}


def full(recipe: dict) -> dict:
    """A recipe with every setting: its family's, then its own."""
    recipe = recipe or {}
    return {**FAMILIES.get(recipe.get("family") or "panel", FAMILIES["panel"]), **recipe}


def describe(recipe: dict) -> str:
    """"Sticker · Arial Black · tilted": a recipe in a few words, for a page."""
    r = full(recipe)
    bits = [FAMILY_NAMES.get(r.get("family") or "panel", r.get("family", "")),
            r["font"].replace("_", " "), r["colours"].replace("_", " ")]
    if r["tilt"]:
        bits.append("tilted")
    bits.append("close-up" if r["picture"] == "art" else "wide scene")
    return " · ".join(b for b in bits if b)


# --- drawing ------------------------------------------------------------------------------

def _hex(colour: str, fallback=(255, 212, 0)) -> tuple:
    try:
        c = colour.lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except (AttributeError, ValueError, IndexError):
        return fallback


def _font(key: str, size: int, art: dict):
    name, variation = FONTS.get(key, FONTS["black"])
    path = FONTS_DIR / name
    try:
        font = ImageFont.truetype(str(path), size)
        if variation:
            font.set_variation_by_name(variation)
        return font
    except (OSError, ValueError):
        from pipeline.assemble import load_font
        return load_font(size, art.get("font_thumb") or "Segoe UI Black")


def _cover(image: Image.Image, size: tuple, focus_x: float = 0.4) -> Image.Image:
    """The picture scaled to fill `size`, cropped around `focus_x`."""
    w, h = size
    scale = max(w / image.width, h / image.height)
    resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    left = min(max(0, round(resized.width * focus_x - w / 2)), resized.width - w)
    top = (resized.height - h) // 2
    return resized.crop((left, top, left + w, top + h))


def _lines(words: str) -> list:
    parts = words.split()
    if len(parts) <= 2:
        return parts
    if len(parts) == 3:
        return [parts[0], " ".join(parts[1:])] if len(parts[0]) > 4 else [" ".join(parts[:2]), parts[2]]
    return [" ".join(parts[:2]), " ".join(parts[2:])]


def _colours(r: dict, art: dict) -> tuple:
    """(first line colour, other lines' colour, fill behind the text or None, outline colour)."""
    accent = _hex(art.get("accent1"), (255, 178, 63))
    dark = _hex(art.get("background"), (16, 26, 58))
    white = (255, 255, 255)
    scheme = r["colours"]
    if scheme == "white":
        return white, white, None, (10, 10, 14)
    if scheme == "accent":
        return accent, accent, None, (10, 10, 14)
    if scheme == "dark_on_accent":
        return dark, dark, accent, accent
    if scheme == "yellow_pop":
        return (255, 225, 77), (255, 225, 77), None, (0, 0, 0)
    return accent, white, None, (10, 10, 14)                     # accent_white


def _text_layer(lines: list, r: dict, art: dict, box: tuple, align: str = "center",
                labels: bool = True) -> Image.Image:
    """The words as a transparent layer the size of `box` (w, h), fitted,
    coloured and edged as the recipe says. `labels`: each line on its own
    coloured label when the colours have a fill (a sticker); off where the
    layout draws the fill itself (a band)."""
    bw, bh = box
    first, rest, fill, edge = _colours(r, art)
    if not labels:
        fill = None
    layer = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    # The split that lets the words be biggest: as given, one line, or a
    # word to a line (a narrow panel takes a word a line far bigger).
    words = " ".join(lines).split()
    stacked = []
    for word in words:                     # "A" or "OF" never alone: it rides with the next word
        if stacked and len(stacked[-1]) <= 2 and len(stacked[-1].split()) == 1:
            stacked[-1] = f"{stacked[-1]} {word}"
        else:
            stacked.append(word)
    splits = [lines, [" ".join(words)]] + ([stacked] if 2 < len(stacked) <= 4 else [])
    best = (0, lines)
    for option in splits:
        size = int(170 * float(r.get("text_scale") or 1.0))
        while size > 40:
            font = _font(r["font"], size, art)
            widest = max(draw.textlength(line, font=font) for line in option)
            if widest <= bw * 0.92 and size * 1.1 * len(option) <= bh * 0.9:
                break
            size -= 6
        if size > best[0]:
            best = (size, option)
    size, lines = best
    font = _font(r["font"], size, art)
    line_h = int(size * 1.1)
    y = (bh - line_h * len(lines)) // 2
    pad = int(size * 0.22)
    for n, line in enumerate(lines):
        width = draw.textlength(line, font=font)
        x = {"left": int(bw * 0.04), "right": bw - width - int(bw * 0.04)}.get(align, (bw - width) / 2)
        if fill is not None:                    # a label behind each line (sticker, band)
            draw.rounded_rectangle((x - pad, y - pad * 0.4, x + width + pad, y + line_h + pad * 0.2),
                                   radius=int(size * 0.12), fill=(*fill, 255))
        colour = first if n == 0 else rest
        if r["effect"] == "shadow":
            shadow = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
            ImageDraw.Draw(shadow).text((x + size * 0.05, y + size * 0.07), line, font=font, fill=(0, 0, 0, 170))
            layer = Image.alpha_composite(layer, shadow.filter(ImageFilter.GaussianBlur(size * 0.06)))
            draw = ImageDraw.Draw(layer)
        stroke = max(4, size // 18) if r["effect"] == "outline" else 0
        draw.text((x, y), line, font=font, fill=(*colour, 255), stroke_width=stroke, stroke_fill=(*edge, 255))
        y += line_h
    if r.get("tilt"):
        layer = layer.rotate(float(r["tilt"]), resample=Image.BICUBIC, expand=False)
    return layer


def draw(art_path: Path, scene_path: Path, words: str, art: dict, recipe: dict) -> Image.Image:
    """A thumbnail in the recipe's style. `art_path`: the film's thumbnail
    picture (a close subject); `scene_path`: one of its storyboard pictures
    (a wide scene), used when the recipe asks for one."""
    from pipeline.documentary import thumbs
    r = full(recipe)
    words = " ".join((words or "").split()[:4]).upper()
    if r.get("family", "panel") == "panel" and all(r[k] == FAMILIES["panel"][k] for k in FAMILIES["panel"]):
        # The original look, exactly as it was.
        return thumbs.compose(art_path, words, art, {})
    source = scene_path if r["picture"] == "scene" and scene_path and Path(scene_path).exists() else art_path
    image = Image.open(source).convert("RGB")
    contrast, colour = (1.2, 1.25) if r["grade"] == "punchy" else (1.05, 1.05)
    image = ImageEnhance.Color(ImageEnhance.Contrast(image).enhance(contrast)).enhance(colour)
    w, h = SIZE
    lines = _lines(words) or [""]
    dark = _hex(art.get("background"), (16, 26, 58))
    layout = r["layout"]
    if layout in ("panel_right", "panel_left"):
        canvas = Image.new("RGB", SIZE, dark)
        pw = int(w * 0.58)
        side = _cover(image, (pw, h), 0.35 if layout == "panel_right" else 0.65)
        x = 0 if layout == "panel_right" else w - pw
        canvas.paste(side, (x, 0))
        fade = 200
        mask = Image.linear_gradient("L").rotate(90 if layout == "panel_right" else -90).resize((fade, h))
        canvas.paste(Image.new("RGB", (fade, h), dark), (pw - fade if layout == "panel_right" else w - pw, 0), mask)
        box = (w - pw + 40, h)
        layer = _text_layer(lines, r, art, box)
        canvas = canvas.convert("RGBA")
        canvas.alpha_composite(layer, (pw - 40 if layout == "panel_right" else 0, 0))
        return canvas.convert("RGB")
    canvas = _cover(image, SIZE, 0.45).convert("RGBA")
    if layout == "band_bottom":
        band_h = int(h * 0.34)
        _, _, fill, _ = _colours(r, art)
        canvas.alpha_composite(Image.new("RGBA", (w, band_h), (*(fill or dark), 255)), (0, h - band_h))
        joined = " ".join(lines)
        layer = _text_layer([joined] if len(joined) <= 20 else lines, r, art, (w, band_h), labels=False)
        canvas.alpha_composite(layer, (0, h - band_h))
        return canvas.convert("RGB")
    if layout in ("overlay", "overlay_top"):
        shade = Image.linear_gradient("L").rotate(90 if layout == "overlay" else 180).resize(SIZE)
        canvas.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", SIZE, (0, 0, 0)).split(),
                                                    shade.point(lambda v: int(v * 0.75)))))
        box = (int(w * 0.62), h if layout == "overlay" else int(h * 0.55))
        layer = _text_layer(lines, r, art, box, align="left")
        canvas.alpha_composite(layer, (0, 0))
        return canvas.convert("RGB")
    if layout == "sticker":
        layer = _text_layer(lines, r, art, (int(w * 0.55), int(h * 0.6)))
        canvas.alpha_composite(layer, (int(w * 0.43), int(h * 0.2)))
        return canvas.convert("RGB")
    # center: the picture dimmed, the words big across the middle
    canvas.alpha_composite(Image.new("RGBA", SIZE, (0, 0, 0, 95)))
    layer = _text_layer(lines, r, art, (int(w * 0.9), int(h * 0.8)))
    canvas.alpha_composite(layer, (int(w * 0.05), int(h * 0.1)))
    return canvas.convert("RGB")
