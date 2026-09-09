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


@bp.route("/channels/<key>/curriculum/<topic_id>/scripts")
def scripts_page(key, topic_id):
    channel = channel_or_404(key)
    topic = curriculum.find_topic(key, topic_id)
    if topic is None:
        abort(404, description="That topic is no longer in the plan.")
    subs = curriculum.subtopics(key, topic_id=topic_id)

    from pipeline.script_gen import MAX_SCRIPTS_PER_CALL

    pending_without_script = [s for s in subs
                              if s["status"] == curriculum.PENDING and not s.get("script")]
    return render_template(
        "curriculum_scripts.html", key=key, channel=channel, topic=topic,
        subtopics=subs, pending_without_script=len(pending_without_script),
        max_per_call=MAX_SCRIPTS_PER_CALL,
    )


@bp.route("/api/channels/<key>/curriculum/<topic_id>/write-scripts", methods=["POST"])
def write_scripts(key, topic_id):
    """Batch-write scripts for this topic's pending, scriptless
    subtopics — chunked the same way `fill` chunks subtopic generation,
    since a single call has a bounded size (see
    `pipeline.script_gen.MAX_SCRIPTS_PER_CALL`)."""
    channel = channel_or_404(key)
    topic = curriculum.find_topic(key, topic_id)
    if topic is None:
        abort(404, description="That topic is no longer in the plan.")

    from pipeline.script_gen import MAX_SCRIPTS_PER_CALL
    from pipeline.script_gen import write_scripts as write_scripts_batch

    todo = [s for s in curriculum.subtopics(key, topic_id=topic_id)
           if s["status"] == curriculum.PENDING and not s.get("script")]
    if not todo:
        return jsonify({"error": "Every pending subtopic in this topic "
                                 "already has a script."}), 400

    scripted = []
    for start in range(0, len(todo), MAX_SCRIPTS_PER_CALL):
        chunk = todo[start:start + MAX_SCRIPTS_PER_CALL]
        try:
            written = write_scripts_batch(channel, topic, chunk)
        except PipelineError as exc:
            log.warning(f"{key}/{topic_id}: script batch failed: {exc}")
            if scripted:
                break
            return jsonify({"error": exc.user_message}), 502
        for row in written:
            curriculum.set_script(key, row["subtopic_id"], row["script"])
            scripted.append(row["subtopic_id"])

    return jsonify({"ok": True, "scripted": scripted})


@bp.route("/api/channels/<key>/curriculum/<subtopic_id>/regenerate-script",
         methods=["POST"])
def regenerate_script(key, subtopic_id):
    channel = channel_or_404(key)
    subtopic = curriculum.find(key, subtopic_id)
    if subtopic is None:
        abort(404, description="That subtopic is no longer in the plan.")
    topic = curriculum.find_topic(key, subtopic["topic"])
    if topic is None:
        abort(404, description="That topic is no longer in the plan.")

    data = request.get_json(force=True, silent=True) or {}
    instruction = (data.get("instruction") or "").strip()

    siblings = [s for s in curriculum.subtopics(key, topic_id=topic["id"])
               if s["id"] != subtopic_id and s.get("script")]

    from pipeline.script_gen import regenerate_script as regenerate

    try:
        script = regenerate(channel, topic, subtopic, siblings, instruction)
    except PipelineError as exc:
        log.warning(f"{key}/{subtopic_id}: script regenerate failed: {exc}")
        return jsonify({"error": exc.user_message}), 502

    curriculum.set_script(key, subtopic_id, script)
    return jsonify({"ok": True, "script": script})


@bp.route("/channels/<key>/curriculum/<subtopic_id>/edit-script", methods=["POST"])
def edit_script(key, subtopic_id):
    """A hand-written or hand-fixed script, saved verbatim — the third
    way a script gets written, alongside the batch writer and
    regenerate. Segments arrive as parallel form-field lists (one entry
    per segment) since HTML forms have no native array-of-objects."""
    channel_or_404(key)
    subtopic = curriculum.find(key, subtopic_id)
    if subtopic is None:
        abort(404, description="That subtopic is no longer in the plan.")

    texts = request.form.getlist("segment_text")
    briefs = request.form.getlist("segment_shot_brief")
    keyword_lines = request.form.getlist("segment_keywords")
    segments = [
        {"text": text.strip(), "shot_brief": brief.strip(),
         "keywords": [k.strip().lower() for k in keywords.split(",") if k.strip()],
         "start": 0.0, "end": 0.0}
        for text, brief, keywords in zip(texts, briefs, keyword_lines)
        if text.strip()
    ]
    if not segments:
        return redirect(url_for("curriculum.scripts_page", key=key,
                                topic_id=subtopic["topic"]) + f"#{subtopic_id}")

    title_options = [t.strip() for t in request.form.get("title_options", "")
                     .split("\n") if t.strip()]
    script = {
        "citation": None,
        "segments": segments,
        "title_options": title_options,
        "description_body": request.form.get("description_body", "").strip(),
    }
    curriculum.set_script(key, subtopic_id, script)
    return redirect(url_for("curriculum.scripts_page", key=key,
                            topic_id=subtopic["topic"]) + f"#{subtopic_id}")


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
