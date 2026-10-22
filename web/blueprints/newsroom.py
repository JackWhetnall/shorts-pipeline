"""
The newsroom page (decision 130): every film the newsroom has in hand as a
row of steps, what's being worked on, what the next run should get through,
and the week's points, at a glance; the detail on hover.
"""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, abort, redirect, render_template, request, url_for

from core import newsroom
from web.helpers import channel_or_404

bp = Blueprint("newsroom", __name__)


def _channel(key: str):
    channel = channel_or_404(key)
    if channel.format != "documentary":
        abort(404, description="Only a documentary channel has a newsroom.")
    return channel


def _until(when: datetime) -> str:
    minutes = max(0, int((when - datetime.now()).total_seconds() // 60))
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


@bp.route("/channels/<key>/newsroom")
def page(key):
    channel = _channel(key)
    data = newsroom.board(channel)
    template = "_newsroom_board.html" if request.args.get("partial") else "newsroom.html"
    return render_template(template, key=key, channel=channel, b=data, until=_until(data["next_run"]),
                           steps=newsroom.STEPS, studio=newsroom.STUDIO)


@bp.route("/channels/<key>/newsroom/release/<subtopic_id>", methods=["POST"])
def release(key, subtopic_id):
    _channel(key)
    newsroom.release(key, subtopic_id)
    return redirect(url_for("newsroom.page", key=key))
