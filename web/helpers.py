"""
Shared route helpers.

`channel_or_404` and `channel_progress` exist here rather than being
duplicated per blueprint because the home page, the dashboard and the
generate-eligibility checks all need the same derived numbers, and any
two of them disagreeing is a bug that shows as "the button is missing".
"""

from __future__ import annotations

from datetime import datetime

from flask import abort, url_for

from core import gallery, jobs, launch
from core.errors import PipelineError
from core.channels import load_channels
from core.paths import OUTPUT_DIR, safe_join, PathTraversalError


def all_channels() -> dict:
    """Always re-read: the app saves and then immediately renders, and a
    cached copy is exactly the bug that used to cause. Validation is off
    so one malformed channel can't blank the whole list — the settings
    page is where it gets fixed."""
    return load_channels(validate=False)


def channel_or_404(key: str):
    channels = all_channels()
    if key not in channels:
        abort(404, description=f'There is no channel called "{key}".')
    return channels[key]


def video_or_404(relpath: str):
    """Resolve a video path from a URL, refusing anything outside
    output/."""
    try:
        target = safe_join(OUTPUT_DIR, relpath)
    except PathTraversalError:
        abort(404, description="That video path isn't valid.")
    if not target.exists():
        abort(404, description="That video no longer exists.")
    return target


# Where each launch or grow stage gets done: (endpoint, params). The
# anchor/query parts land you on the exact card or section.
STAGE_LINKS = {
    "content": ("setup.setup_step", {"step": "content"}),
    "sample": ("channels.create_video", {}),
    "logo": ("logos.logo_page", {}),
    "youtube": ("channels.settings", {"_anchor": "section-publishing"}),
    "plan": ("channels.settings", {"_anchor": "section-publishing"}),
    "shadow": ("review.queue", {}),
    "autopilot": ("channels.settings", {"_anchor": "section-publishing"}),
    "tiktok": ("channels.settings", {"_anchor": "section-publishing"}),
    "instagram": ("channels.settings", {"_anchor": "section-publishing"}),
    "audit": ("youtube.setup", {}),
    "patreon": ("channels.settings", {"_anchor": "section-money"}),
    "merch_logo": ("logos.logo_page", {}),
    "merch_store": ("channels.settings", {"_anchor": "section-money"}),
    "affiliate": ("channels.settings", {"_anchor": "section-money"}),
}


def _stage_row(channel, stage) -> dict:
    endpoint, params = STAGE_LINKS[stage.id]
    params = dict(params)
    if endpoint == "review.queue":
        params["channel"] = channel.key
    elif endpoint != "youtube.setup":
        params["key"] = channel.key
    return {
        "id": stage.id, "label": stage.label, "who": stage.who, "done": stage.done,
        "skipped": stage.skipped, "detail": stage.detail,
        "link": url_for(endpoint, **params),
        "toggle_link": url_for("channels.toggle_checklist", key=channel.key, item_id=stage.id),
    }


def channel_progress(key: str, channel) -> dict:
    """Everything the home page, the dashboard and the generate buttons
    need, computed once, so no two of them can disagree about where a
    channel is (see core.launch)."""
    state = gallery.video_state_counts(channel.output_dir)
    launch_stages, grow_stages = launch.stages(channel, state)
    launch_rows = [_stage_row(channel, s) for s in launch_stages]
    grow_rows = [_stage_row(channel, s) for s in grow_stages]
    now = launch.current(launch_stages)
    active_job = jobs.active_job_for_channel(key)

    try:
        channel.validate()
        setup_problem = None
    except PipelineError as exc:
        setup_problem = exc.user_message

    return {
        "setup_problem": setup_problem,
        "video_count": state["active"],
        "published_count": state["published"],
        "unpublished_count": state["unpublished"],
        "waiting_count": state["waiting"],
        "queued_count": state["queued"],
        "discarded_count": state["discarded"],
        "launch": launch_rows,
        "grow": grow_rows,
        "current_stage": next((r for r in launch_rows if r["id"] == now.id), None) if now else None,
        "launch_settled": sum(1 for s in launch_stages if s.settled),
        "launch_total": len(launch_stages),
        "grow_remaining": sum(1 for s in grow_stages if not s.settled),
        "section": launch.section(channel, launch_stages, state),
        "active_job": active_job,
        # Making one by hand is always allowed on the dashboard; the quick
        # button stops at the channel's buffer of videos waiting for a look,
        # so a click-happy afternoon can't bury the review queue.
        "can_generate": (setup_problem is None and active_job is None
                         and state["waiting"] < channel.publishing.buffer),
    }


def as_int(raw, default: int, minimum: int = None, maximum: int = None) -> int:
    """Parse a number out of request data without ever raising.

    Query strings and form fields are user input — hand-typed, bookmarked,
    stale, occasionally hostile. `int(request.args.get("page"))` turning a
    typo into a 500 is a bug in the handler, not bad input.
    """
    try:
        # OverflowError as well as ValueError: "1e999" parses as a float
        # perfectly happily and then explodes on the way to an int.
        value = int(float(raw))
    except (TypeError, ValueError, OverflowError):
        return default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def as_float(raw, default: float, minimum: float = None, maximum: float = None) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return default
    # NaN compares false against every bound, so it would slip past the
    # clamping below untouched.
    if value != value or value in (float("inf"), float("-inf")):
        return default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def format_date(timestamp) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%b %d, %Y") if timestamp else None


def format_iso_date(value) -> str:
    return datetime.fromisoformat(value).strftime("%b %d, %Y") if value else None
