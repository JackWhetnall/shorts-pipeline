"""
"Remake as is": a made video made again, keeping its script, voice,
footage and pictures, and making again only the parts picked (core.remake,
decision 056).
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, redirect, render_template, request, send_file, url_for

from core import gallery, remake
from core.errors import PipelineError
from web.helpers import all_channels, video_or_404

bp = Blueprint("remake", __name__)


def _phone() -> bool:
    return request.values.get("m") == "1"


def _channel_of(video: Path):
    key = gallery._channel_key_for(video)
    channel = all_channels().get(key) if key else None
    if channel is None:
        abort(404, description="Couldn't tell which channel this video belongs to.")
    return channel


@bp.route("/videos/<path:relpath>/remake")
def page(relpath):
    video = video_or_404(relpath)
    channel = _channel_of(video)
    info = gallery.load_publish_info(video)
    return render_template("remake.html", relpath=relpath, channel=channel, phone=_phone(),
                           title=info.get("title") or gallery.video_title(video.name),
                           out=gallery.is_out(info), about=remake.summary(channel, video),
                           note=request.args.get("note", ""))


@bp.route("/videos/<path:relpath>/remake/picture/<part>")
def picture(relpath, part):
    """A shot's keyframe, to recognise the shot by."""
    video = video_or_404(relpath)
    found = next((p for p in remake.parts(video) if p["id"] == part and p.get("picture")), None)
    if found is None:
        abort(404, description="That picture isn't kept.")
    return send_file(found["picture"])


@bp.route("/videos/<path:relpath>/remake", methods=["POST"])
def start(relpath):
    video = video_or_404(relpath)
    channel = _channel_of(video)
    if gallery.is_out(gallery.load_publish_info(video)):
        return redirect(url_for("remake.page", relpath=relpath, m="1" if _phone() else None,
                                note="This video has gone out, so it isn't remade from here."))
    try:
        remake.start(channel, video, redo=set(request.form.getlist("redo")),
                     redraw=set(request.form.getlist("redraw")))
    except PipelineError as exc:
        return redirect(url_for("remake.page", relpath=relpath, m="1" if _phone() else None,
                                note=exc.user_message))
    if _phone():
        return redirect(url_for("phone.home", note="Remaking it; it'll be back in review when it's done."))
    return redirect(url_for("jobs.activity"))
