"""
The web app: an application factory, blueprints, and cross-cutting
concerns in one place.

What changed from the single 890-line module this replaces:

  - **Routes are grouped by concern.** Channels, logos, the setup wizard,
    the gallery, jobs, and the voice lab were all in one file.

  - **CSRF protection.** There was none, on any POST — including channel
    deletion, which permanently removes an output tree. "It only listens
    on localhost" is not a defence: any page open in the same browser can
    POST to 127.0.0.1. Every form now carries a token and every unsafe
    method is checked.

  - **One error handler.** Routes used to `return jsonify({"error":
    str(e)}), 500`, piping raw exception text — absolute filesystem paths
    included — into the browser. Now every error goes through
    `core.errors.friendly_message`, and the technical detail goes to the
    log.

  - **Debug mode is off unless asked for.** The Werkzeug debugger is an
    interactive console; it was hardcoded on.
"""

from __future__ import annotations

import logging
import os
import secrets

from flask import Flask, abort, flash, g, jsonify, render_template, request, session

from core import jobs
from core.errors import PipelineError, friendly_message
from core.logging_setup import configure, get_logger

log = get_logger(__name__)

CSRF_SESSION_KEY = "_csrf_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _csrf_token() -> str:
    if CSRF_SESSION_KEY not in session:
        session[CSRF_SESSION_KEY] = secrets.token_urlsafe(32)
    return session[CSRF_SESSION_KEY]


def _check_csrf() -> None:
    """Reject any unsafe request without a matching token.

    Accepts the token from a form field or the X-CSRF-Token header, since
    the frontend posts JSON as well as forms. Compared with
    `secrets.compare_digest` rather than `==`.
    """
    if request.method in SAFE_METHODS:
        return
    expected = session.get(CSRF_SESSION_KEY)
    supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    if not expected or not secrets.compare_digest(str(expected), str(supplied)):
        abort(400, description="This form expired or came from somewhere unexpected. "
                               "Reload the page and try again.")


def _wants_json() -> bool:
    return (request.path.startswith("/api/")
            or request.accept_mimetypes.best == "application/json"
            or request.is_json)


def create_app(debug: bool = False) -> Flask:
    configure(level=logging.DEBUG if debug else logging.INFO)
    jobs.install()

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024      # merch photo uploads
    # Jinja only auto-reloads templates when debug is on, so with debug
    # off a template edit silently did nothing until the server was
    # restarted — which reads as "my change didn't work". This is a
    # single-user local app; the stat() per render costs nothing.
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    # A stable key keeps sessions (and therefore CSRF tokens) valid across
    # restarts. Generated and stored on first run rather than committed.
    app.secret_key = os.environ.get("SHORTS_SECRET_KEY") or _local_secret()

    app.before_request(_check_csrf)

    @app.context_processor
    def inject_csrf():
        return {"csrf_token": _csrf_token}

    @app.context_processor
    def inject_chrome():
        """Counts the header needs on every page.

        Both are cheap directory reads, and both answer questions the app
        previously only answered on one specific page: how much is waiting
        for you, and whether anything is running right now.
        """
        try:
            from core import gallery
            from core.channels import load_channels
            waiting = 0
            for channel in load_channels(validate=False).values():
                state = gallery.video_state_counts(channel.output_dir)
                waiting += state["unpublished"]
            return {"review_waiting": waiting,
                    "active_job_count": len(jobs.active_jobs())}
        except Exception:  # noqa: BLE001 - chrome must never break a page
            return {"review_waiting": 0, "active_job_count": 0}

    @app.context_processor
    def inject_fonts():
        """The caption faces this machine can actually render.

        A context processor rather than an argument to each render call:
        both pages that carry the channel form need it, the answer is
        cached for the process, and passing it by hand is exactly the kind
        of thing one of the two call sites eventually forgets.
        """
        from core import fonts
        return {"font_faces": fonts.available()}

    @app.errorhandler(PipelineError)
    def handle_pipeline_error(exc):
        log.warning(f"{type(exc).__name__}: {exc}")
        if _wants_json():
            return jsonify({"error": exc.user_message}), 400
        return render_template("error.html", message=exc.user_message), 400

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Let Flask's own HTTP errors (404, 400 from abort) through
        # untouched — they already carry the right status and message.
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            if _wants_json():
                return jsonify({"error": exc.description}), exc.code
            return render_template("error.html", message=exc.description), exc.code

        log.exception("Unhandled error")
        message = friendly_message(exc)
        if _wants_json():
            return jsonify({"error": message}), 500
        return render_template("error.html", message=message), 500

    from web.blueprints import (
        channels, curriculum, footage, gallery, jobs as jobs_bp, logos,
        review, setup, voice_lab, youtube,
    )
    app.register_blueprint(channels.bp)
    app.register_blueprint(curriculum.bp)
    app.register_blueprint(gallery.bp)
    app.register_blueprint(jobs_bp.bp)
    app.register_blueprint(footage.bp)
    app.register_blueprint(logos.bp)
    app.register_blueprint(review.bp)
    app.register_blueprint(setup.bp)
    app.register_blueprint(voice_lab.bp)
    app.register_blueprint(youtube.bp)

    return app


def _local_secret() -> str:
    """A per-installation key, generated once into cache/ and reused.

    Without this the key would change on every restart and every open
    page's CSRF token would break — which trains people to ignore the
    error rather than heed it.
    """
    from core.paths import CACHE_DIR
    path = CACHE_DIR / "secret_key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(48)
    path.write_text(key, encoding="utf-8")
    return key
