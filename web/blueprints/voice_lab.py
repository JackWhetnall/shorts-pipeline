"""
Voice Lab: audition voices, cadence presets and speed.
"""

from __future__ import annotations

from flask import (
    Blueprint, abort, jsonify, render_template, request, send_from_directory, url_for,
)

from core import voice_lab as lab
from core.errors import friendly_message
from core.paths import PathTraversalError, safe_join

bp = Blueprint("voice_lab", __name__)


@bp.route("/voice-lab")
def page():
    from web.helpers import all_channels

    error = None
    try:
        voices = lab.get_cached_voices()
    except Exception as exc:  # noqa: BLE001 - the page is still useful without the list
        voices, error = [], friendly_message(exc)
    from core import gallery

    channels = all_channels()
    targets = []
    for key, channel in channels.items():
        state = gallery.video_state_counts(channel.output_dir)
        targets.append({
            "key": key,
            "name": channel.channel_display_name or key,
            "published": state["published"],
            "voice": channel.voice,
        })
    return render_template("voice_lab.html", voices=voices,
                           presets=lab.CADENCE_PRESETS, error=error,
                           channels=channels, targets=targets)


@bp.route("/api/voice-lab/refresh-voices", methods=["POST"])
def refresh():
    return jsonify({"voices": lab.refresh_voices()})


@bp.route("/api/voice-lab/test", methods=["POST"])
def test_combo():
    data = request.get_json(force=True, silent=True) or {}
    voice_id, preset = data.get("voice_id"), data.get("preset")
    if not voice_id or not preset:
        return jsonify({"error": "Pick a voice and a cadence first."}), 400
    try:
        speed = float(data.get("speed", 1.0))
    except (TypeError, ValueError):
        return jsonify({"error": "That speed isn't a number."}), 400

    sample = lab.get_or_create_snippet(voice_id, preset, speed)
    return jsonify({"sample_url": url_for("voice_lab.serve_sample", filename=sample.name)})


@bp.route("/voice-lab/samples/<path:filename>")
def serve_sample(filename):
    try:
        safe_join(lab.SAMPLES_DIR, filename)
    except PathTraversalError:
        abort(403, description="That sample isn't available.")
    return send_from_directory(lab.SAMPLES_DIR, filename)
