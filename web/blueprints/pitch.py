"""
Pitch an idea, review the draft channel, accept it.

The flow in docs/specs/launch-pipeline-and-publishing.md, stages 1-3:
core.drafts does the work; these routes are the pages around it.
"""

from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template, request, url_for

from core import drafts, palettes
from core.errors import PipelineError
from core.logging_setup import get_logger
from web.blueprints.scenes import art_from, form_context

log = get_logger(__name__)

bp = Blueprint("pitch", __name__)


def _draft_or_404(draft_id: str) -> dict:
    record = drafts.load(draft_id)
    if record is None:
        abort(404, description="That draft no longer exists. It may have been accepted or discarded.")
    return record


@bp.route("/channels/pitch", methods=["POST"])
def pitch():
    text = request.form.get("pitch", "")
    try:
        record = drafts.create(text, note=request.form.get("note", ""))
    except PipelineError as exc:
        return render_template("new_channel.html", display_name="", key="",
                               pitch_text=text, pitch_error=exc.user_message,
                               drafts=drafts.all_drafts()), 400
    return redirect(url_for("pitch.review", draft_id=record["id"]))


@bp.route("/channels/drafts/<draft_id>")
def review(draft_id):
    record = _draft_or_404(draft_id)
    body = record["channel"]
    drafted_art = body.get("art") or {}
    return render_template(
        "channel_draft.html", draft=record, body=body,
        palettes=palettes.PALETTES,
        error=request.args.get("error"),
        **form_context(drafted_art, drafted_art.get("scene_share", 0)),
        music_draft=True, music_channel_key="", music_tracks=[],
        music_suggest_url=url_for("music.suggest_for_draft", draft_id=draft_id),
    )


@bp.route("/channels/drafts/<draft_id>/redraft", methods=["POST"])
def redraft(draft_id):
    record = _draft_or_404(draft_id)
    note = request.form.get("note", "").strip()
    if not note:
        return redirect(url_for("pitch.review", draft_id=draft_id,
                                error="Say what to change, then redraft."))
    try:
        drafts.create(record["pitch"], note=note, previous=record)
    except PipelineError as exc:
        return redirect(url_for("pitch.review", draft_id=draft_id, error=exc.user_message))
    return redirect(url_for("pitch.review", draft_id=draft_id))


@bp.route("/channels/drafts/<draft_id>/accept", methods=["POST"])
def accept(draft_id):
    _draft_or_404(draft_id)
    form = request.form
    name = form.get("name_choice", "")
    if name == "__custom__":
        name = form.get("name_custom", "")
    choices = {
        "name": name,
        "style_prompt": form.get("style_prompt"),
        "hook_style": form.get("hook_style"),
        "voice": form.get("voice"),
        "palette": form.get("palette"),
        "target_seconds": form.get("target_seconds"),
        "segment_count": form.get("segment_count"),
        "speed": form.get("speed"),
        "avoid_imagery": [a.strip().lower() for a in form.get("avoid_imagery", "").split(",")
                          if a.strip()],
        "art": art_from(form),
        "scene_share": form.get("scene_share"),
        "music": form.getlist("music_track"),
    }
    if "quotes" in form:
        choices["quotes"] = form.get("quotes", "")
    try:
        channel = drafts.accept(draft_id, choices)
    except PipelineError as exc:
        return redirect(url_for("pitch.review", draft_id=draft_id, error=exc.user_message))
    return redirect(url_for("channels.dashboard", key=channel.key, created=1))


@bp.route("/channels/drafts/<draft_id>/discard", methods=["POST"])
def discard(draft_id):
    drafts.discard(draft_id)
    return redirect(url_for("channels.new_channel"))
