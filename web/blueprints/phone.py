"""
The phone pages: /m, a small version of the daily loop for a phone on the
home network (decision 055). What's being made, what's waiting for
review (watch it, approve or discard it, check a quiz's questions), and a
button to make the next video. Everything else stays on the PC.

Plus the PC's page for turning phone access on (core.phone_access), and
the sign-in page a phone gives the code on.
"""

from __future__ import annotations

from urllib.parse import urlparse

from flask import Blueprint, abort, current_app, redirect, render_template, request, session, url_for

from core import code_freshness, curriculum, gallery, jobs, phone_access, publish_queue
from core.errors import PipelineError
from core.logging_setup import get_logger
from web.blueprints.review import _queue
from web.helpers import all_channels, channel_or_404, video_or_404

log = get_logger(__name__)

bp = Blueprint("phone", __name__)

PICKS_SHOWN = 30        # rounds offered to pick from when making a video


def _home(note: str = ""):
    return redirect(url_for("phone.home", note=note or None))


@bp.route("/m")
def home():
    from web.blueprints.jobs import _activity_payload
    activity = _activity_payload()
    waiting = [v for v in _queue() if not v["queued"]]
    channels = []
    for key, channel in sorted(all_channels().items(), key=lambda kv: kv[1].channel_display_name.lower()):
        picks, written = [], 0
        if curriculum.exists(key):
            pending = curriculum.subtopics(key, status=curriculum.PENDING)
            picks = pending[:PICKS_SHOWN]
            written = sum(1 for s in pending if (s.get("script") or {}).get("quiz"))
        channels.append({"key": key, "name": channel.channel_display_name, "picks": picks,
                         "quiz": channel.format == "quiz", "written": written,
                         "waiting": sum(1 for v in waiting if v["channel_key"] == key),
                         "busy": any(j["channel_key"] == key for j in activity["active"])})
    return render_template("m_home.html", active=activity["active"], recent=activity["recent"][:3],
                           waiting=len(waiting), channels=channels, note=request.args.get("note", ""))


@bp.route("/m/review")
def review():
    items = [v for v in _queue() if not v["queued"]]
    return render_template("m_review.html", items=items, reasons=gallery.DISCARD_REASONS,
                           note=request.args.get("note", ""))


@bp.route("/m/videos/<path:relpath>/approve", methods=["POST"])
def approve(relpath):
    try:
        publish_queue.enqueue(video_or_404(relpath), approved_by="you")
    except PipelineError as exc:
        return redirect(url_for("phone.review", note=exc.user_message))
    return redirect(url_for("phone.review", note="Approved: it goes out at the next publishing slot."))


@bp.route("/m/videos/<path:relpath>/discard", methods=["POST"])
def discard(relpath):
    gallery.set_discarded(video_or_404(relpath), True, reason=request.form.get("reason"))
    return redirect(url_for("phone.review", note="Discarded. Its topic goes back in the plan."))


@bp.route("/m/make/<key>", methods=["POST"])
def make(key):
    """The next video, or the round picked, straight to making: no seed
    review on a phone."""
    from pipeline.run import fetch_seed
    channel = channel_or_404(key)
    picked = request.form.get("subtopic_id", "")
    try:
        seed = fetch_seed(channel, pick={"subtopic_id": picked} if picked else None)
        jobs.start_job(key, seed.to_jsonable())
    except PipelineError as exc:
        return _home(exc.user_message)
    return _home(f"Making “{seed.title}”. It'll be in review when it's done.")


@bp.route("/m/rounds/<key>")
def rounds(key):
    """A quiz channel's rounds written ahead, to check their questions."""
    channel = channel_or_404(key)
    rows = [s for s in curriculum.subtopics(key, status=curriculum.PENDING)
            if (s.get("script") or {}).get("quiz")] if curriculum.exists(key) else []
    return render_template("m_rounds.html", channel=channel, key=key, rows=rows)


# --- signing a phone in -------------------------------------------------------

def _safe_next(target: str) -> str:
    parts = urlparse(target or "")
    if parts.scheme or parts.netloc or not (target or "").startswith("/") or target.startswith("//"):
        return url_for("phone.home")
    return target


@bp.route("/m/sign-in", methods=["GET", "POST"])
def sign_in():
    address = request.remote_addr or ""
    problem = ""
    if request.method == "POST":
        if phone_access.check(address, request.form.get("code", "")):
            session.permanent = True
            session["phone"] = phone_access.token()
            return redirect(_safe_next(request.form.get("next", "")))
        problem = ("Too many wrong codes. Wait a quarter of an hour." if phone_access.locked_out(address)
                   else "That isn't the code. It's on the PC, under Phone.")
    return render_template("m_sign_in.html", problem=problem, next=request.values.get("next", ""))


# --- the PC's page ------------------------------------------------------------

@bp.route("/phone")
def setup():
    if not phone_access.is_local(request.remote_addr):
        abort(403, description="Phone access is set up from the PC itself.")
    state = phone_access.settings()
    port = request.host.split(":")[1] if ":" in request.host else "5000"
    return render_template("phone_setup.html", state=state, port=port,
                           addresses=phone_access.addresses(),
                           listening=current_app.config.get("LISTEN_HOST") == "0.0.0.0",
                           restarting=code_freshness.is_stale(), note=request.args.get("note", ""))


@bp.route("/phone/set", methods=["POST"])
def set_access():
    if not phone_access.is_local(request.remote_addr):
        abort(403, description="Phone access is set up from the PC itself.")
    action = request.form.get("action")
    if action == "new-code":
        phone_access.change_code()
        return redirect(url_for("phone.setup", note="New code made. Phones signed in before need it."))
    phone_access.set_enabled(action == "on")
    # What the app listens on is set when it starts.
    restarting = code_freshness.request_restart("Phone access changed")
    note = ("Restarting to listen on the network; this page comes back in a few seconds."
            if action == "on" else "Phone access is off; the app is restarting to stop listening on the network.")
    if not restarting:
        note = "Saved. Restart the app for it to apply."
    return redirect(url_for("phone.setup", note=note))
