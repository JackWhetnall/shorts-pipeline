"""
Choosing and editing a channel's background picture.

Searching is free and returns preview URLs the browser loads directly —
nothing is downloaded until a picture is chosen, so browsing costs
nothing but the search call.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, send_file

from core import backgrounds
from core.errors import PipelineError, friendly_message
from core.logging_setup import get_logger
from web.helpers import as_int, channel_or_404

log = get_logger(__name__)

bp = Blueprint("backgrounds", __name__)


@bp.route("/api/channels/<key>/background/search", methods=["POST"])
def search(key):
    channel = channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        # The channel's own subject is a better default than nothing, and
        # it is what someone would have typed anyway.
        query = channel.channel_display_name or "abstract texture"

    if not backgrounds.any_key_configured():
        return jsonify({"error": "Set PEXELS_API_KEY or PIXABAY_API_KEY to search "
                                 "for pictures."}), 400

    results = backgrounds.search(query)
    if not results:
        return jsonify({"error": f'Nothing found for "{query}". Try different '
                                 f"words."}), 404
    return jsonify({"results": results, "query": query})


@bp.route("/api/channels/<key>/background/choose", methods=["POST"])
def choose(key):
    channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    try:
        info = backgrounds.choose(
            key,
            url=(data.get("url") or "").strip(),
            source=(data.get("source") or "").strip(),
            credit=(data.get("credit") or "").strip(),
            link=(data.get("link") or "").strip(),
            blur=as_int(data.get("blur"), 0, 0, backgrounds.MAX_BLUR),
            dim=as_int(data.get("dim"), 0, 0, backgrounds.MAX_DIM),
        )
    except PipelineError as exc:
        return jsonify({"error": exc.user_message}), 502
    return jsonify({"ok": True, "info": info})


@bp.route("/api/channels/<key>/background/edit", methods=["POST"])
def edit(key):
    """Re-derive the picture from the original with new blur and dim."""
    channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    try:
        info = backgrounds.apply_edits(
            key,
            blur=as_int(data.get("blur"), 0, 0, backgrounds.MAX_BLUR),
            dim=as_int(data.get("dim"), 0, 0, backgrounds.MAX_DIM),
        )
    except PipelineError as exc:
        return jsonify({"error": exc.user_message}), 400
    except Exception as exc:  # noqa: BLE001 - an unreadable original
        log.exception("Could not re-edit the background")
        return jsonify({"error": friendly_message(exc)}), 500
    return jsonify({"ok": True, "info": info})


@bp.route("/api/channels/<key>/background/clear", methods=["POST"])
def clear(key):
    channel_or_404(key)
    backgrounds.clear(key)
    return jsonify({"ok": True})


@bp.route("/channels/<key>/background.jpg")
def serve(key):
    """The edited picture, for the settings page to show.

    `max-age=0` because the file is rewritten in place every time a slider
    moves, and a cached copy would make the edits look broken.
    """
    channel_or_404(key)
    target = backgrounds.path(key)
    if not target.exists():
        return jsonify({"error": "No background."}), 404
    response = send_file(target, mimetype="image/jpeg")
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response
