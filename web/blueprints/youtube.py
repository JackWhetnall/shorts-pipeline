"""
Connecting a channel to YouTube, and uploading to it.

The OAuth redirect URI has to be registered with Google character for
character, port included, so every page that mentions it derives it from
the request rather than hardcoding a guess — run the app on a different
port and the setup page tells you the URI you now need to register.
"""

from __future__ import annotations

import secrets

from flask import (
    Blueprint, abort, jsonify, redirect, render_template, request, session,
    url_for,
)

from core import gallery, youtube
from core.errors import PipelineError
from core.logging_setup import get_logger
from web.helpers import channel_or_404, video_or_404

log = get_logger(__name__)

bp = Blueprint("youtube", __name__)

OAUTH_STATE_KEY = "_youtube_oauth"


def redirect_uri() -> str:
    """The callback URL as this server is actually reachable.

    `_external` with the request's own host means a run on :5055 registers
    :5055, rather than silently sending Google a URI that will not match.
    """
    return url_for("youtube.callback", _external=True)


@bp.route("/youtube/setup", methods=["GET", "POST"])
def setup():
    """Where the Google Cloud OAuth client is entered.

    Installation-wide, not per channel: one Cloud project holds the client
    for every channel, and making someone repeat it per channel would be
    six identical forms and six chances to paste the wrong secret.
    """
    error = saved = None
    if request.method == "POST":
        if request.form.get("action") == "forget":
            youtube.forget_client_config()
            return redirect(url_for("youtube.setup"))
        client_id = request.form.get("client_id", "").strip()
        client_secret = request.form.get("client_secret", "").strip()
        if not client_id or not client_secret:
            error = "Both the client ID and the client secret are needed."
        else:
            youtube.save_client_config(client_id, client_secret)
            saved = True

    return render_template(
        "youtube_setup.html",
        configured=youtube.is_configured(),
        redirect_uri=redirect_uri(),
        error=error, saved=saved,
        channels=_connection_rows(),
    )


def _connection_rows() -> list:
    from web.helpers import all_channels

    rows = []
    for key, channel in all_channels().items():
        info = youtube.connection(key)
        info.update({"key": key, "name": channel.channel_display_name or key})
        rows.append(info)
    return rows


@bp.route("/channels/<key>/youtube/connect")
def connect(key):
    """Send the browser to Google's consent screen.

    The state parameter is a random token kept in the session, not the
    channel key: an attacker who could guess the state could otherwise
    finish an authorization against a channel of their choosing.
    """
    channel_or_404(key)
    try:
        state = secrets.token_urlsafe(24)
        session[OAUTH_STATE_KEY] = {"state": state, "channel": key}
        return redirect(youtube.authorize_url(redirect_uri(), state))
    except PipelineError as exc:
        log.warning(f"Cannot start YouTube authorization: {exc}")
        return redirect(url_for("youtube.setup"))


@bp.route("/youtube/callback")
def callback():
    """Where Google sends the browser back.

    Everything in the query string arrives from outside, so nothing is
    trusted: the state has to match what this session stored, and the
    channel comes from the session rather than the URL.
    """
    pending = session.pop(OAUTH_STATE_KEY, None)
    if not pending or request.args.get("state") != pending.get("state"):
        abort(400, description="That sign-in didn't match the one this browser "
                               "started. Try connecting again.")

    key = pending["channel"]
    channel_or_404(key)

    if request.args.get("error"):
        # The user pressed Cancel, or Google refused. Not an error page —
        # they know what they did; put them back where they were.
        log.info(f"{key}: YouTube authorization declined ({request.args.get('error')})")
        return redirect(url_for("channels.settings", key=key))

    code = request.args.get("code", "")
    if not code:
        abort(400, description="Google didn't send back a sign-in code.")

    tokens = youtube.exchange_code(code, redirect_uri())
    youtube.save_tokens(key, tokens)
    log.info(f"{key}: connected to YouTube as {tokens.get('account') or 'unknown account'}")
    return redirect(url_for("channels.settings", key=key, connected=1))


@bp.route("/channels/<key>/youtube/disconnect", methods=["POST"])
def disconnect(key):
    channel_or_404(key)
    youtube.disconnect(key)
    return redirect(url_for("channels.settings", key=key))


@bp.route("/api/videos/<path:relpath>/upload-youtube", methods=["POST"])
def upload(relpath):
    """Upload one finished video, and record the link it came back with.

    Synchronous. An upload is a 20-40 MB PUT that finishes in seconds on
    any usable connection, and routing it through the job queue — which
    exists to serialise expensive generation against rate-limited APIs —
    would mean an upload waiting behind a render.
    """
    target = video_or_404(relpath)
    data = request.get_json(force=True, silent=True) or {}
    key = data.get("channel_key", "")
    if not key:
        return jsonify({"error": "Which channel this video belongs to wasn't sent."}), 400
    channel_or_404(key)

    info = gallery.load_publish_info(target)
    if info["youtube_url"]:
        return jsonify({"error": "This video already has a YouTube link. "
                                 "Clear it first if you meant to upload again."}), 400

    privacy = data.get("privacy", "public")
    title = (data.get("title") or info.get("title") or "").strip()
    description = data.get("description") or info.get("description") or ""

    try:
        result = youtube.upload(key, target, title, description,
                                tags=data.get("tags", ()), privacy=privacy)
    except PipelineError as exc:
        log.warning(f"{key}: YouTube upload failed: {exc}")
        return jsonify({"error": exc.user_message}), 502

    # Recording the link is what marks it published, so this is the same
    # state transition the manual flow produces — the review queue, the
    # gallery and /insights all see an ordinary published video.
    published = gallery.save_publish_info(target, {"youtube_url": result["url"]})
    return jsonify({
        "ok": True,
        "url": result["url"],
        "published_at": published["published_at"],
        "privacy": result["privacy_granted"],
        "locked_private": result["locked_private"],
    })
