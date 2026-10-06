"""
A quiz round's questions laid out to judge one by one (pipeline.quiz_review,
decision 055): from the topic plan for a round written ahead, and from
the review queue for a made short.

A round written ahead is changed in place, so the video made from it later
asks the new questions; nothing about making videos changes. A made short
is changed as a draft beside it, and "Remake with these changes" discards
the short and makes it again from the draft, voicing only the lines that
changed.
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, redirect, render_template, request, url_for

from core import curriculum, gallery
from core.errors import PipelineError
from core.logging_setup import get_logger
from web.helpers import all_channels, channel_or_404, video_or_404

log = get_logger(__name__)

bp = Blueprint("quiz_review", __name__)


def _phone() -> bool:
    return request.values.get("m") == "1"


def _back(endpoint: str, note: str = "", **params):
    return redirect(url_for(endpoint, note=note or None, m="1" if _phone() else None, **params))


def _render(channel, script: dict, title: str, **extra):
    from pipeline import quiz_review
    return render_template(
        "quiz_review.html", channel=channel, key=channel.key, title=title,
        quiz=script.get("quiz") or {}, questions=quiz_review.rows(channel, script),
        verdicts=quiz_review.VERDICTS, phone=_phone(), note=request.args.get("note", ""),
        hook=(script.get("quiz") or {}).get("hook", ""), **extra)


# --- a round written ahead ---------------------------------------------------

def _stored(key: str, subtopic_id: str) -> dict:
    row = curriculum.find(key, subtopic_id) if curriculum.exists(key) else None
    if row is None:
        abort(404, description="That round is no longer in the topic plan.")
    return row


@bp.route("/channels/<key>/questions/<subtopic_id>")
def written(key, subtopic_id):
    channel = channel_or_404(key)
    row = _stored(key, subtopic_id)
    if row.get("video_stem"):
        video = _video_of(channel, row["video_stem"])
        if video is not None:
            return redirect(url_for("quiz_review.made", relpath=_relpath(video), m="1" if _phone() else None))
    if not (row.get("script") or {}).get("quiz"):
        abort(404, description="That round hasn't been written yet.")
    return _render(channel, row["script"], row["title"], subtopic=row, mode="written", can_swap=True,
                   judge_url=url_for("quiz_review.judge_written", key=key, subtopic_id=subtopic_id))


@bp.route("/channels/<key>/questions/<subtopic_id>/judge", methods=["POST"])
def judge_written(key, subtopic_id):
    from pipeline import quiz_review
    channel = channel_or_404(key)
    row = _stored(key, subtopic_id)
    script = row.get("script")
    if not (script or {}).get("quiz"):
        abort(404, description="That round hasn't been written yet.")
    try:
        notes = [quiz_review.judge(channel, script, index, request.form.get("verdict", ""),
                                   request.form.get("reason", ""))["message"]
                 for index in _indices(script)]
    except PipelineError as exc:
        return _back("quiz_review.written", exc.user_message, key=key, subtopic_id=subtopic_id)
    curriculum.set_script(key, subtopic_id, script)
    return _back("quiz_review.written", _summary(notes), key=key, subtopic_id=subtopic_id)


# --- a made short -------------------------------------------------------------

def _relpath(video: Path) -> str:
    return str(video.relative_to(gallery.OUTPUT_DIR)).replace("\\", "/")


def _video_of(channel, stem: str):
    directory = gallery.resolve_output_dir(channel.output_dir)
    if not directory.exists():
        return None
    return next((v for v in gallery.videos_in(directory) if v.stem == stem), None)


def _channel_of(video: Path):
    key = gallery._channel_key_for(video)
    channel = all_channels().get(key) if key else None
    if channel is None:
        abort(404, description="Couldn't tell which channel this video belongs to.")
    return channel


def _made_round(video: Path, channel) -> tuple:
    """(script, editable, can_swap, publish info) for a made short. Swaps
    only while it's still to decide: one gone out or discarded can't be
    remade from here, though verdicts on it still teach the bank."""
    from pipeline import quiz_review
    script = quiz_review.draft(channel, video)
    editable = script is not None
    info = gallery.load_publish_info(video)
    can_swap = editable and not info["discarded"] and not gallery.is_out(info)
    return script or quiz_review.read_only_script(video), editable, can_swap, info


@bp.route("/videos/<path:relpath>/questions")
def made(relpath):
    from pipeline import quiz_review
    video = video_or_404(relpath)
    channel = _channel_of(video)
    script, editable, can_swap, info = _made_round(video, channel)
    if not script["quiz"]["questions"]:
        abort(404, description="This video isn't a quiz round.")
    return _render(channel, script, info.get("title") or gallery.video_title(video.name),
                   mode="made", editable=editable, can_swap=can_swap, relpath=relpath,
                   discarded=info["discarded"], out=gallery.is_out(info),
                   swapped=quiz_review.swapped(channel, video) if can_swap else [],
                   judge_url=url_for("quiz_review.judge_made", relpath=relpath))


@bp.route("/videos/<path:relpath>/questions/judge", methods=["POST"])
def judge_made(relpath):
    from pipeline import quiz_review
    video = video_or_404(relpath)
    channel = _channel_of(video)
    script, _, can_swap, _ = _made_round(video, channel)
    try:
        notes = [quiz_review.judge(channel, script, index, request.form.get("verdict", ""),
                                   request.form.get("reason", ""), swap=can_swap)["message"]
                 for index in _indices(script)]
    except PipelineError as exc:
        return _back("quiz_review.made", exc.user_message, relpath=relpath)
    if can_swap:
        quiz_review.save_draft(video, script)
    return _back("quiz_review.made", _summary(notes), relpath=relpath)


@bp.route("/videos/<path:relpath>/questions/undo", methods=["POST"])
def undo_draft(relpath):
    """Forget the swaps: the short stays as it was made. What the bank
    learnt (levels moved, questions taken out) stands."""
    from pipeline import quiz_review
    from pipeline.facts import bank, store
    video = video_or_404(relpath)
    channel = _channel_of(video)
    path = quiz_review.draft_path(video)
    made_script = quiz_review.made_script(channel, video) or {}
    if path.exists():
        drafted = quiz_review.draft(channel, video)
        kept = {q.get("bank_id") for q in (made_script.get("quiz") or {}).get("questions") or []}
        extra = [q["bank_id"] for q in drafted["quiz"]["questions"] if q.get("bank_id") and q["bank_id"] not in kept]
        bank.unuse(store.connect(), channel.key, extra)
        path.unlink()
    return _back("quiz_review.made", "Changes dropped; the video is as it was made.", relpath=relpath)


@bp.route("/videos/<path:relpath>/questions/remake", methods=["POST"])
def remake(relpath):
    """Discard this short and make it again from its draft: the same round
    and number, with the swapped questions, voicing only what changed
    (core.remake)."""
    from core import remake as remaking
    from pipeline import quiz_review
    video = video_or_404(relpath)
    channel = _channel_of(video)
    path = quiz_review.draft_path(video)
    if not path.exists():
        return _back("quiz_review.made", "Nothing has been changed to remake it with.", relpath=relpath)
    row = next((s for s in curriculum.subtopics(channel.key) if s.get("video_stem") == video.stem), None) \
        if curriculum.exists(channel.key) else None
    if row is None:
        return _back("quiz_review.made", "This video isn't on the topic plan, so it can't be remade from "
                                         "here. Make it again from Create video.", relpath=relpath)
    drafted = quiz_review.draft(channel, video)
    # On the plan too: if it can't be made now, the round keeps its new
    # questions for whenever it is.
    curriculum.set_script(channel.key, row["id"], drafted)
    try:
        remaking.start(channel, video, script=drafted)
    except PipelineError as exc:
        # Only the app waiting to restart refuses now (a remake queues
        # behind anything this channel is making).
        return _back("quiz_review.made", f"{exc.user_message} The new questions are kept, so "
                                         f"Remake works once it's back.", relpath=relpath)
    path.unlink(missing_ok=True)
    if _phone():
        return redirect(url_for("phone.home", note="Remaking it; it'll be back in review when it's done."))
    return redirect(url_for("jobs.activity"))


# --- helpers ---------------------------------------------------------------

def _indices(script: dict) -> list:
    """The question judged, or with "all" every one not yet looked at."""
    if request.form.get("index") == "all":
        return [i for i, q in enumerate(script["quiz"]["questions"]) if not q.get("approved")]
    try:
        return [int(request.form.get("index", ""))]
    except ValueError:
        raise PipelineError("no question index", user_message="Pick a question first.")


def _summary(notes: list) -> str:
    if len(notes) > 1:
        return f"{len(notes)} questions kept."
    return notes[0] if notes else "Nothing to change."
