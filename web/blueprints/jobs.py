"""
Job status polling and retry, and the Activity page that shows every
video in flight at once.

Until Activity existed, a running job could only be watched from the
Create Video page of the channel that owns it — so two videos going at
once meant two tabs, and knowing there were two at all meant reading a
count in the header and guessing. The header's count now leads here.
"""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, render_template

from core import job_eta, jobs as jobs_core
from core.paths import OUTPUT_DIR, relative_to_output
from web.helpers import all_channels, channel_or_404

bp = Blueprint("jobs", __name__)


def _with_relpath(job: dict) -> dict:
    """Attach the URL-addressable path of the finished video, so the page
    can navigate straight to it rather than rendering a second, worse
    video player of its own."""
    relpath = None
    if job.get("result_path"):
        try:
            relpath = relative_to_output(job["result_path"])
        except ValueError:
            relpath = None
    return {**job, "result_path_rel": relpath}


def _with_eta(job: dict) -> dict:
    """"How much longer?" on the per-channel progress view too, not only
    on Activity — it is the same question in both places, and someone
    watching one job shouldn't have to leave the page to get an answer."""
    if job.get("status") != "running":
        return job
    seconds = job_eta.remaining_seconds(job, jobs_core.history())
    return {**job, "eta_seconds": seconds, "eta_label": job_eta.describe(seconds)}


def _for_activity(job: dict, names: dict) -> dict:
    """One job, trimmed to what the Activity page draws.

    The log tail is dropped deliberately: this response can carry a dozen
    jobs and gets polled every couple of seconds, and the full log has its
    own place on the per-channel progress view.
    """
    seed = job.get("seed") or {}
    return {
        "id": job["id"],
        "channel_key": job["channel_key"],
        "channel_name": names.get(job["channel_key"], job["channel_key"]),
        "status": job["status"],
        "stage": job.get("stage") or 0,
        "stage_total": job.get("stage_total"),
        "stage_label": job.get("stage_labels", {}).get(job.get("stage")),
        "progress_percent": job.get("progress_percent"),
        "queue_position": job.get("queue_position"),
        "title": seed.get("reference") or seed.get("topic") or "Untitled",
        "started_at": job.get("started_at"),
        "queued_at": job.get("queued_at"),
        "finished_at": job.get("finished_at"),
        "error": job.get("error"),
        "warnings": job.get("warnings") or [],
        "result_path_rel": _with_relpath(job)["result_path_rel"],
        "eta_seconds": job.get("eta_seconds"),
        "eta_at": job.get("eta_at"),
        "eta_label": job_eta.describe(job.get("eta_seconds")),
    }


def _activity_payload() -> dict:
    names = {key: channel.channel_display_name
             for key, channel in all_channels().items()}
    history = jobs_core.history()
    active = job_eta.annotate(jobs_core.active_in_order(), history)
    return {
        "active": [_for_activity(job, names) for job in active],
        "recent": [_for_activity(job, names) for job in jobs_core.recent_finished()],
        # Said once on the page rather than per row: an estimate built
        # from two finished videos is worth reading differently from one
        # built from thirty, and hiding that would be the wrong kind of
        # confident.
        "samples": job_eta.sample_count(history),
    }


@bp.route("/activity")
def activity():
    return render_template("activity.html", **_activity_payload())


@bp.route("/api/activity")
def activity_data():
    """Polled by the Activity page. Everything in flight in the order it
    will happen, so the page never has to work out the queue itself."""
    return jsonify(_activity_payload())


@bp.route("/api/jobs/<job_id>")
def get_job(job_id):
    job = jobs_core.get_job(job_id)
    if job is None:
        # Definitive, not transient: the frontend treats a 404 as "this
        # job is gone" and stops polling, rather than retrying forever
        # against an id that will never come back.
        abort(404, description="That job no longer exists — the app may have restarted.")
    return jsonify(_with_eta(_with_relpath(job)))


@bp.route("/api/jobs/<job_id>/retry", methods=["POST"])
def retry(job_id):
    jobs_core.retry_job(job_id)
    return jsonify({"job_id": job_id})


@bp.route("/api/channels/<key>/current-job")
def current_job(key):
    """Lets a page reconnect to a job still in flight after navigating
    away and back. The job never stopped — only the page's view of it."""
    channel_or_404(key)
    job = jobs_core.active_job_for_channel(key)
    return jsonify({"job": _with_eta(_with_relpath(job)) if job else None})


@bp.route("/api/channels/<key>/last-failed-job")
def last_failed_job(key):
    """Surfaces "your last attempt was interrupted — retry?" on load.
    Nothing else exposes a job id, so without this an interrupted job is
    invisible unless you knew to look."""
    channel_or_404(key)
    job = jobs_core.latest_failed_for_channel(key)
    return jsonify({"job": _with_relpath(job) if job else None})
