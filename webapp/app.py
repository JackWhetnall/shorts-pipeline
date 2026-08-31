"""
Local web GUI for the pipeline: pick a channel, edit its settings, create
a new channel, trigger a video generation with live progress, and browse
finished videos — instead of hand-editing config/channels.py and running
main.py blind. See CLAUDE.md's "Web GUI" section for the overall design
(config storage, non-interactive generation flow, job execution model).

Run with: python webapp/app.py
Then open http://127.0.0.1:5000/
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, request, jsonify, render_template, redirect, url_for, send_from_directory, abort

import config.channels as channels_module
import main as main_module
from quote_source import SOURCES
import webapp.channel_store as channel_store
import webapp.gallery as gallery
import webapp.jobs as jobs
import webapp.voice_lab as voice_lab

OUTPUT_ROOT = (PROJECT_ROOT / "output").resolve()
PACING_INT_FIELDS = {"caption_max_group_size", "segment_count"}
STYLE_TEXT_FIELDS = ("base_color", "highlight_color", "stroke_color",
                      "outro_title_color", "outro_subtext_color")
STYLE_INT_FIELDS = ("font_size", "stroke_width")

app = Flask(__name__)


def _lines(text: str) -> list:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _channel_or_404(key: str) -> dict:
    channels = channel_store.get_channels()
    if key not in channels:
        abort(404)
    return channels[key]


def _parse_channel_form(form, key: str) -> dict:
    """Builds a complete channels.json entry from a submitted settings/
    new-channel form. Always writes the full field set (see
    channel_store.py's docstring on why that's an acceptable trade-off)."""
    content_mode = form.get("content_mode", "topic")
    entry = {
        "content_mode": content_mode,
        "voice": form.get("voice", "").strip(),
        "style_prompt": form.get("style_prompt", "").strip(),
        "channel_display_name": form.get("channel_display_name", "").strip(),
        "outro_subtext": form.get("outro_subtext", "").strip(),
        "output_dir": form.get("output_dir", f"output/{key}").strip(),
        "avoid_imagery": _lines(form.get("avoid_imagery", "")),
        "speed": float(form["speed"]) if form.get("speed") else channels_module.DEFAULT_SPEED,
    }
    if content_mode == "static_corpus":
        entry["source"] = form.get("source", "").strip()
    else:
        entry["topics"] = _lines(form.get("topics", ""))

    pacing = {}
    for field in channels_module.DEFAULT_PACING:
        raw = form.get(f"pacing_{field}")
        if raw is None or raw == "":
            continue
        pacing[field] = int(float(raw)) if field in PACING_INT_FIELDS else float(raw)
    entry["pacing"] = pacing

    style = {}
    for field in STYLE_TEXT_FIELDS:
        raw = form.get(f"style_{field}")
        if raw:
            style[field] = raw.strip()
    for field in STYLE_INT_FIELDS:
        raw = form.get(f"style_{field}")
        if raw not in (None, ""):
            style[field] = int(float(raw))
    bg_raw = form.get("style_outro_bg_color", "")
    if bg_raw.strip():
        style["outro_bg_color"] = [int(x.strip()) for x in bg_raw.split(",") if x.strip()]
    entry["style"] = style

    return entry


@app.route("/")
def index():
    channels = channel_store.get_channels()
    video_counts = {key: gallery.count_videos(ch["output_dir"]) for key, ch in channels.items()}
    return render_template("index.html", channels=channels, video_counts=video_counts)


@app.route("/channels/<key>/settings", methods=["GET", "POST"])
def channel_settings(key):
    channel = _channel_or_404(key)
    if request.method == "POST":
        entry = _parse_channel_form(request.form, key)
        channel_store.save_channel(key, entry)
        return redirect(url_for("channel_settings", key=key))
    channel = dict(channel, key=key)
    return render_template("channel_settings.html", channel=channel, sources=list(SOURCES.keys()))


@app.route("/channels/new", methods=["GET", "POST"])
def new_channel():
    default_channel = {
        "key": "", "content_mode": "topic", "voice": "", "style_prompt": "",
        "channel_display_name": "", "outro_subtext": "Subscribe for more",
        "output_dir": "", "avoid_imagery": [], "topics": [], "source": "",
        "pacing": channels_module.DEFAULT_PACING,
        "style": channels_module.DEFAULT_STYLE,
        "speed": channels_module.DEFAULT_SPEED,
    }
    if request.method == "POST":
        key = request.form.get("key", "").strip()
        error = None
        if not key or not re.match(r"^[a-z0-9_]+$", key):
            error = "Channel key must be lowercase letters, numbers, and underscores only."
        elif key in channel_store.get_raw_entries():
            error = f'Channel "{key}" already exists.'
        if error:
            return render_template("new_channel.html", channel={**default_channel, **request.form, "key": key},
                                    sources=list(SOURCES.keys()), error=error), 400

        entry = _parse_channel_form(request.form, key)
        channel_store.save_channel(key, entry)
        (PROJECT_ROOT / entry["output_dir"]).mkdir(parents=True, exist_ok=True)
        return redirect(url_for("index"))

    return render_template("new_channel.html", channel=default_channel, sources=list(SOURCES.keys()))


@app.route("/channels/<key>/create")
def create_video(key):
    channel = _channel_or_404(key)
    return render_template("create_video.html", key=key, channel=channel)


@app.route("/channels/<key>/gallery")
def channel_gallery(key):
    channel = _channel_or_404(key)
    videos = gallery.list_videos(channel["output_dir"])
    return render_template("gallery.html", key=key, channel=channel, videos=videos)


@app.route("/api/channels/<key>/seed", methods=["POST"])
def api_seed(key):
    channel = _channel_or_404(key)
    try:
        seed = main_module.fetch_candidate_seed(channel)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"seed": seed})


@app.route("/api/channels/<key>/generate", methods=["POST"])
def api_generate(key):
    _channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    seed = data.get("seed")
    if not seed:
        return jsonify({"error": "Missing seed"}), 400
    try:
        job_id = jobs.start_job(key, seed)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify({"job_id": job_id})


@app.route("/api/jobs/<job_id>")
def api_job(job_id):
    job = jobs.get_job(job_id)
    if job is None:
        abort(404)
    result_path_rel = None
    if job["result_path"]:
        result_path_rel = str(Path(job["result_path"]).resolve().relative_to(OUTPUT_ROOT)).replace("\\", "/")
    return jsonify({**job, "result_path_rel": result_path_rel})


@app.route("/videos/<path:relpath>")
def serve_video(relpath):
    target = (OUTPUT_ROOT / relpath).resolve()
    if OUTPUT_ROOT != target and OUTPUT_ROOT not in target.parents:
        abort(403)
    return send_from_directory(OUTPUT_ROOT, relpath)


@app.route("/voice-lab")
def voice_lab_page():
    error = None
    try:
        voices = voice_lab.get_cached_voices()
    except Exception as e:
        voices, error = [], str(e)
    return render_template(
        "voice_lab.html", voices=voices, presets=voice_lab.CADENCE_PRESETS, error=error,
    )


@app.route("/api/voice-lab/refresh-voices", methods=["POST"])
def api_refresh_voices():
    try:
        voices = voice_lab.refresh_voices()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"voices": voices})


@app.route("/api/voice-lab/test", methods=["POST"])
def api_voice_lab_test():
    data = request.get_json(force=True, silent=True) or {}
    voice_id = data.get("voice_id")
    preset = data.get("preset")
    try:
        speed = float(data.get("speed", 1.0))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid speed"}), 400
    if not voice_id or not preset:
        return jsonify({"error": "Missing voice_id or preset"}), 400
    try:
        sample_path = voice_lab.get_or_create_snippet(voice_id, preset, speed)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"sample_url": url_for("serve_voice_lab_sample", filename=sample_path.name)})


@app.route("/voice-lab/samples/<path:filename>")
def serve_voice_lab_sample(filename):
    target = (voice_lab.SAMPLES_DIR / filename).resolve()
    if voice_lab.SAMPLES_DIR.resolve() not in target.parents:
        abort(403)
    return send_from_directory(voice_lab.SAMPLES_DIR, filename)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False, threaded=True)
