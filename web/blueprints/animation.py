"""
Animation settings (pipeline.animation, decisions 051 to 053): the style
builder, its previews, style frames and cast sheets, the price of a
video, and trials on the channel's own finished videos.

The style is built from answers to the questions in
pipeline/animation/style/grammar.yaml, asked in order, each offering only
the options that make sense after the answers before it (the browser
evaluates the grammar's conditions itself, from the same data; the
server normalises whatever it's sent, so it never saves a combination
that doesn't fit). A style can also start from one of the starting
points, or from a description in the user's own words.

The form (templates/_animation_settings.html) is part of the channel's
settings form and saved with it (web.forms). The buttons here act on the
values in the form as it stands, saved or not, so a style can be seen
before it's kept: previews and style frames are filed by what they were
made from, so switching back finds them again.
"""

from __future__ import annotations

import copy
import re

from flask import Blueprint, abort, jsonify, request, send_file, url_for

from core import gallery, jobs
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import OUTPUT_DIR, PathTraversalError, relative_to_output, safe_join
from pipeline.animation import bible, fal, frame as frames, models, preview, samples, style
from pipeline.animation.style import describe as describing
from pipeline.animation.style import gallery as style_gallery
from pipeline.animation.style import preview as style_preview
from web.helpers import channel_or_404

log = get_logger(__name__)

bp = Blueprint("animation", __name__)

MAX_CAST = 6
PREVIEW_SECONDS = 50.0
LOOK_KEY_RE = re.compile(r"^[a-z0-9_]{1,60}$")


# --- the form -------------------------------------------------------------------

def starting_points() -> list:
    """The starting points with their example pictures, for the builder."""
    out = []
    for sp in style.starting_points():
        answers, _ = style.normalise(sp["answers"])
        fmt, _ = style.compile(_Settings(answers))
        out.append({"id": sp["id"], "label": sp["label"], "description": sp["description"],
                    "suits": sp.get("suits", ""), "answers": answers,
                    "composited": style.composited(fmt),
                    "example": (url_for("animation.style_example", sid=sp["id"])
                                if style_gallery.path(sp["id"]).exists() else None)})
    return out


def material_examples() -> dict:
    """{material: [{"url", "label"}]}: each material's example pictures."""
    return {m: [{"url": url_for("animation.material_example", material=m, n=n + 1),
                 "label": label}
                for n, label, _ in samples.available(m)]
            for m in samples.materials()}


class _Settings:
    """Just enough of an Animation to compile a style from answers."""

    def __init__(self, answers: dict):
        self.style = answers


def form_context(channel) -> dict:
    """What _animation_settings.html needs."""
    a = channel.animation
    answers, _ = style.normalise(a.style)
    fmt, look = style.compile(a)
    return {
        "anim": a,
        "anim_style": answers,
        "anim_fmt": fmt,
        "anim_look": look,
        "anim_grammar": style.for_browser(),
        "anim_starts": starting_points(),
        "anim_materials": material_examples(),
        "anim_palette": look["palette"],
        "anim_custom_palette": bool(a.palette),
        "anim_qualities": models.QUALITY_LABELS,
        "anim_video_models": models.VIDEO_MODELS,
        "anim_image_models": models.IMAGE_MODELS,
        "anim_cast": list(a.cast or [])[:MAX_CAST] + [{"name": "", "description": ""}],
        "anim_fal_ready": fal.configured(),
        "anim_state": style_state(channel),
        "anim_subject": style_preview._subject(channel, ""),
        "anim_estimate": estimate_text(a.quality, a.video_model, a.image_model, a.pace,
                                       a.budget),
        "anim_videos": _recent_videos(channel),
        "anim_previews": _previews(channel),
    }


def style_state(channel, subject: str = "", frame: str = "vertical") -> dict:
    """What the builder shows beside the questions for the style as it
    stands: its name and sentence, which engine makes it, the palettes it
    suggests, any preview already made (in `frame`), and its style frames."""
    a = channel.animation
    answers, changed = style.normalise(a.style)
    fmt, look = style.compile(a)
    made = style_preview.cached(channel, a, subject, frame=frame)
    return {"style": answers, "changed": changed, "title": look["label"],
            "summary": look["description"], "composited": style.composited(fmt),
            "avatar": fmt["avatar"], "look_key": look["key"], "frame": frames.get(frame).key,
            "palette": look["palette"],
            "suggested_palettes": [p for p in look["suggested_palettes"] if p],
            "preview": {kind: (_style_preview_url(channel.key, path) if path else None)
                        for kind, path in made.items()},
            "bible": bible_state(channel, look)}


def _style_preview_url(key: str, path) -> str:
    return url_for("animation.style_preview_file", key=key, name=path.name)


def estimate_text(quality, video_model, image_model, pace, budget,
                  seconds: float = PREVIEW_SECONDS) -> dict:
    video, image = models.video_model(video_model), models.image_model(image_model)
    quality = quality if quality in video.price else "standard"
    est = models.estimate(seconds, models.mean_shot_seconds(int(pace)), video, image, quality)
    return {"total": est.total, "over": est.total > float(budget) + 1e-6,
            "text": (f"A {seconds:.0f}-second video fully animated: about {est.shots} shots and "
                     f"${est.total:.2f} (video ${est.video_usd:.2f} for {est.generated:.0f}s on "
                     f"{video.label}, pictures ${est.image_usd:.2f}).")}


def bible_state(channel, look: dict) -> dict:
    """The style frames and cast sheets on disk for this style."""
    data = bible.load(channel.key, look)
    current = bible.current(channel.key, look)
    frames = [{"url": _file_url(channel.key, look, p.name), "index": i}
              for i, p in enumerate(bible.frames(channel.key, look))] if current else []
    cast = {}
    for key, entry in data.get("cast", {}).items():
        cast[entry.get("name", key)] = _file_url(channel.key, look, entry["file"])
    return {"frames": frames, "chosen": data.get("chosen", 0), "cast": cast,
            "prompts": data.get("prompts", []) if current else [],
            "stale": bool(data.get("frames")) and not current}


def _file_url(key: str, look: dict, name: str) -> str:
    return url_for("animation.bible_file", key=key, look_key=look["key"], name=name)


def _recent_videos(channel, limit: int = 12) -> list:
    """Finished videos with a script and narration to preview on."""
    out = []
    try:
        paths = sorted(gallery.videos_in(channel.output_path, long=False),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return out
    for path in paths:
        if (path.with_name(f"{path.stem}_meta.txt").exists()
                and path.with_name(f"{path.stem}_audio.mp3").exists()):
            out.append({"rel": relative_to_output(path), "label": path.stem.replace("_", " ")})
        if len(out) >= limit:
            break
    return out


def _previews(channel) -> list:
    folder = preview.preview_dir(channel.key)
    if not folder.is_dir():
        return []
    files = sorted(folder.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": p.name, "url": url_for("animation.preview_file", key=channel.key,
                                            name=p.name)} for p in files[:6]]


def style_from(get) -> dict:
    """A style's answers from form fields (anim_style_<question> and
    anim_style_custom_<question>), through `get(name)`, normalised."""
    given = {q["id"]: get(f"anim_style_{q['id']}") for q in style.questions()
             if get(f"anim_style_{q['id']}")}
    given["custom"] = {q["id"]: " ".join(str(get(f"anim_style_custom_{q['id']}") or "").split())
                       for q in style.questions()}
    answers, _ = style.normalise(given)
    if not answers.get("custom"):
        answers.pop("custom", None)
    return answers


def apply_form(animation, form) -> None:
    """The channel's animation settings from the settings form (fields
    named anim_*). Only called when the form carries them (anim_present)."""
    animation.enabled = bool(form.get("anim_enabled"))
    animation.style = style_from(form.get)
    animation.style_notes = " ".join((form.get("anim_style_notes") or "").split())[:600]
    if form.get("anim_palette_custom"):
        colours = [form.get(f"anim_palette_{i}", "") for i in range(6)]
        animation.palette = [c for c in colours if style.HEX_RE.match(c or "")]
    else:
        animation.palette = []
    for name in ("energy", "pace", "finish"):
        try:
            setattr(animation, name, max(0, min(100, int(form.get(f"anim_{name}")))))
        except (TypeError, ValueError):
            pass
    if form.get("anim_quality") in models.QUALITY_LABELS:
        animation.quality = form.get("anim_quality")
    if form.get("anim_video_model") in models.VIDEO_MODELS:
        animation.video_model = form.get("anim_video_model")
    if form.get("anim_image_model") in models.IMAGE_MODELS:
        animation.image_model = form.get("anim_image_model")
    try:
        animation.budget = round(max(0.0, min(50.0, float(form.get("anim_budget")))), 2)
    except (TypeError, ValueError):
        pass
    cast = []
    for i in range(MAX_CAST + 1):
        name = " ".join((form.get(f"anim_cast_name_{i}") or "").split())[:60]
        description = " ".join((form.get(f"anim_cast_desc_{i}") or "").split())[:500]
        if name:
            cast.append({"name": name, "description": description})
    animation.cast = cast[:MAX_CAST]


def _trying(channel, data: dict):
    """The channel with the style as it stands in the form (unsaved)."""
    trial = copy.deepcopy(channel)
    a = trial.animation
    if isinstance(data.get("style"), dict):
        given = data["style"]
        custom = given.get("custom") if isinstance(given.get("custom"), dict) else {}
        a.style = style_from(lambda name: (
            custom.get(name[len("anim_style_custom_"):])
            if name.startswith("anim_style_custom_") else given.get(name[len("anim_style_"):])))
    if "style_notes" in data:
        a.style_notes = " ".join(str(data.get("style_notes") or "").split())[:600]
    if "palette" in data:
        a.palette = [c for c in data.get("palette") or [] if style.HEX_RE.match(str(c))]
    if "cast" in data:
        a.cast = [{"name": " ".join(str(c.get("name") or "").split())[:60],
                   "description": " ".join(str(c.get("description") or "").split())[:500]}
                  for c in data.get("cast") or [] if str(c.get("name") or "").strip()][:MAX_CAST]
    for name in ("energy", "pace", "finish"):
        if name in data:
            try:
                setattr(a, name, max(0, min(100, int(data[name]))))
            except (TypeError, ValueError):
                pass
    if data.get("video_model") in models.VIDEO_MODELS:
        a.video_model = data["video_model"]
    if data.get("quality") in models.QUALITY_LABELS:
        a.quality = data["quality"]
    return trial


def _subject_in(data: dict) -> str:
    return " ".join(str(data.get("subject") or "").split())[:160]


def _frame_in(data: dict) -> str:
    """The frame a preview is for: a vertical short or widescreen."""
    return data.get("frame") if data.get("frame") in frames.FRAMES else "vertical"


# --- routes: pictures -------------------------------------------------------------

@bp.route("/animation/styles/<sid>.jpg")
def style_example(sid):
    """A starting point's example (pipeline.animation.style.gallery)."""
    if not style.starting_point(sid):
        abort(404)
    path = style_gallery.path(sid)
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype="image/jpeg", max_age=86400)


@bp.route("/animation/materials/<material>/<int:n>.jpg")
def material_example(material, n):
    """One of a material's example pictures (pipeline.animation.samples)."""
    if material not in samples.materials() or not 1 <= n <= len(samples.SUBJECTS):
        abort(404)
    path = samples.path(material, n - 1)
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype="image/jpeg", max_age=86400)


@bp.route("/channels/<key>/animation/style-preview/<name>")
def style_preview_file(key, name):
    channel_or_404(key)
    try:
        path = safe_join(style_preview.folder_for(key), name)
    except PathTraversalError:
        abort(400)
    if not path.is_file() or path.suffix not in (".jpg", ".mp4"):
        abort(404)
    return send_file(path, conditional=True, max_age=3600)


@bp.route("/channels/<key>/animation/file/<look_key>/<path:name>")
def bible_file(key, look_key, name):
    channel_or_404(key)
    if not LOOK_KEY_RE.match(look_key):
        abort(404)
    try:
        path = safe_join(bible.folder(key, {"key": look_key}), name)
    except PathTraversalError:
        abort(400)
    if not path.is_file():
        abort(404)
    return send_file(path, max_age=3600)


@bp.route("/channels/<key>/animation/preview/<name>")
def preview_file(key, name):
    channel_or_404(key)
    try:
        path = safe_join(preview.preview_dir(key), name)
    except PathTraversalError:
        abort(400)
    if not path.is_file() or path.suffix != ".mp4":
        abort(404)
    return send_file(path, mimetype="video/mp4", conditional=True)


# --- routes: the builder ----------------------------------------------------------

@bp.route("/api/channels/<key>/animation/style", methods=["POST"])
def style_for(key):
    """The style in the form: its sentence, previews and style frames, and
    which answers (if any) had to change to fit."""
    data = request.get_json(force=True, silent=True) or {}
    state = style_state(_trying(channel_or_404(key), data), _subject_in(data), _frame_in(data))
    if isinstance(data.get("style"), dict):
        state["changed"] = style.normalise(data["style"])[1]
    return jsonify(state)


@bp.route("/api/channels/<key>/animation/describe", methods=["POST"])
def describe_style(key):
    """A style from a description in the user's own words. One model call,
    under a cent."""
    channel = channel_or_404(key)
    text = " ".join(str((request.get_json(force=True, silent=True) or {}).get("text")
                        or "").split())
    if len(text) < 8:
        raise PipelineError("no description",
                            user_message="Say in a sentence or two what you picture.")
    return jsonify(describing.describe(text, channel))


@bp.route("/api/channels/<key>/animation/style-preview", methods=["POST"])
def make_style_preview(key):
    """One frame of the style in the form on the channel's subject (or,
    with `moving`, a few seconds of it), in a vertical short's frame or a
    widescreen one. A new composited frame costs 5-15 cents, mostly
    pictures the channel keeps; moving it, or the other frame, costs
    nothing more. A generated style's frame is 2-3 cents; moving it needs
    FAL_KEY."""
    data = request.get_json(force=True, silent=True) or {}
    trial = _trying(channel_or_404(key), data)
    subject, frame = _subject_in(data), _frame_in(data)
    make = style_preview.moving if data.get("moving") else style_preview.still
    make(trial, trial.animation, subject=subject, frame=frame)
    return jsonify(style_state(trial, subject, frame))


@bp.route("/api/channels/<key>/animation/bible", methods=["POST"])
def bible_for(key):
    """The style frames and cast sheets for the style in the form."""
    trial = _trying(channel_or_404(key), request.get_json(force=True, silent=True) or {})
    return jsonify(bible_state(trial, style.compile(trial.animation)[1]))


@bp.route("/api/channels/<key>/animation/frames", methods=["POST"])
def draw_frames(key):
    """Three new style frames in the style in the form. About 5 cents."""
    trial = _trying(channel_or_404(key), request.get_json(force=True, silent=True) or {})
    look = style.compile(trial.animation)[1]
    bible.draw_style_frames(trial, look)
    return jsonify(bible_state(trial, look))


@bp.route("/api/channels/<key>/animation/choose", methods=["POST"])
def choose_frame(key):
    data = request.get_json(force=True, silent=True) or {}
    trial = _trying(channel_or_404(key), data)
    look = style.compile(trial.animation)[1]
    try:
        index = int(data.get("index"))
    except (TypeError, ValueError):
        raise PipelineError("bad index", user_message="Pick one of the style frames.")
    bible.choose(key, look, index)
    return jsonify(bible_state(trial, look))


@bp.route("/api/channels/<key>/animation/cast", methods=["POST"])
def draw_cast(key):
    """Model sheets for the cast in the form, in its style. Drawn only for
    anyone new or changed; a couple of cents each."""
    trial = _trying(channel_or_404(key), request.get_json(force=True, silent=True) or {})
    look = style.compile(trial.animation)[1]
    members = bible.cast_members(trial)
    if not members:
        raise PipelineError("no cast", user_message="Name a character first.")
    for member in members:
        bible.cast_sheet(trial, look, member)
    return jsonify(bible_state(trial, look))


@bp.route("/api/animation/estimate")
def estimate():
    args = request.args
    try:
        pace, budget = int(args.get("pace", 50)), float(args.get("budget", 5))
    except ValueError:
        pace, budget = 50, 5.0
    return jsonify(estimate_text(args.get("quality", "standard"), args.get("video_model", ""),
                                 args.get("image_model", ""), pace, budget))


@bp.route("/api/channels/<key>/animation/preview", methods=["POST"])
def start_preview(key):
    """An animatic (or, with `animate`, an animated film) of one of the
    channel's finished videos, as a background job. Uses the saved
    settings: save first."""
    channel = channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    try:
        video = safe_join(OUTPUT_DIR, data.get("video") or "")
    except PathTraversalError:
        abort(400)
    if not video.is_file():
        raise PipelineError("no such video", user_message="Pick one of the channel's videos.")
    animate = bool(data.get("animate"))
    if animate and not fal.configured() and \
            not style.composited(style.compile(channel.animation)[0]):
        raise PipelineError("no fal key", user_message="Animating needs FAL_KEY. See the APIs "
                                                       "page; an animatic doesn't.")
    job_id = jobs.start_job(channel.key, {"type": "animation_preview",
                                          "video": relative_to_output(video),
                                          "animate": animate})
    return jsonify({"job_id": job_id})
