"""
A documentary's thumbnail, designed rather than taken from the opening
still (decision 086).

The first film's thumbnail was its opening still with all nine words of
its title across the bottom: Lincoln under 3% of the frame, the title
said twice. What breakout thumbnails share is one subject filling about
a third of the frame, strong contrast, and a few words that add to the
title instead of repeating it. So:

- the picture is drawn for the purpose, from the chosen angle's
  thumbnail idea (pipeline.documentary.pitch), in the channel's look and
  with the cast's model sheets: one subject, close, lit, on the left;
  if it can't be drawn, the film's strongest close-up still stands in;
- its words (four at most) go on a dark panel beside it, big, the first
  line in the channel's accent.

The variants for Studio's Test & Compare (core.thumbnail_tests) change
one setting of this design at a time: text size, accent, panel colour.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from core.errors import PipelineError
from core.logging_setup import get_logger

log = get_logger(__name__)

SIZE = (1280, 720)
PICTURE_SHARE = 0.6             # of the width, the subject's side
ART_NAME = "thumb_art.jpg"


def _font(size: int, face: str):
    from pipeline.assemble import load_font
    return load_font(size, face)


def _hex(colour: str, fallback=(255, 212, 0)) -> tuple:
    try:
        c = colour.lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except (AttributeError, ValueError, IndexError):
        return fallback


def picture(channel, data: dict, folder: Path, pictures: dict) -> tuple:
    """(the thumbnail's picture, "" or why the stand-in was used): drawn
    once from the angle's idea, kept in the production folder."""
    from core import production
    folder = Path(folder)
    kept = folder / ART_NAME
    angle = production.packaging(data)
    subject = (angle.get("thumbnail") or {}).get("subject") or ""
    # Kept only while it shows the same idea in the same look: the remade
    # drill film came out with the old cartoon drill on its thumbnail
    # (decision 091).
    from pipeline.documentary import stills as storyboard
    key = storyboard.fingerprint({"subject": subject, "look": storyboard.look_for(channel).get("description", "")})
    stamp = kept.with_suffix(".key")
    if kept.exists() and (not stamp.exists() or stamp.read_text(encoding="utf-8") == key):
        if not stamp.exists():
            stamp.write_text(key, encoding="utf-8")
        return kept, ""
    kept.unlink(missing_ok=True)
    note = ""
    if subject:
        try:
            from pipeline.documentary import stills
            names = [m["name"] for m in (data.get("outline") or {}).get("cast") or []
                     if m["name"].split(" (")[0].lower() in subject.lower()]
            drawn = stills.draw_one(channel, data["outline"], (
                f"A thumbnail picture: {subject}. One subject only, large and close, on the left two "
                f"thirds of the frame, strongly lit with clear contrast and a readable expression; "
                f"the right third quiet and dark, nothing important there."), names, folder, "close-up")
            drawn.replace(kept)
            stamp.write_text(key, encoding="utf-8")
            return kept, ""
        except PipelineError as exc:
            note = f"Thumbnail picture couldn't be drawn ({exc.user_message}); a still stands in."
            log.warning(f"  [documentary] {note}")
    scenes = (data.get("script") or {}).get("scenes") or []
    close = [i for i, s in enumerate(scenes) if s.get("framing") in ("close-up", "extreme close-up")
             and s.get("cast") and i in pictures]
    stand_in = pictures.get(close[0] if close else min(pictures))
    return Path(stand_in), note


def compose(picture_path: Path, words: str, art: dict, recipe: dict = None) -> Image.Image:
    """The designed thumbnail: the subject on the left, the words big on a
    panel on the right; without words, the picture alone."""
    recipe = recipe or {}
    w, h = SIZE
    image = Image.open(picture_path).convert("RGB")
    image = ImageEnhance.Color(ImageEnhance.Contrast(image).enhance(1.18)).enhance(1.1)
    words = " ".join((words or "").split()[:4]).upper()
    if not words:
        return image.resize(SIZE, Image.LANCZOS)
    panel_colour = {"dark": (18, 18, 22), "accent": _hex(art.get("accent2"), (46, 139, 139))}.get(
        recipe.get("background"), (22, 24, 30))
    pw = int(w * PICTURE_SHARE)
    # The picture's left part, at full height, fills the subject's side.
    iw, ih = image.size
    scale = h / ih
    crop_w = min(iw, int(pw / scale))
    side = image.crop((0, 0, crop_w, ih)).resize((pw, h), Image.LANCZOS)
    canvas = Image.new("RGB", SIZE, panel_colour)
    canvas.paste(side, (0, 0))
    fade = 220
    mask = Image.linear_gradient("L").rotate(90).resize((fade, h))
    canvas.paste(Image.new("RGB", (fade, h), panel_colour), (pw - fade, 0), mask)
    draw = ImageDraw.Draw(canvas)
    key = recipe.get("accent") or "a1"           # a recipe's accent: a1 to a5, or ink
    accent = (255, 255, 255) if key == "ink" else _hex(art.get(f"accent{key[1:]}") or art.get("accent1"),
                                                        (255, 212, 0))
    face = art.get("font_thumb") or "Segoe UI Black"     # a heavy sans reads at phone size
    lines = _lines(words)
    left, right = pw - 60, w - 36
    size = int(150 * float(recipe.get("text_scale") or 1.0))
    while size > 60:
        font = _font(size, face)
        if max(draw.textlength(line, font=font) for line in lines) <= right - left:
            break
        size -= 6
    font = _font(size, face)
    line_h = int(size * 1.08)
    y = (h - line_h * len(lines)) // 2
    for n, line in enumerate(lines):
        x = left + (right - left - draw.textlength(line, font=font)) / 2
        draw.text((x, y), line, font=font, fill=accent if n == 0 else (255, 255, 255),
                  stroke_width=max(4, size // 22), stroke_fill=(10, 10, 12))
        y += line_h
    return canvas


def _lines(words: str) -> list:
    """Two or three short lines from up to four words."""
    parts = words.split()
    if len(parts) <= 2:
        return parts
    if len(parts) == 3:
        return [parts[0], " ".join(parts[1:])] if len(parts[0]) > 4 else [" ".join(parts[:2]), parts[2]]
    return [" ".join(parts[:2]), " ".join(parts[2:])]


def make(channel, data: dict, pictures: dict, title: str, video_path: Path, art: dict) -> str:
    """The film's thumbnail beside it. Returns "" or what went wrong."""
    from core import production
    folder = production.folder(channel.key, data["subtopic_id"])
    out = Path(video_path).with_name(f"{Path(video_path).stem}_thumb.jpg")
    try:
        art_path, note = picture(channel, data, folder, pictures)
        words = (production.packaging(data).get("thumbnail") or {}).get("words", "")
        compose(art_path, words, art).save(out, quality=90)
        return note
    except Exception as exc:  # noqa: BLE001 - a plainer thumbnail beats none
        log.warning(f"  [documentary] designed thumbnail failed ({exc}); the opening still is used")
        from pipeline.documentary.render import thumbnail
        thumbnail(pictures[min(pictures)], title, art).save(out, quality=90)
        return "The designed thumbnail failed; the opening still was used."


def retitled(channel, data: dict, video_path: Path) -> None:
    """A made film given another angle's title (decision 090): its stored
    title and its thumbnail's words changed, the picture kept. Free."""
    from core import gallery, production
    angle = production.packaging(data)
    info = gallery.load_publish_info(video_path)
    gallery.save_title_and_description(video_path, angle["title"], info.get("description") or "")
    folder = production.folder(channel.key, data["subtopic_id"])
    stills = {int(k): folder / v for k, v in (data.get("stills") or {}).items()}
    art_path = folder / ART_NAME if (folder / ART_NAME).exists() else stills[min(stills)]
    out = Path(video_path).with_name(f"{Path(video_path).stem}_thumb.jpg")
    compose(art_path, (angle.get("thumbnail") or {}).get("words", ""), dict(channel.scenes.art or {})).save(
        out, quality=90)


def render_variant(channel, video_path: Path, recipe: dict, out: Path) -> Path:
    """One Test & Compare variant of a documentary's thumbnail."""
    from core import production
    sidecar = Path(video_path).with_name(f"{Path(video_path).stem}_production.json")
    info = json.loads(sidecar.read_text(encoding="utf-8"))
    data = production.load(info["channel"], info["subtopic_id"])
    folder = production.folder(info["channel"], info["subtopic_id"])
    stills = {int(k): folder / v for k, v in (data.get("stills") or {}).items()}
    art_path = folder / ART_NAME if (folder / ART_NAME).exists() else stills[min(stills)]
    words = (production.packaging(data).get("thumbnail") or {}).get("words", "")
    compose(art_path, words, dict(channel.scenes.art or {}), recipe).save(out, quality=90)
    return Path(out)


AB_COUNT = 3                       # what YouTube's A/B test takes: three of each


def ab_folder(video_path: Path) -> Path:
    return Path(video_path).with_name(f"{Path(video_path).stem}_ab")


def ab_variants(channel, data: dict, video_path: Path) -> dict:
    """Three titles and three thumbnails to A/B test in Studio (decision
    114): the film's own, then the pitch's next best angles. The second
    thumbnail puts the next angle's words on the film's picture (free);
    the third draws that angle's own picture (about three cents). Kept in
    `<stem>_ab/` beside the video, with ab.json listing them."""
    from core import production
    own = production.packaging(data)
    angles = [a for a in (data.get("pitch") or {}).get("angles") or [] if a.get("title") and a is not own
              and a.get("title") != own.get("title")]
    angles.sort(key=lambda a: -(a.get("score") or 0))
    pick = [own] + angles[:AB_COUNT - 1]
    folder = ab_folder(video_path)
    folder.mkdir(parents=True, exist_ok=True)
    art = dict(channel.scenes.art or {})
    production_folder = production.folder(channel.key, data["subtopic_id"])
    stills = {int(k): production_folder / v for k, v in (data.get("stills") or {}).items()}
    own_art = production_folder / ART_NAME if (production_folder / ART_NAME).exists() else stills[min(stills)]
    thumbs = [Path(video_path).with_name(f"{Path(video_path).stem}_thumb.jpg")]
    for n, angle in enumerate(pick[1:], start=2):
        words = (angle.get("thumbnail") or {}).get("words", "")
        out = folder / f"thumb_{n}.jpg"
        picture_path = own_art
        subject = (angle.get("thumbnail") or {}).get("subject", "")
        if n == AB_COUNT and subject:
            try:
                from pipeline.documentary import stills as storyboard
                drawn = storyboard.draw_one(channel, data["outline"], (
                    f"A thumbnail picture: {subject}. One subject only, large and close, on the left two "
                    f"thirds of the frame, strongly lit with clear contrast; the right third quiet and dark, "
                    f"nothing important there."), [], folder / "art", "close-up")
                picture_path = drawn
            except PipelineError as exc:
                log.warning(f"  [documentary] A/B thumbnail {n} picture couldn't be drawn ({exc}); the film's is used")
        compose(picture_path, words, art).save(out, quality=90)
        thumbs.append(out)
    listed = {"titles": [a["title"] for a in pick], "thumbs": [str(t.name if t.parent != folder else
                                                                    f"{folder.name}/{t.name}") for t in thumbs]}
    (folder / "ab.json").write_text(json.dumps(listed, indent=1), encoding="utf-8")
    return listed


def load_ab(video_path: Path) -> dict:
    try:
        return json.loads((ab_folder(video_path) / "ab.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def is_documentary(video_path: Path) -> bool:
    sidecar = Path(video_path).with_name(f"{Path(video_path).stem}_production.json")
    try:
        return bool(json.loads(sidecar.read_text(encoding="utf-8")).get("documentary"))
    except (OSError, ValueError):
        return False
