"""
A preview of exactly the style chosen (decision 053): one real frame of
it, on the channel's own subject, before anything is committed.

- **Composited styles**: one line of narration and the beat that shows
  it, written for this style; the kit it needs drawn (and kept: a real
  video will reuse it); the stage built and a frame filmed by the real
  compositor. `moving` films a few seconds of the same beat, locally, for
  nothing.
- **Generated styles**: the first frame of one shot in the style. `moving`
  animates it with the channel's video model (needs FAL_KEY; a few tens
  of cents).

Previews are cached by what they were made from, so looking at one again
costs nothing. About 5-15 cents for a new composited preview (most of it
the pictures the channel keeps), 2-3 cents for a generated one.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import CACHE_DIR
from pipeline.animation import beats as beat_board, compose, fal, finish, images, kit, models
from pipeline.animation import frame as frames
from pipeline.animation import look as looks
from pipeline.animation import style
from pipeline.animation.compositor import render, script
from pipeline.llm import call_json
from pipeline.plan import WordTiming

log = get_logger(__name__)

PREVIEWS_DIR = CACHE_DIR / "style_previews"
SECONDS_PER_WORD = 0.38

DEMO = """
You are showing someone what their animated channel will look like, in one moment. Write one
line of narration the channel might say about the subject (10 to 16 words, in its voice, a real
insight rather than a greeting), then the single beat that shows that line in this style at its
best: the most characteristic, charming picture the style can make of it. The kit describes each
thing drawn (reuse existing keys where they fit). Word indices count the line's words from 0.
""".strip()

SHOT = """
You are showing someone what their animated channel will look like, in one moment. Write one
line of narration the channel might say about the subject (10 to 16 words, in its voice), then
the first frame of the shot that shows it, as a painter would need it (who and what is where,
pose, setting, light; no style words, no text in the picture), and what then moves in the shot.
""".strip()


def _key(fmt: dict, look: dict, subject: str, hint: str, framed: bool = True) -> str:
    """What a preview was made from. The written moment (the .json) is the
    same in either frame; the pictures (`framed`) are not."""
    basis = [look["identity"], fmt["key"], fmt.get("entrance"), fmt.get("labels"),
             fmt.get("no_labels"), look.get("cadence"), subject, hint]
    if fmt.get("diagrams"):
        basis.append(fmt["diagrams"])
    if framed and fmt.get("frame", "vertical") != "vertical":
        basis.append(fmt["frame"])
    return hashlib.sha1(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()[:14]


def folder_for(channel_key: str) -> Path:
    return PREVIEWS_DIR / channel_key


def cached(channel, settings, subject: str = "", hint: str = "", frame=None) -> dict:
    """What's already been made for this style: {"still", "moving"} paths
    (either may be None)."""
    fmt, look = style.compile(settings, frame)
    base = folder_for(channel.key) / _key(fmt, look, _subject(channel, subject), hint)
    return {"still": base.with_suffix(".jpg") if base.with_suffix(".jpg").exists() else None,
            "moving": base.with_suffix(".mp4") if base.with_suffix(".mp4").exists() else None}


def _demo_path(channel, fmt, look, subject, hint) -> Path:
    return folder_for(channel.key) / (_key(fmt, look, subject, hint, framed=False) + ".json")


def _subject(channel, subject: str) -> str:
    if subject:
        return subject
    try:
        from core import curriculum
        rows = curriculum.load(channel.key)["subtopics"]
        if rows:
            return rows[0]["title"]
    except Exception:  # noqa: BLE001 - any subject will do for a preview
        pass
    return (getattr(channel, "topics", None) or [None])[0] or \
        getattr(channel, "channel_display_name", "") or "an everyday curiosity"


def _channel_voice(channel) -> str:
    prompt = getattr(channel, "style_prompt", "") or ""
    return f"The channel's voice: {prompt[:500]}" if prompt else ""


def still(channel, settings, subject: str = "", hint: str = "", frame=None) -> Path:
    """One frame of this style (see the module docstring), in a vertical
    short's frame or a widescreen one."""
    fmt, look = style.compile(settings, frame)
    subject = _subject(channel, subject)
    base = folder_for(channel.key) / _key(fmt, look, subject, hint)
    out = base.with_suffix(".jpg")
    if out.exists():
        return out
    base.parent.mkdir(parents=True, exist_ok=True)
    if style.composited(fmt):
        stage_data, assets = _composited_stage(channel, fmt, look, subject, hint)
        render.still(stage_data, assets, max(0.1, stage_data["duration"] - 0.3), out)
    else:
        _generated_frame(channel, fmt, look, subject, hint, out)
    return out


def moving(channel, settings, subject: str = "", hint: str = "", frame=None) -> Path:
    """A few seconds of this style moving (see the module docstring)."""
    fmt, look = style.compile(settings, frame)
    subject = _subject(channel, subject)
    base = folder_for(channel.key) / _key(fmt, look, subject, hint)
    out = base.with_suffix(".mp4")
    if out.exists():
        return out
    base.parent.mkdir(parents=True, exist_ok=True)
    if style.composited(fmt):
        stage_data, assets = _composited_stage(channel, fmt, look, subject, hint)
        raw = render.render(stage_data, assets, base.with_suffix(".raw.mp4"))
        finish.grade(raw, out, look)
        raw.unlink(missing_ok=True)
        return out
    if not fal.configured():
        raise PipelineError("no fal key", user_message="Seeing this style move needs FAL_KEY "
                                                       "(see the APIs page).")
    first = still(channel, settings, subject, hint, frame)
    demo = json.loads(_demo_path(channel, fmt, look, subject, hint).read_text(encoding="utf-8"))
    video = models.video_model(settings.video_model)
    quality = settings.quality if settings.quality in video.price else "standard"
    seconds = video.durations[0]
    prompt = f"{demo['motion']} {looks.motion_text(look)}"
    result = fal.run(video.endpoint, video.request(prompt, fal.data_uri(first), seconds, quality,
                                                   aspect_ratio=frames.get(frame).aspect_ratio),
                     what="the preview")
    from core import costs
    costs.record_fal("animation_style_preview", video.key, video.cost(seconds, quality),
                     seconds=seconds)
    raw = fal.download(video.video_url(result), base.with_suffix(".raw.mp4"))
    finish.finish_shot(raw, out, seconds * 0.95, look)
    raw.unlink(missing_ok=True)
    return out


def _composited_stage(channel, fmt, look, subject, hint) -> tuple:
    """(stage, assets) for the preview beat, written once (for either
    frame) and kept."""
    demo_path = _demo_path(channel, fmt, look, subject, hint)
    if demo_path.exists():
        demo = json.loads(demo_path.read_text(encoding="utf-8"))
    else:
        existing = kit.index(channel.key, look, kit.view(fmt))
        schema = beat_board.schema(fmt)
        demo_schema = {"type": "object", "properties": {
            "line": {"type": "string"},
            "kit": schema["properties"]["kit"],
            "beat": schema["properties"]["beats"]["items"]},
            "required": ["line", "kit", "beat"], "additionalProperties": False}
        show = []
        if fmt.get("avatar"):
            show.append("This style's host is its signature: use the presenter layout, with a pose.")
        elif beat_board.diagram_kinds(fmt):
            show.append("This style draws exact diagrams: show the line with the diagram layout "
                        "(a formula, a chart, a number line, a plot or a graph, whichever suits it "
                        "best), with several elements so the diagram is rich.")
        user = "\n\n".join(p for p in [
            f"The subject: {subject}", f"Showing: {hint}" if hint else "", _channel_voice(channel),
            beat_board.brief(fmt, look, existing), " ".join(show)] if p)
        demo = call_json(beat_board.GUIDE.replace("{mean}", "5") + "\n\n" + DEMO, user,
                         demo_schema, operation="animation_style_preview", max_tokens=8000)
        demo_path.write_text(json.dumps(demo, indent=1), encoding="utf-8")
    words_text = demo["line"].split() or ["..."]
    words = [WordTiming(w, round(i * SECONDS_PER_WORD, 3), round(i * SECONDS_PER_WORD + 0.3, 3))
             for i, w in enumerate(words_text)]
    duration = max(4.5, len(words) * SECONDS_PER_WORD + 1.6)
    windows = [{"first": 0, "last": 0, "start": 0.0, "end": duration,
                "words": list(range(len(words)))}]
    beat = dict(demo["beat"], start_word=0)
    if fmt.get("avatar") and beat.get("layout") != "presenter":
        # The host is such a style's signature, and the model doesn't always
        # put them in: the preview's beat is theirs, with its first thing.
        beat.update(layout="presenter", avatar=beat.get("avatar") or "point",
                    items=(beat.get("items") or [])[:1], diagram=None)
    settled, kit_needed, _ = beat_board.settle({"kit": demo["kit"], "beats": [beat]}, windows,
                                               words, fmt)
    pictures = kit.objects(channel, look, fmt, kit_needed)
    for b in settled:
        b["items"] = [it for it in b["items"] if it["key"] in pictures]
        if b.get("backdrop") and b["backdrop"] not in pictures:
            b["backdrop"] = ""
    stage_theme, assets = compose.dress(channel, look, fmt, pictures)
    stage_data = script.build(settled, words, 0.0, duration, kit.aspects(pictures), fmt,
                              stage_theme)
    return stage_data, assets


def _generated_frame(channel, fmt, look, subject, hint, out) -> Path:
    demo_path = _demo_path(channel, fmt, look, subject, hint)
    if demo_path.exists():
        demo = json.loads(demo_path.read_text(encoding="utf-8"))
    else:
        schema = {"type": "object", "properties": {
            "line": {"type": "string"}, "image": {"type": "string"}, "motion": {"type": "string"}},
            "required": ["line", "image", "motion"], "additionalProperties": False}
        user = "\n\n".join(p for p in [
            f"The subject: {subject}", f"Showing: {hint}" if hint else "", _channel_voice(channel),
            f"THE STYLE: {look['description']}", f"HOW TO THINK: {fmt['guide']}"] if p)
        demo = call_json(SHOT, user, schema, operation="animation_style_preview", max_tokens=4000)
        demo_path.write_text(json.dumps(demo, indent=1), encoding="utf-8")
    prompt = f"{demo['image']}\n{looks.style_text(look)}\n{looks.frame_rules(look)}"
    images.draw(prompt, out, models.image_model(channel.animation.image_model),
                size=frames.get(fmt.get("frame")).image, operation="animation_style_preview")
    return out
