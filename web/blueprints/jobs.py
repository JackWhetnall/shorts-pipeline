"""
Job status polling and retry.
"""

from __future__ import annotations

from flask import Blueprint, abort, jsonify

from core import jobs as jobs_core
from core.paths import OUTPUT_DIR, relative_to_output
from web.helpers import channel_or_404

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


@bp.route("/api/jobs/<job_id>")
def get_job(job_id):
    job = jobs_core.get_job(job_id)
    if job is None:
        # Definitive, not transient: the frontend treats a 404 as "this
        # job is gone" and stops polling, rather than retrying forever
        # against an id that will never come back.
        abort(404, description="That job no longer exists — the app may have restarted.")
    return jsonify(_with_relpath(job))


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
    return jsonify({"job": _with_relpath(job) if job else None})


@bp.route("/api/channels/<key>/last-failed-job")
def last_failed_job(key):
    """Surfaces "your last attempt was interrupted — retry?" on load.
    Nothing else exposes a job id, so without this an interrupted job is
    invisible unless you knew to look."""
    channel_or_404(key)
    job = jobs_core.latest_failed_for_channel(key)
    return jsonify({"job": _with_relpath(job) if job else None})
