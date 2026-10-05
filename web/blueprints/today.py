"""
Today, the home page: what needs you, and what runs by itself
(core.today, decision 067).
"""

from __future__ import annotations

from flask import Blueprint, render_template, url_for

from core import today
from core.channels import load_channels
from core.logging_setup import get_logger

log = get_logger(__name__)

bp = Blueprint("today", __name__)


@bp.route("/")
def page():
    from core import money
    channels = load_channels(validate=False)
    try:
        forecast = money.forecast(channels)
    except Exception as exc:  # noqa: BLE001 - the page says money couldn't be read; the rest still shows
        log.warning(f"Today: couldn't work out the money: {exc}")
        forecast = None
    try:
        running = today.running(channels)
        background = today.background()
    except Exception as exc:  # noqa: BLE001 - shown on the page as unavailable
        log.warning(f"Today: couldn't read what's running: {exc}")
        running, background = None, None
    return render_template("today.html", items=today.needs_you(channels, url_for, forecast=forecast),
                           running=running, background=background, forecast=forecast,
                           has_channels=bool(channels))
