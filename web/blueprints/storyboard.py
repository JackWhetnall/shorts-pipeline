"""
A channel's next few videos as storyboards, to look at before they're
made (core.storyboard, decision 073). Approving is optional: one not
looked at is made as it is.
"""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from core import curriculum, storyboard
from core.errors import PipelineError
from core.logging_setup import get_logger
from web.helpers import channel_or_404

log = get_logger(__name__)

bp = Blueprint("storyboard", __name__)


def _back(key: str, note: str = "", anchor: str = None):
    return redirect(url_for("storyboard.page", key=key, note=note or None, _anchor=anchor))


def _row(key: str, subtopic_id: str) -> dict:
    row = curriculum.find(key, subtopic_id) if curriculum.exists(key) else None
    if row is None or row["status"] != curriculum.PENDING:
        raise PipelineError(f"no pending {subtopic_id}", user_message="That video has been made or taken off "
                                                                      "the plan since.")
    return row


@bp.route("/channels/<key>/coming-up")
def page(key):
    channel = channel_or_404(key)
    if channel.format == "documentary":
        return redirect(url_for("productions.index", key=key))
    rows = storyboard.upcoming(channel)
    return render_template("storyboard.html", key=key, channel=channel,
                           boards=[storyboard.view(channel, row) for row in rows],
                           writing=storyboard.writing(key), note=request.args.get("note", ""),
                           coming_up=storyboard.COMING_UP)


@bp.route("/channels/<key>/coming-up/write", methods=["POST"])
def write_now(key):
    """The missing storyboards, written now at full price rather than
    waiting for the hourly batch."""
    channel = channel_or_404(key)
    if not storyboard.missing(channel):
        return _back(key, "Every one is written.")
    started = storyboard.start([channel], batch=False)
    return _back(key, "Writing them now; this page shows them when they're done." if started
                 else "They're already being written.")


@bp.route("/channels/<key>/coming-up/<subtopic_id>/approve", methods=["POST"])
def approve(key, subtopic_id):
    channel_or_404(key)
    try:
        _row(key, subtopic_id)
        curriculum.mark_storyboard(key, subtopic_id, approved=True)
    except PipelineError as exc:
        return _back(key, exc.user_message)
    return _back(key, "Approved.", anchor=subtopic_id)


@bp.route("/channels/<key>/coming-up/<subtopic_id>/edit", methods=["POST"])
def edit(key, subtopic_id):
    channel = channel_or_404(key)
    try:
        _row(key, subtopic_id)
        storyboard.edit(channel, subtopic_id, request.form.getlist("text"), request.form.getlist("shot_brief"))
    except PipelineError as exc:
        return _back(key, exc.user_message, anchor=subtopic_id)
    return _back(key, "Saved, and approved.", anchor=subtopic_id)


@bp.route("/channels/<key>/coming-up/<subtopic_id>/rewrite", methods=["POST"])
def rewrite(key, subtopic_id):
    channel = channel_or_404(key)
    note = " ".join(request.form.get("note", "").split())
    try:
        storyboard.write(channel, _row(key, subtopic_id), note)
    except PipelineError as exc:
        return _back(key, exc.user_message, anchor=subtopic_id)
    return _back(key, "Written again.", anchor=subtopic_id)
