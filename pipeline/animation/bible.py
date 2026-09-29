"""
A channel's animation bible: the pictures its look rests on.

- **Style frames.** Three finished frames of the channel's world, drawn
  once in its look. One of them (the chosen one) goes into every keyframe
  as the style reference, which is what makes every shot of every video
  look like the same film. Drawn again only when the look itself changes
  (preset, notes or palette: `look.identity`).
- **The cast.** Recurring characters (the channel's `animation.cast`):
  a model sheet each, front, three-quarter and side, drawn in the style
  frame's hand and passed to every keyframe they appear in.

Both are drawn on first need, so a channel works without anyone visiting
its settings, and kept under channels/<key>/animation/<look>/ with a
bible.json saying what each picture was drawn from. Per-video characters
and places are drawn the same way into the video's own folder
(`element_sheet`).
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from core.logging_setup import get_logger
from core.paths import channel_animation_dir, slugify
from pipeline.animation import images, look as looks, models

log = get_logger(__name__)

FRAME_COUNT = 3
_lock = threading.Lock()


def folder(channel_key: str, look: dict) -> Path:
    return channel_animation_dir(channel_key, look["key"])


def load(channel_key: str, look: dict) -> dict:
    path = folder(channel_key, look) / "bible.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("frames", [])
    data.setdefault("prompts", [])
    data.setdefault("chosen", 0)
    data.setdefault("cast", {})
    return data


def _save(channel_key: str, look: dict, data: dict) -> None:
    d = folder(channel_key, look)
    d.mkdir(parents=True, exist_ok=True)
    (d / "bible.json").write_text(json.dumps(data, indent=1), encoding="utf-8")


def frames(channel_key: str, look: dict) -> list:
    """The style frames on disk for this look, current or not."""
    d = folder(channel_key, look)
    return [d / f for f in load(channel_key, look)["frames"] if (d / f).exists()]


def current(channel_key: str, look: dict) -> bool:
    """Whether the style frames on disk were drawn in this look."""
    data = load(channel_key, look)
    return bool(frames(channel_key, look)) and data.get("identity") == look["identity"]


# --- style frames -----------------------------------------------------------

FRAME_IDEAS = """
You are the art director of an animated short-form channel. Describe three
style frames: finished pictures that show what this channel's world looks
like, so every later frame can be drawn to match them.

- One wide establishing picture of a place typical of the channel.
- One medium shot of a person or character in a characteristic moment.
- One close, intimate detail: hands, an object, light on a surface.

Each is one or two concrete sentences a painter could work from: what is
in the frame, where, and the light and mood. Typical of the channel's
subjects, not of one video. No text, signs or writing in any of them.
""".strip()


def _frame_ideas(channel, look: dict) -> list:
    from pipeline.llm import call_json

    topics = _sample_topics(channel)
    schema = {"type": "object", "properties": {"frames": {
        "type": "array", "items": {"type": "string"}}},
        "required": ["frames"], "additionalProperties": False}
    user = (f"Channel: {channel.channel_display_name or channel.key}\n"
            f"What it makes: {(channel.style_prompt or '')[:900]}\n"
            f"Some of its subjects: {'; '.join(topics) or 'not yet planned'}\n"
            f"Its look: {look['label']}: {look['description']}")
    data = call_json(FRAME_IDEAS, user, schema, operation="animation_style_ideas",
                     max_tokens=3000)
    ideas = [" ".join(str(f).split()) for f in data.get("frames") or [] if str(f).strip()]
    fallback = ["A wide view of a place typical of this channel, in soft light.",
                "A person in a quiet, characteristic moment, medium shot.",
                "A close detail: hands and an everyday object, catching the light."]
    return (ideas + fallback)[:FRAME_COUNT]


def _sample_topics(channel) -> list:
    titles = [str(t) for t in (channel.topics or [])[:8]]
    try:
        from core import curriculum
        titles += [row.get("title", "") for row in curriculum.load(channel.key)["subtopics"][:10]]
    except Exception:  # noqa: BLE001 - topics only flavour the ideas; none is fine
        pass
    return [t for t in titles if t][:10]


def frame_prompt(idea: str, look: dict) -> str:
    return (f"{idea}\n\nThis is a style frame for an animated series: the picture every later "
            f"frame must match in medium, rendering, palette and light. A finished, beautiful, "
            f"fully realised frame, not a sketch.\n{looks.style_text(look)}\n{looks.FRAME_RULES}")


def draw_style_frames(channel, look: dict) -> list:
    """Three new style frames for this channel in this look, replacing any
    it had. About 20 cents."""
    ideas = _frame_ideas(channel, look)
    d = folder(channel.key, look)
    model = models.image_model(models.BIBLE_IMAGE_MODEL)
    names = []
    for i, idea in enumerate(ideas):
        name = f"style_{look['identity']}_{i + 1}.png"
        images.draw(frame_prompt(idea, look), d / name, model,
                    operation="animation_style_frame")
        names.append(name)
    with _lock:
        data = load(channel.key, look)
        for old in data["frames"]:
            if old not in names:
                (d / old).unlink(missing_ok=True)
        old_sheet = data.pop("sheet", None)
        if old_sheet:
            (d / old_sheet).unlink(missing_ok=True)
        data.update({"identity": look["identity"], "frames": names, "prompts": ideas,
                     "chosen": 0, "cast": {}})
        _save(channel.key, look, data)
    log.info(f"  [animation] drew {len(names)} style frames for {channel.key} ({look['label']})")
    return [d / n for n in names]


def choose(channel_key: str, look: dict, index: int) -> None:
    with _lock:
        data = load(channel_key, look)
        if 0 <= index < len(data["frames"]):
            data["chosen"] = index
            # The sheet and the cast were drawn from the old frame; redraw
            # them on next use.
            data["cast"] = {}
            data.pop("sheet", None)
            _save(channel_key, look, data)


def chosen_frame(channel, look: dict) -> Path:
    """The chosen style frame, drawing the frames first if this look has
    none (or has changed since they were drawn)."""
    if not current(channel.key, look):
        draw_style_frames(channel, look)
    data = load(channel.key, look)
    available = frames(channel.key, look)
    index = data["chosen"] if data["chosen"] < len(available) else 0
    return available[index]


# A style frame is a scene, and a picture model given a scene as its style
# reference copies the scene too: the first test put the style frame's
# study, arched window and moon behind half the shots of a video about
# yawning. Every video on the channel would have had that room. So what
# every keyframe is drawn with is a sheet of small unrelated studies in
# the chosen frame's hand: all of its style, none of its content.
STYLE_SHEET = (
    "An art-style reference sheet, drawn in exactly the style of the reference picture: the "
    "same medium, line quality, rendering, texture, palette and light. Take nothing else from "
    "it: none of its people, places or objects. On a plain background, a loose grid of eight "
    "small, separate, unrelated studies: the head of an old man in three-quarter view, the head "
    "of a young child laughing, a pair of hands, a tree in wind, the corner of a stone "
    "building, a dusk sky with clouds, a still life of a cup and a pear, a patch of rippling "
    "water. Each study finished in the style, with generous space between them. No text, "
    "labels, numbers or borders.")


def reference(channel, look: dict) -> Path:
    """The style reference every keyframe and sheet is drawn with: the
    style sheet made from the chosen frame, drawn on first need."""
    frame = chosen_frame(channel, look)
    data = load(channel.key, look)
    d = folder(channel.key, look)
    name = data.get("sheet")
    if name and (d / name).exists():
        return d / name
    name = f"sheet_{look['identity']}_{data['chosen'] + 1}.png"
    images.draw(STYLE_SHEET + "\n" + looks.style_text(look), d / name,
                models.image_model(models.BIBLE_IMAGE_MODEL), references=[frame],
                size=(1024, 1024), operation="animation_style_sheet")
    with _lock:
        data = load(channel.key, look)
        old = data.get("sheet")
        if old and old != name:
            (d / old).unlink(missing_ok=True)
        data["sheet"] = name
        _save(channel.key, look, data)
    return d / name


# --- the cast and per-video elements ----------------------------------------

SHEET = {
    "character": ("A character model sheet for an animated series. The character: {name}: "
                  "{description}. Show them full-length three times side by side on a plain, "
                  "softly lit background: front view, three-quarter view, side view. Identical "
                  "design, clothes, colours and proportions in all three; a relaxed neutral pose; "
                  "a clear, readable silhouette."),
    "place": ("An establishing view of a place in an animated series: {name}: {description}. "
              "A clear, wide, uncluttered view with no people in it, showing the layout, the "
              "materials and the light that every later shot of this place must keep."),
    "object": ("A reference drawing of an object in an animated series: {name}: {description}. "
               "The object alone, with no person holding or wearing it, shown whole and "
               "clearly, three-quarter view, centred on a plain background."),
}
SHEET_SIZE = {"character": images.LANDSCAPE, "place": images.PORTRAIT, "object": (1024, 1024)}


def sheet_prompt(kind: str, name: str, description: str, look: dict) -> str:
    kind = kind if kind in SHEET else "character"
    return (SHEET[kind].format(name=name, description=description) +
            "\nDrawn in exactly the art style of the reference sheet: the same medium, line, "
            "texture, palette and light. Take only its style; copy none of its studies.\n"
            f"{looks.style_text(look)}\nNo text, labels, arrows, notes or colour swatches.")


def element_sheet(kind: str, name: str, description: str, look: dict, style_ref: Path,
                  out_path: Path, model=None) -> Path:
    """A reference picture of one character, place or object in the look."""
    if Path(out_path).exists():
        return Path(out_path)
    kind = kind if kind in SHEET else "character"
    return images.draw(sheet_prompt(kind, name, description, look), out_path,
                       model or models.image_model(models.BIBLE_IMAGE_MODEL),
                       references=[style_ref], size=SHEET_SIZE[kind],
                       operation="animation_element")


def cast_sheet(channel, look: dict, member: dict) -> Path:
    """This cast member's model sheet in this look, drawn on first need or
    when their description has changed."""
    name = str(member.get("name") or "").strip()
    description = str(member.get("description") or "").strip() or name
    key = slugify(name, "character")
    basis = hashlib.sha1(f"{name}|{description}|{look['identity']}".encode()).hexdigest()[:10]
    d = folder(channel.key, look)
    entry = load(channel.key, look)["cast"].get(key) or {}
    path = d / "cast" / f"{key}_{basis}.png"
    if entry.get("basis") == basis and path.exists():
        return path
    style_ref = reference(channel, look)
    element_sheet("character", name, description, look, style_ref, path)
    with _lock:
        data = load(channel.key, look)
        old = data["cast"].get(key, {}).get("file")
        if old and old != f"cast/{path.name}":
            (d / old).unlink(missing_ok=True)
        data["cast"][key] = {"file": f"cast/{path.name}", "basis": basis, "name": name}
        _save(channel.key, look, data)
    return path


def cast_members(channel) -> list:
    return [c for c in (channel.animation.cast or []) if str(c.get("name") or "").strip()]
