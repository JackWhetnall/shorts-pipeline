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
# Drawn in each channel's own look (decision 084): the two it used to
# have came from the end card's colours, near-black on every channel, in
# one layout, so every channel's banner looked the same.
VARIANTS = ("brand", "picture")
LABELS = {"brand": "In its own look", "picture": "With its own picture"}
OLD_VARIANTS = ("split", "centered")
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
    """Draw both designs into the channel's folder. {variant: path}. A
    design the page renderer can't draw falls back to the plain drawing."""
    folder = banner_dir(channel.key)
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for variant, fallback in zip(VARIANTS, OLD_VARIANTS):
        path = path_for(channel.key, variant)
        try:
            from pipeline.scenes import render as pages
            jpeg = pages.page_frame(page_html(channel, tagline, variant), 0.0, size=SIZE)
            import io
            Image.open(io.BytesIO(jpeg)).convert("RGB").save(path, optimize=True)
        except Exception as exc:  # noqa: BLE001 - a plainer banner beats none
            log.warning(f"{channel.key}: banner {variant} drawn plainly ({exc})")
            render(channel, tagline, fallback).save(path, optimize=True)
        out[variant] = path
    for old in OLD_VARIANTS:
        path_for(channel.key, old).unlink(missing_ok=True)
    return out


# --- in the channel's own look ---------------------------------------------------------

def _words(channel) -> list:
    """What the channel covers, for a row of chips: its quiz categories,
    or its plan's topics, short ones first."""
    try:
        from core import curriculum
        if not curriculum.exists(channel.key):
            return []
        topics = [t["title"] for t in curriculum.load(channel.key)["topics"] if not t.get("placeholder")]
    except Exception:  # noqa: BLE001 - chips are decoration
        return []
    short = [t for t in topics if len(t) <= 26]
    return (short or topics)[:6]


def picture(channel) -> Path:
    """A picture of the channel's own work for a backdrop, or None: a
    documentary's style frame or latest storyboard still; for a footage
    channel, a frame of its latest video. A quiz's picture is its board,
    drawn in its look, so it has none."""
    if channel.format == "quiz":
        return None
    if channel.format == "documentary":
        stills = sorted((CHANNELS_DIR / channel.key / "productions").glob("*/stills/kf_*.jpg"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
        if stills:
            return stills[0]
        frames = sorted((CHANNELS_DIR / channel.key / "animation").glob("*/style_*.png"))
        return frames[0] if frames else None
    from core import gallery
    root = gallery.resolve_output_dir(channel.output_dir)
    if not root.exists():
        return None
    videos = [v for v in sorted(gallery.videos_in(root, long=False), key=lambda v: v.stat().st_mtime, reverse=True)
              if not gallery.load_publish_info(v)["discarded"]][:4]
    return _best_frame(channel, videos)


def _colourfulness(image) -> float:
    """Hasler and Süsstrunk's colourfulness, plus contrast: a frame of a
    sunset over hills scores well, a grey door handle doesn't."""
    import numpy as np
    a = np.asarray(image.convert("RGB").resize((160, 90)), dtype=np.float32)
    rg, yb = a[..., 0] - a[..., 1], 0.5 * (a[..., 0] + a[..., 1]) - a[..., 2]
    colour = np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    return float(colour + 0.5 * a.mean(axis=2).std())


def _best_frame(channel, videos: list):
    """The most colourful frame from a few points in each video (wide
    enough for a banner once cropped), saved beside the banner."""
    import subprocess
    import imageio_ffmpeg
    best, score = None, -1.0
    folder = banner_dir(channel.key)
    folder.mkdir(parents=True, exist_ok=True)
    for i, video in enumerate(videos):
        for j, at in enumerate((5, 14, 24, 36)):
            frame = folder / f"candidate_{i}_{j}.jpg"
            try:
                subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-ss", str(at), "-i", str(video),
                                "-frames:v", "1", "-q:v", "2", str(frame)], check=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                with Image.open(frame) as im:
                    s = _colourfulness(im)
            except Exception:  # noqa: BLE001 - past the end, or unreadable: the next one
                continue
            if s > score:
                best, score = frame, s
    if best is None:
        return None
    chosen = folder / "frame.jpg"
    chosen.write_bytes(best.read_bytes())
    for leftover in folder.glob("candidate_*.jpg"):
        leftover.unlink(missing_ok=True)
    return chosen


def _data_uri(path: Path) -> str:
    import base64
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def page_html(channel, tagline: str, variant: str) -> str:
    """The banner as a page in the channel's look (pipeline.templates.theme),
    everything that matters inside the centre a phone shows."""
    import html
    from pipeline.scenes import art
    from pipeline.templates import page, theme
    esc = html.escape
    style = art.resolve(channel.scenes.art)
    name = esc((channel.channel_display_name or channel.key).strip())
    tag = esc(" ".join((tagline or "").split())[:MAX_TAGLINE])
    logo_path = channel_logo_dir(channel.key) / "logo.png"
    logo = f"<img class='logo' src='{_data_uri(logo_path)}'>" if logo_path.exists() else ""
    chips = "".join(f"<span class='chip filled a{(i % 5) + 1}'>{esc(w)}</span>"
                    for i, w in enumerate(_words(channel)))
    x0, y0, x1, y1 = SAFE
    quiz = channel.format == "quiz"
    base = f"""
    html, body {{ width: {SIZE[0]}px; height: {SIZE[1]}px; margin: 0; overflow: hidden; }}
    .safe {{ position: absolute; left: {x0}px; top: {y0}px; width: {SAFE_W}px; height: {SAFE_H}px;
      display: flex; align-items: center; gap: 56px; }}
    .logo {{ width: 300px; height: 300px; object-fit: contain; flex: none; border-radius: 50%; }}
    .words {{ display: flex; flex-direction: column; gap: 18px; min-width: 0; }}
    .name {{ font-family: var(--display); font-weight: var(--dw); font-size: 150px; line-height: .95;
      color: var(--ink); letter-spacing: -.01em; }}
    .tag {{ font-size: 52px; line-height: 1.15; color: var(--soft); }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 14px; }}
    .chips .chip {{ font-size: 30px; padding: 8px 24px; }}
    .wide {{ position: absolute; inset: 0; }}
    """
    if variant == "brand":
        motif = ""
        if quiz:
            # Its stamp, as on every short's opening screen.
            motif = (f"<div class='stamp'>{tag or name}</div>")
            css = base + """
            .stamp { align-self: flex-start; margin-top: 18px; padding: 18px 44px; border-radius: 28px;
              background: var(--a1); color: var(--on-a1); border: 7px solid var(--ink);
              font-family: var(--display); font-weight: var(--dw); text-transform: uppercase;
              font-size: 40px; line-height: 1.15; transform: rotate(-4deg); box-shadow: 0 12px 0 rgba(0,0,0,.2);
              max-width: 1000px; }
            .mark { position: absolute; left: 150px; top: 50%; transform: translateY(-52%) rotate(-8deg);
              font-family: var(--display); font-weight: var(--dw); font-size: 900px; line-height: 1;
              color: var(--a2); opacity: .16; }
            """
            body = (f"<div class='mark'>?</div><div class='safe'>{logo}<div class='words'>"
                    f"<div class='name'>{name}</div>{motif}</div></div>")
        else:
            css = base + """
            .rule { width: 160px; height: 10px; border-radius: 5px; background: var(--a1); }
            .band { position: absolute; left: 0; right: 0; top: 0; height: 26px; background: var(--a1); }
            .band.b { top: auto; bottom: 0; background: var(--a2); }
            """
            body = (f"<div class='band'></div><div class='band b'></div><div class='safe'>{logo}<div class='words'>"
                    f"<div class='name'>{name}</div><div class='rule'></div>"
                    + (f"<div class='tag'>{tag}</div>" if tag else "") +
                    f"<div class='chips'>{chips}</div></div></div>")
    else:
        pic = picture(channel)
        title, accent = _rgb(channel.style.highlight_color, (255, 212, 0)), None
        if pic is not None:
            css = base + f"""
            .wide img {{ width: 100%; height: 100%; object-fit: cover; }}
            .shade {{ position: absolute; inset: 0; background:
              linear-gradient(90deg, rgba(0,0,0,.82) 0%, rgba(0,0,0,.62) 45%, rgba(0,0,0,.15) 80%); }}
            .name {{ color: #fff; text-shadow: 0 6px 30px rgba(0,0,0,.5); }}
            .tag {{ color: rgb{title}; }}
            """
            body = (f"<div class='wide'><img src='{_data_uri(pic)}'></div><div class='shade'></div>"
                    f"<div class='safe'>{logo}<div class='words'><div class='name'>{name}</div>"
                    + (f"<div class='tag'>{tag}</div>" if tag else "") + "</div></div>")
        else:
            # No picture of its own (a quiz): its board's look, dark.
            css = base + """
            .bg { background: var(--ink) !important; }
            .name { color: var(--bg); } .tag { color: var(--a1); }
            .mark { position: absolute; right: 150px; top: 50%; transform: translateY(-50%) rotate(8deg);
              font-family: var(--display); font-weight: var(--dw); font-size: 760px; line-height: 1; color: var(--a1); }
            """
            body = (f"<div class='mark'>?</div><div class='safe'>{logo}<div class='words'>"
                    f"<div class='name'>{name}</div>"
                    + (f"<div class='tag'>{tag}</div>" if tag else "") +
                    f"<div class='chips'>{chips}</div></div></div>")
    return ("<!doctype html><html><head><meta charset='utf-8'><style>"
            f"{theme.css(style)}{css}.bg-grain {{ background-image: url({page.GRAIN}); }}"
            "</style></head><body><div class='bg'><div class='bg-pattern'></div><div class='bg-grain'></div>"
            f"<div class='bg-vignette'></div></div>{body}"
            "<script>window.TEMPLATE_DURATION = 1;</script>"
            f"<script>{page.RUNTIME.read_text(encoding='utf-8')}</script></body></html>")
