"""
A channel's syllabus: what it will cover, in what order, and where it is.

Generation is the only thing here that costs money, so it is the only
thing that asks first — the page states the figure before the button does
anything, in the same shape as the footage library's enrich step.
"""

from __future__ import annotations

from flask import (
    Blueprint, abort, jsonify, redirect, render_template, request, url_for,
)

from core import curriculum
from core.channels import load_channels
from core.errors import PipelineError
from core.logging_setup import get_logger
from web.helpers import as_int, channel_or_404

log = get_logger(__name__)

bp = Blueprint("curriculum", __name__)

# Bounds on what the outline form will accept. A syllabus of two units is
# not a syllabus, and one of two hundred is a list wearing a costume.
MIN_UNITS, MAX_UNITS = 5, 60
MIN_TOPICS, MAX_TOPICS = 50, 3000


@bp.route("/channels/<key>/curriculum")
def page(key):
    channel = channel_or_404(key)
    from pipeline.curriculum_gen import DEFAULT_TOTAL_TOPICS, DEFAULT_UNIT_COUNT, estimate_cost

    return render_template(
        "curriculum.html",
        key=key, channel=channel,
        progress=curriculum.progress(key),
        units=curriculum.units_with_topics(key),
        next_unit=curriculum.next_unfilled_unit(key),
        cost=estimate_cost(DEFAULT_UNIT_COUNT),
        default_units=DEFAULT_UNIT_COUNT,
        default_topics=DEFAULT_TOTAL_TOPICS,
    )


@bp.route("/api/channels/<key>/curriculum/outline", methods=["POST"])
def make_outline(key):
    """Design the syllabus. One call; no topics yet.

    Refuses to overwrite a syllabus that has been used, because the units
    are what every topic is positioned against — replacing them would
    orphan the record of what has already been made.
    """
    channel = channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}

    existing = curriculum.progress(key)
    if existing["has_curriculum"] and existing["done"] and not data.get("confirm_replace"):
        return jsonify({"error": f"This channel has already made {existing['done']} "
                                 f"videos from its current plan. Replacing it would "
                                 f"lose the record of what has been covered."}), 400

    from pipeline.curriculum_gen import plan_outline

    unit_count = as_int(data.get("unit_count"), 25, MIN_UNITS, MAX_UNITS)
    total = as_int(data.get("total_topics"), 1000, MIN_TOPICS, MAX_TOPICS)
    try:
        outline = plan_outline(channel, unit_count, total,
                               subject_hint=(data.get("subject") or "").strip())
    except PipelineError as exc:
        log.warning(f"{key}: outline generation failed: {exc}")
        return jsonify({"error": exc.user_message}), 502

    curriculum.start(key, outline.get("subject", ""), outline["units"])
    return jsonify({"ok": True, "units": len(outline["units"])})


@bp.route("/api/channels/<key>/curriculum/fill", methods=["POST"])
def fill(key):
    """Write topics for the next unfilled unit, or for several.

    One unit per call rather than the whole syllabus in one go: the
    response has to fit in a token budget, and generating only what is
    about to be used is what keeps a thousand-topic plan cheap.
    """
    channel = channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    wanted = as_int(data.get("units"), 1, 1, 10)

    from pipeline.curriculum_gen import write_unit_topics

    filled, added = [], 0
    for _ in range(wanted):
        unit = curriculum.next_unfilled_unit(key)
        if unit is None:
            break
        try:
            topics = write_unit_topics(channel, curriculum.load(key), unit)
        except PipelineError as exc:
            log.warning(f"{key}: topics for {unit['id']} failed: {exc}")
            # Partial success is still success: report what was written
            # rather than throwing away units that worked.
            if filled:
                break
            return jsonify({"error": exc.user_message}), 502
        before = curriculum.progress(key)["total"]
        curriculum.add_topics(key, unit["id"], topics)
        added += curriculum.progress(key)["total"] - before
        filled.append(unit["title"])

    if not filled:
        return jsonify({"error": "Every unit already has its topics."}), 400
    return jsonify({"ok": True, "units": filled, "topics_added": added,
                    "pending": curriculum.pending_count(key)})


@bp.route("/channels/<key>/curriculum/<topic_id>/skip", methods=["POST"])
def skip(key, topic_id):
    channel_or_404(key)
    try:
        curriculum.skip(key, topic_id, request.form.get("note", ""))
    except PipelineError:
        abort(404, description="That topic is no longer in the plan.")
    return redirect(url_for("curriculum.page", key=key) + f"#{topic_id}")


@bp.route("/channels/<key>/curriculum/<topic_id>/unskip", methods=["POST"])
def unskip(key, topic_id):
    channel_or_404(key)
    try:
        curriculum.unskip(key, topic_id)
    except PipelineError:
        abort(404, description="That topic is no longer in the plan.")
    return redirect(url_for("curriculum.page", key=key) + f"#{topic_id}")


@bp.route("/channels/<key>/curriculum/<topic_id>/next", methods=["POST"])
def make_next(key, topic_id):
    """Jump one topic to the front of the queue."""
    channel_or_404(key)
    try:
        curriculum.move_to_front(key, topic_id)
    except PipelineError as exc:
        abort(400, description=exc.user_message)
    return redirect(url_for("curriculum.page", key=key))


@bp.route("/channels/<key>/curriculum/delete", methods=["POST"])
def delete(key):
    """Throw the syllabus away; the channel reverts to its topic list."""
    channel_or_404(key)
    curriculum.delete(key)
    return redirect(url_for("curriculum.page", key=key))


def channels_running_low() -> list:
    """Channels close to running out of topics, for the home page.

    Surfaced there because running out is the one failure mode of this
    design: it stops generation dead, and the warning is only useful in
    advance.
    """
    low = []
    for key, channel in load_channels(validate=False).items():
        if channel.content_mode != "topic" or not curriculum.exists(key):
            continue
        state = curriculum.progress(key)
        if state["running_low"]:
            low.append({"key": key,
                        "name": channel.channel_display_name or key,
                        "pending": state["pending"],
                        "runway_days": state["runway_days"]})
    return low
