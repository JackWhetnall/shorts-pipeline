"""
Today, the home page: what needs you, and what runs by itself
(core.today, decision 067).
"""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from core import today
from core.channels import load_channels
from core.errors import PipelineError
from core.logging_setup import get_logger

log = get_logger(__name__)

bp = Blueprint("today", __name__)


@bp.route("/focus", methods=["POST"])
def set_focus():
    """Look at one channel (or all) in this browser (web.focus)."""
    from web import focus
    key = request.form.get("channel", "")
    back = request.form.get("next") or url_for("today.page")
    if not back.startswith("/") or back.startswith("//"):
        back = url_for("today.page")
    response = redirect(back)
    if key in load_channels(validate=False):
        response.set_cookie(focus.COOKIE, key, max_age=focus.YEAR, samesite="Lax")
    else:
        response.delete_cookie(focus.COOKIE)
    return response


@bp.route("/tests", methods=["POST"])
def set_tests():
    """Show the channels not yet publishing, or not (web.focus, decision 139)."""
    from web import focus
    back = request.form.get("next") or url_for("today.page")
    if not back.startswith("/") or back.startswith("//"):
        back = url_for("today.page")
    response = redirect(back)
    if request.form.get("include") == "1":
        response.set_cookie(focus.TESTS_COOKIE, "1", max_age=focus.YEAR, samesite="Lax")
    else:
        response.delete_cookie(focus.TESTS_COOKIE)
    return response


@bp.route("/api/nav-counts")
def nav_counts():
    from flask import jsonify
    from web import focus, nav_counts as counts
    channels = load_channels(validate=False)
    return jsonify(counts(channels, focus.current(channels)))


@bp.route("/today/jobs/<job_id>/retry", methods=["POST"])
def retry(job_id):
    """A failed video tried again from Today, under the same id so what it
    had made is reused."""
    from core import jobs
    try:
        jobs.retry_job(job_id)
    except PipelineError as exc:
        return redirect(url_for("today.page", note=exc.user_message))
    return redirect(url_for("jobs.activity"))


@bp.route("/today/jobs/<job_id>/dismiss", methods=["POST"])
def dismiss(job_id):
    from core import jobs
    try:
        jobs.dismiss_job(job_id)
    except PipelineError as exc:
        return redirect(url_for("today.page", note=exc.user_message))
    return redirect(url_for("today.page", note="Discarded."))


@bp.route("/today/clear", methods=["POST"])
def clear_out():
    """What went out, cleared: the list starts again from now (decision 139)."""
    from core import digest
    digest.clear()
    return redirect(url_for("today.page"))


def _grouped(rows: list) -> list:
    """[{name, channel, rows}] by channel, each newest first, busiest first."""
    groups = {}
    for r in rows:
        groups.setdefault(r["channel"], {"name": r["name"], "channel": r["channel"], "rows": []})["rows"].append(r)
    return sorted(groups.values(), key=lambda g: -len(g["rows"]))


@bp.route("/")
def page():
    from core import money
    from web import focus
    channels = focus.visible(load_channels(validate=False))
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
    from core import digest
    try:
        after = digest.since()
        out, coming = _grouped(digest.went_out(channels, after)), digest.going_out(channels)
    except Exception as exc:  # noqa: BLE001 - shown on the page as unavailable
        log.warning(f"Today: couldn't read what went out: {exc}")
        after, out, coming = None, None, None
    return render_template("today.html", items=today.needs_you(channels, url_for, forecast=forecast),
                           out=out, out_since=after, coming=coming,
                           note=request.args.get("note", ""),
                           running=running, background=background, forecast=forecast,
                           has_channels=bool(channels))
