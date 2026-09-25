"""
A channel's music: playable suggestions to choose between, its current
tracks, adding and removing. core.music_library does the work; see
decision 039.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, send_file

from core import drafts, music_library
from core.channels import save_channel
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import safe_join
from web.helpers import channel_or_404

log = get_logger(__name__)

bp = Blueprint("music", __name__)


def _suggestions(channel_key: str, description: str, moods: list):
    try:
        return music_library.suggest(channel_key, description, moods)
    except PipelineError as exc:
        return {"error": exc.user_message}


@bp.route("/channels/<key>/music/suggest")
def suggest(key):
    channel = channel_or_404(key)
    found = _suggestions(key, music_library.describe(channel), channel.sound.music_moods)
    if "error" in found:
        return jsonify(found), 502
    if found["moods"] and found["moods"] != channel.sound.music_moods:
        channel.sound.music_moods = found["moods"]          # worked out once, then reused
        save_channel(channel)
    return jsonify(found)


@bp.route("/channels/drafts/<draft_id>/music/suggest")
def suggest_for_draft(draft_id):
    record = drafts.load(draft_id)
    if record is None:
        return jsonify({"error": "That draft no longer exists."}), 404
    body = record["channel"]
    description = f"{body['name_options'][0]}. {body.get('summary', '')} {body.get('style_prompt', '')[:500]}"
    found = _suggestions("", description, body.get("music_moods") or [])
    return (jsonify(found), 502) if "error" in found else jsonify(found)


@bp.route("/channels/<key>/music")
def listing(key):
    channel_or_404(key)
    return jsonify({"tracks": music_library.tracks(key)})


@bp.route("/channels/<key>/music/add", methods=["POST"])
def add(key):
    channel_or_404(key)
    track_id = (request.get_json(silent=True) or {}).get("id", "")
    try:
        music_library.add(key, music_library.candidate(track_id))
    except PipelineError as exc:
        return jsonify({"error": exc.user_message}), 400
    return jsonify({"tracks": music_library.tracks(key)})


@bp.route("/channels/<key>/music/remove", methods=["POST"])
def remove(key):
    channel_or_404(key)
    filename = (request.get_json(silent=True) or {}).get("file", "")
    try:
        music_library.remove(key, filename)
    except (PipelineError, ValueError) as exc:
        return jsonify({"error": getattr(exc, "user_message", "Couldn't remove that.")}), 400
    return jsonify({"tracks": music_library.tracks(key)})


@bp.route("/channels/<key>/music/file/<path:name>")
def play(key, name):
    channel_or_404(key)
    return send_file(safe_join(music_library.music_dir(key), name))
