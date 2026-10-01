"""
The channel profile page: the descriptions to paste into YouTube, TikTok
and Instagram, and the YouTube banner (core.channel_profile, core.banner;
decision 058).
"""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, render_template, request, send_file, url_for

from core import banner, channel_profile
from core.errors import PipelineError
from core.logging_setup import get_logger
from web.helpers import channel_or_404

log = get_logger(__name__)

bp = Blueprint("profile", __name__)


def _state(channel) -> dict:
    words = channel_profile.load(channel.key)
    return {"words": words, "links": channel_profile.links(channel),
            "about": channel_profile.about_with_links(channel, words) if words else "",
            "bio_link": channel_profile.bio_link(channel)}


@bp.route("/channels/<key>/profile")
def page(key):
    channel = channel_or_404(key)
    return render_template(
        "profile.html", key=key, channel=channel, **_state(channel),
        limits={"about": channel_profile.YOUTUBE_ABOUT_MAX, "tiktok": channel_profile.TIKTOK_BIO_MAX,
                "instagram": channel_profile.INSTAGRAM_BIO_MAX, "tagline": channel_profile.TAGLINE_MAX},
        variants=[(v, banner.LABELS[v], banner.path_for(key, v).exists()) for v in banner.VARIANTS],
        banner_size=banner.SIZE, banner_safe=(banner.SAFE_W, banner.SAFE_H),
        has_logo=(banner.channel_logo_dir(key) / "logo.png").exists())


@bp.route("/api/channels/<key>/profile/generate", methods=["POST"])
def generate(key):
    """Write the descriptions (about a cent). The banner is drawn at the
    same time, with the new tagline, so there's something to look at."""
    channel = channel_or_404(key)
    try:
        words = channel_profile.generate(channel)
        banner.make(channel, words["tagline"])
    except PipelineError as exc:
        return jsonify({"error": exc.user_message}), 400
    return jsonify({"ok": True, **_state(channel)})


@bp.route("/api/channels/<key>/profile/save", methods=["POST"])
def save(key):
    """Keep the owner's edits to the words. A changed tagline redraws the banner."""
    channel = channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    fields = {k: data[k] for k in ("tagline", "about", "tiktok_bio", "instagram_bio") if k in data}
    if "keywords" in data:
        fields["keywords"] = [w for w in str(data["keywords"]).replace("\n", ",").split(",") if w.strip()]
    before = channel_profile.load(key)
    words = channel_profile.update(key, fields)
    if "tagline" in fields and words.get("tagline") != before.get("tagline"):
        banner.make(channel, words["tagline"])
    return jsonify({"ok": True, **_state(channel)})


@bp.route("/api/channels/<key>/profile/banner", methods=["POST"])
def make_banner(key):
    """Draw the banner again (after a new logo, say)."""
    channel = channel_or_404(key)
    banner.make(channel, channel_profile.load(key).get("tagline", ""))
    return jsonify({"ok": True})


@bp.route("/channels/<key>/profile/banner/<variant>.png")
def banner_image(key, variant):
    channel_or_404(key)
    path = banner.path_for(key, variant) if variant in banner.VARIANTS else None
    if path is None or not path.exists():
        abort(404, description="That banner hasn't been made yet.")
    if request.args.get("download"):
        return send_file(path, as_attachment=True, download_name=f"{key}_youtube_banner_{variant}.png")
    return send_file(path, max_age=0)
