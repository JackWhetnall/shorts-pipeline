"""
Generated animation's settings (pipeline.animation, decision 051): the
look, its style frames and cast sheets, the price of a video, and
previews on the channel's own finished videos.

The form (templates/_animation_settings.html) is part of the channel's
settings form and saved with it (web.forms). The buttons here act on the
values in the form as it stands, saved or not, so a look can be tried
before it's kept: style frames are filed by what they were drawn from
(`look.identity`), so switching back finds them again.
"""

from __future__ import annotations

import copy

from flask import Blueprint, abort, jsonify, request, send_file, url_for

from core import gallery, jobs
from core.channels import ANIMATION_CADENCES
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import OUTPUT_DIR, PathTraversalError, relative_to_output, safe_join
from pipeline.animation import bible, fal, look as looks, models, preview, samples
from web.helpers import channel_or_404

log = get_logger(__name__)

bp = Blueprint("animation", __name__)

MAX_CAST = 6
PREVIEW_SECONDS = 50.0


# --- the form -------------------------------------------------------------------

def look_examples() -> dict:
    """{look key: [{"url", "label"}]}: each look's example pictures."""
    return {key: [{"url": url_for("animation.look_sample", look_key=key, n=n + 1),
                   "label": label}
                  for n, label, _ in samples.available(key)]
            for key in looks.presets()}


def form_context(channel) -> dict:
    """What _animation_settings.html needs."""
    a = channel.animation
    look = looks.resolve(a)
    presets = looks.presets()
    return {
        "anim": a,
        "anim_look": look,
        "anim_presets": presets,
        "anim_examples": look_examples(),
        "anim_palette": look["palette"],
        "anim_custom_palette": bool(a.palette),
        "anim_cadences": {"": f"The look's own", "ones": "Smooth (every frame)",
                          "twos": "On twos (hand-drawn)", "threes": "On threes (stop-motion)"},
        "anim_cadence_default": {k: p["cadence"] for k, p in presets.items()},
        "anim_qualities": models.QUALITY_LABELS,
        "anim_video_models": models.VIDEO_MODELS,
        "anim_image_models": models.IMAGE_MODELS,
        "anim_cast": list(a.cast or [])[:MAX_CAST] + [{"name": "", "description": ""}],
        "anim_fal_ready": fal.configured(),
        "anim_bible": bible_state(channel, look),
        "anim_estimate": estimate_text(a.quality, a.video_model, a.image_model, a.pace,
                                       a.budget),
        "anim_videos": _recent_videos(channel),
        "anim_previews": _previews(channel),
    }


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
    """The style frames and cast sheets on disk for this look."""
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


def apply_form(animation, form) -> None:
    """The channel's animation settings from the settings form (fields
    named anim_*). Only called when the form carries them (anim_present)."""
    animation.enabled = bool(form.get("anim_enabled"))
    if form.get("anim_look") in looks.presets():
        animation.look = form.get("anim_look")
    animation.style_notes = " ".join((form.get("anim_style_notes") or "").split())[:600]
    if form.get("anim_palette_custom"):
        colours = [form.get(f"anim_palette_{i}", "") for i in range(6)]
        animation.palette = [c for c in colours if looks.HEX_RE.match(c or "")]
    else:
        animation.palette = []
    for name in ("energy", "pace", "finish"):
        try:
            setattr(animation, name, max(0, min(100, int(form.get(f"anim_{name}")))))
        except (TypeError, ValueError):
            pass
    if form.get("anim_cadence", "") in ANIMATION_CADENCES:
        animation.cadence = form.get("anim_cadence", "")
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
    """The channel with the look as it stands in the form (unsaved)."""
    trial = copy.deepcopy(channel)
    a = trial.animation
    if data.get("look") in looks.presets():
        a.look = data["look"]
    if "style_notes" in data:
        a.style_notes = " ".join(str(data.get("style_notes") or "").split())[:600]
    if "palette" in data:
        a.palette = [c for c in data.get("palette") or [] if looks.HEX_RE.match(str(c))]
    if "cast" in data:
        a.cast = [{"name": " ".join(str(c.get("name") or "").split())[:60],
                   "description": " ".join(str(c.get("description") or "").split())[:500]}
                  for c in data.get("cast") or [] if str(c.get("name") or "").strip()][:MAX_CAST]
    return trial


# --- routes ---------------------------------------------------------------------

@bp.route("/animation/looks/<look_key>/<int:n>.jpg")
def look_sample(look_key, n):
    """One of a look's example pictures (pipeline.animation.samples)."""
    if look_key not in looks.presets() or not 1 <= n <= len(samples.SUBJECTS):
        abort(404)
    path = samples.path(look_key, n - 1)
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype="image/jpeg", max_age=86400)


@bp.route("/channels/<key>/animation/file/<look_key>/<path:name>")
def bible_file(key, look_key, name):
    channel_or_404(key)
    if look_key not in looks.presets():
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


@bp.route("/api/channels/<key>/animation/bible", methods=["POST"])
def bible_for(key):
    """The style frames and cast sheets for the look in the form."""
    trial = _trying(channel_or_404(key), request.get_json(force=True, silent=True) or {})
    return jsonify(bible_state(trial, looks.resolve(trial.animation)))


@bp.route("/api/channels/<key>/animation/frames", methods=["POST"])
def draw_frames(key):
    """Three new style frames in the look in the form. About 5 cents."""
    trial = _trying(channel_or_404(key), request.get_json(force=True, silent=True) or {})
    look = looks.resolve(trial.animation)
    bible.draw_style_frames(trial, look)
    return jsonify(bible_state(trial, look))


@bp.route("/api/channels/<key>/animation/choose", methods=["POST"])
def choose_frame(key):
    data = request.get_json(force=True, silent=True) or {}
    trial = _trying(channel_or_404(key), data)
    look = looks.resolve(trial.animation)
    try:
        index = int(data.get("index"))
    except (TypeError, ValueError):
        raise PipelineError("bad index", user_message="Pick one of the style frames.")
    bible.choose(key, look, index)
    return jsonify(bible_state(trial, look))


@bp.route("/api/channels/<key>/animation/cast", methods=["POST"])
def draw_cast(key):
    """Model sheets for the cast in the form, in its look. Drawn only for
    anyone new or changed; a couple of cents each."""
    trial = _trying(channel_or_404(key), request.get_json(force=True, silent=True) or {})
    look = looks.resolve(trial.animation)
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
    if animate and not fal.configured():
        raise PipelineError("no fal key", user_message="Animating needs FAL_KEY. See the APIs "
                                                       "page; an animatic doesn't.")
    job_id = jobs.start_job(channel.key, {"type": "animation_preview",
                                          "video": relative_to_output(video),
                                          "animate": animate})
    return jsonify({"job_id": job_id})
