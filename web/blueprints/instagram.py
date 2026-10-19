"""
Connecting Instagram, and posting a Short to it now (core.instagram,
decision 116).

Installation-wide, like YouTube's OAuth client: one Meta app and one
token from the Graph API Explorer bring every channel's Instagram
account; each channel then picks its own in Settings.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from core import gallery, instagram
from core.channels import load_channels
from core.errors import PipelineError
from core.logging_setup import get_logger
from web.helpers import all_channels, video_or_404

log = get_logger(__name__)

bp = Blueprint("instagram", __name__)


@bp.route("/instagram/setup", methods=["GET", "POST"])
def setup():
    error = message = None
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "app":
                instagram.save_app(request.form.get("app_id", ""), request.form.get("app_secret", ""))
                message = "App saved."
            elif action == "connect":
                found = instagram.connect(request.form.get("token", ""))
                message = "Connected: " + ", ".join(f"@{a['username']}" if a["username"] else a["page_name"]
                                                    for a in found)
            elif action == "forget":
                instagram.forget()
                return redirect(url_for("instagram.setup"))
        except PipelineError as exc:
            log.warning(f"Instagram setup: {exc}")
            error = exc.user_message
    channels = all_channels()
    rows = []
    for key, account in sorted(instagram.accounts().items(), key=lambda kv: kv[1].get("username", "").lower()):
        users = [(k, c.channel_display_name or k) for k, c in channels.items()
                 if getattr(c.publishing, "instagram_account", "") == key]
        rows.append({"username": account.get("username"), "page": account.get("page_name"), "channels": users})
    return render_template("instagram_setup.html", configured=bool(instagram.app_config()), rows=rows,
                           error=error, message=message, problem=instagram.problem(),
                           permissions=", ".join(instagram.PERMISSIONS),
                           explorer_url=instagram.EXPLORER_URL, apps_url=instagram.APPS_URL)


@bp.route("/api/videos/<path:relpath>/instagram-now", methods=["POST"])
def post_now(relpath):
    """"Post it for me": this Short posted to Instagram now, in the background."""
    target = video_or_404(relpath)
    key = gallery._channel_key_for(target)
    channel = load_channels(validate=False).get(key) if key else None
    if channel is None:
        return jsonify({"error": "Couldn't tell which channel this video belongs to."}), 400
    try:
        instagram.post_now(channel, target)
    except PipelineError as exc:
        return jsonify({"error": exc.user_message}), 400
    return jsonify({"ok": True})
