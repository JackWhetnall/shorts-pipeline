"""
Logo generation and the assets it produces.
"""

from __future__ import annotations

from flask import (
    Blueprint, abort, jsonify, render_template, request, send_from_directory, url_for,
)

from core import assets, logos as logos_core
from core.paths import PathTraversalError, channel_logo_dir, safe_join
from web.helpers import channel_or_404

bp = Blueprint("logos", __name__)


@bp.route("/channels/<key>/logo")
def logo_page(key):
    channel = channel_or_404(key)
    return render_template(
        "logo_gen.html", key=key, channel=channel,
        has_logo=assets.has_logo(key),
        has_merch_variants=logos_core.has_merch_variants(key),
        candidates=[p.name for p in assets.list_candidates(key)],
        variant_styles=logos_core.VARIANT_STYLES,
        candidate_count=logos_core.CANDIDATE_COUNT,
        logo_brief=_suggested_brief(channel),
    )


def _suggested_brief(channel) -> str:
    """A starting point for the logo brief.

    It used to be the first 60 characters of the style prompt, which are
    instructions to a script writer — the box came pre-filled with "You
    are writing a short..." under a label asking what the channel is
    about. Two different things.

    The topic plan's subject IS a one-sentence description of the channel,
    written for exactly this purpose, so it goes first. Failing that the
    display name, which at least names the subject. Failing that, nothing
    — an empty box is better than a wrong one.
    """
    from core import curriculum

    try:
        subject = curriculum.progress(channel.key).get("subject", "")
    except Exception:  # noqa: BLE001 - a suggestion is never worth an error
        subject = ""
    return subject or channel.channel_display_name or ""


@bp.route("/api/channels/<key>/logo/generate", methods=["POST"])
def generate(key):
    channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    fragment = (data.get("fragment") or "").strip()
    if not fragment:
        return jsonify({"error": "Describe what the channel is about first."}), 400

    paths = logos_core.generate_candidates(key, fragment)
    return jsonify({"candidates": [
        {"filename": p.name,
         "url": url_for("logos.serve_asset", key=key, filename=f"candidates/{p.name}")}
        for p in paths
    ]})


@bp.route("/api/channels/<key>/logo/select", methods=["POST"])
def select(key):
    channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    filename = data.get("filename")
    if not filename:
        return jsonify({"error": "No logo was chosen."}), 400
    try:
        candidate = safe_join(assets.candidates_dir(key), filename)
    except PathTraversalError:
        abort(400, description="That isn't a valid candidate.")
    if not candidate.exists():
        return jsonify({"error": "That candidate no longer exists."}), 400

    logos_core.select_logo(key, candidate)
    return jsonify({"ok": True, "redirect": url_for("logos.logo_page", key=key)})


@bp.route("/api/channels/<key>/logo/variants/generate", methods=["POST"])
def generate_variants(key):
    channel_or_404(key)
    variants = logos_core.generate_merch_variants(key)
    labels = {s["key"]: s["label"] for s in logos_core.VARIANT_STYLES}
    labels["monochrome"] = "Monochrome (single-colour print)"
    return jsonify({"variants": [
        {"key": vkey, "label": labels.get(vkey, vkey),
         "url": url_for("logos.serve_asset", key=key, filename=path.name)}
        for vkey, path in variants.items()
    ]})


@bp.route("/channels/<key>/logo-assets/<path:filename>")
def serve_asset(key, filename):
    directory = channel_logo_dir(key)
    try:
        target = safe_join(directory, filename)
    except PathTraversalError:
        abort(403, description="That file isn't available.")
    if not target.exists():
        abort(404, description="That image doesn't exist.")
    return send_from_directory(directory, filename)
