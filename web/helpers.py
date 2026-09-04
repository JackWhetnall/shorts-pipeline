"""
Shared route helpers.

`channel_or_404` and `checklist_for` exist here rather than being
duplicated per blueprint because the home page, the dashboard and the
generate-eligibility checks all need the same derived numbers, and any
two of them disagreeing is a bug that shows as "the button is missing".
"""

from __future__ import annotations

from datetime import datetime

from flask import abort, url_for

from core import gallery, jobs
from core.errors import PipelineError
from core.channels import load_channels
from core.paths import OUTPUT_DIR, safe_join, PathTraversalError
from web import checklist


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


def checklist_for(channel, video_count: int) -> list:
    """Checklist items with a "fix this" URL attached."""
    items = []
    for item in checklist.build(channel, video_count):
        endpoint, params = checklist.FIX_STEP[item.id]
        blueprint = {"logo_page": "logos", "settings": "channels",
                     "create_video": "channels"}[endpoint]
        items.append({
            "id": item.id, "label": item.label, "done": item.done, "manual": item.manual,
            "link": url_for(f"{blueprint}.{endpoint}", key=channel.key, **params),
            "toggle_link": url_for("channels.toggle_checklist", key=channel.key,
                                   item_id=item.id),
        })
    return items


def channel_progress(key: str, channel) -> dict:
    """Everything the home page and the eligibility checks need, computed
    once.

    `can_generate` is defined here and nowhere else, so the per-card
    button, "generate all", and the scheduler can never disagree about
    whether a channel is ready.
    """
    state = gallery.video_state_counts(channel.output_dir)
    items = checklist_for(channel, state["active"])
    essentials, extras = checklist.split(items)
    # Only the essentials gate going live. The extras are a to-do list.
    remaining = sum(1 for item in essentials if not item["done"])
    section = checklist.section_for(channel, remaining, len(essentials), state["published"])
    active_job = jobs.active_job_for_channel(key)

    # A channel is created from a name alone and filled in through the
    # wizard, so "exists" and "can make a video" are different questions.
    # This is the only thing that answers the second, and it answers it
    # with the same check the pipeline would fail on later — so the reason
    # shown here is the reason it would have failed.
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
        "discarded_count": state["discarded"],
        "checklist": items,
        "checklist_essential": essentials,
        "checklist_extras": extras,
        "checklist_remaining": remaining,
        "extras_remaining": sum(1 for item in extras if not item["done"]),
        "section": section,
        "active_job": active_job,
        "can_generate": (setup_problem is None
                         and section == "live"
                         and state["unpublished"] == 0
                         and active_job is None),
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
