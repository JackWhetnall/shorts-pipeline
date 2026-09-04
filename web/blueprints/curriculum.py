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

# Bounds on what the outline form will accept. A syllabus of two topics is
# not a syllabus, and one of two hundred is a list wearing a costume.
MIN_TOPICS, MAX_TOPICS = 5, 80
MIN_SUBTOPICS, MAX_SUBTOPICS = 50, 3000


@bp.route("/channels/<key>/curriculum")
def page(key):
    channel = channel_or_404(key)
    from pipeline.curriculum_gen import (
        DEFAULT_TOPIC_COUNT, DEFAULT_TOTAL_SUBTOPICS, estimate_cost)

    return render_template(
        "curriculum.html",
        key=key, channel=channel,
        progress=curriculum.progress(key),
        topics=curriculum.topics_with_subtopics(key),
        next_topic=curriculum.next_unfilled_topic(key),
        cost=estimate_cost(DEFAULT_TOPIC_COUNT),
        default_topics=DEFAULT_TOPIC_COUNT,
        default_subtopics=DEFAULT_TOTAL_SUBTOPICS,
    )


@bp.route("/api/channels/<key>/curriculum/outline", methods=["POST"])
def make_outline(key):
    """Design the syllabus. One call; no subtopics yet.

    Refuses to overwrite a syllabus that has been used, because the topics
    are what every subtopic is positioned against — replacing them would
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

    topic_count = as_int(data.get("topic_count"), 40, MIN_TOPICS, MAX_TOPICS)
    total = as_int(data.get("total_subtopics"), 1000, MIN_SUBTOPICS, MAX_SUBTOPICS)
    try:
        outline = plan_outline(channel, topic_count, total,
                               subject_hint=(data.get("subject") or "").strip())
    except PipelineError as exc:
        log.warning(f"{key}: outline generation failed: {exc}")
        return jsonify({"error": exc.user_message}), 502

    curriculum.start(key, outline.get("subject", ""), outline["topics"])
    return jsonify({"ok": True, "topics": len(outline["topics"])})


@bp.route("/api/channels/<key>/curriculum/fill", methods=["POST"])
def fill(key):
    """Write subtopics for the next unfilled topic, or for several.

    One topic per call rather than the whole syllabus in one go: the
    response has to fit in a token budget, and generating only what is
    about to be used is what keeps a thousand-video plan cheap.

    `topic_id` fills one specific topic instead of the next unfilled one —
    what the create page uses when you pick a topic that has no subtopics
    written yet.
    """
    channel = channel_or_404(key)
    data = request.get_json(force=True, silent=True) or {}
    wanted = as_int(data.get("count"), 1, 1, 10)
    only = (data.get("topic_id") or "").strip()

    from pipeline.curriculum_gen import write_subtopics

    filled, added = [], 0
    for _ in range(wanted):
        topic = (curriculum.find_topic(key, only) if only
                 else curriculum.next_unfilled_topic(key))
        if topic is None or (only and topic.get("filled")):
            break
        try:
            subtopics = write_subtopics(channel, curriculum.load(key), topic)
        except PipelineError as exc:
            log.warning(f"{key}: subtopics for {topic['id']} failed: {exc}")
            # Partial success is still success: report what was written
            # rather than throwing away topics that worked.
            if filled:
                break
            return jsonify({"error": exc.user_message}), 502
        before = curriculum.progress(key)["total"]
        curriculum.add_subtopics(key, topic["id"], subtopics)
        added += curriculum.progress(key)["total"] - before
        filled.append(topic["title"])
        if only:
            break

    if not filled:
        return jsonify({"error": "Every topic already has its subtopics."}), 400
    return jsonify({"ok": True, "topics": filled, "subtopics_added": added,
                    "pending": curriculum.pending_count(key)})


@bp.route("/channels/<key>/curriculum/<subtopic_id>/skip", methods=["POST"])
def skip(key, subtopic_id):
    channel_or_404(key)
    try:
        curriculum.skip(key, subtopic_id, request.form.get("note", ""))
    except PipelineError:
        abort(404, description="That subtopic is no longer in the plan.")
    return redirect(url_for("curriculum.page", key=key) + f"#{subtopic_id}")


@bp.route("/channels/<key>/curriculum/<subtopic_id>/unskip", methods=["POST"])
def unskip(key, subtopic_id):
    channel_or_404(key)
    try:
        curriculum.unskip(key, subtopic_id)
    except PipelineError:
        abort(404, description="That subtopic is no longer in the plan.")
    return redirect(url_for("curriculum.page", key=key) + f"#{subtopic_id}")


@bp.route("/channels/<key>/curriculum/<subtopic_id>/next", methods=["POST"])
def make_next(key, subtopic_id):
    """Jump one subtopic to the front of the queue."""
    channel_or_404(key)
    try:
        curriculum.move_to_front(key, subtopic_id)
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
    """Channels close to running out of subtopics, for the home page.

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
