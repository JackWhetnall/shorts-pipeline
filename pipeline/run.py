"""
The pipeline itself: seed in, finished video out.

Every stage is `fn(plan) -> plan`, so this module is a list of stages
rather than a function that threads thirteen arguments through five
signatures. Adding a stage — a music bed, a thumbnail, an upload — is a
function and a line here.

Seed selection is separate from generation on purpose. `fetch_seed` makes
no decisions and asks nothing, so the web app can drive accept/reroll from
buttons and the CLI can wrap it in a prompt loop, without either one
reimplementing what the other does.
"""

from __future__ import annotations

import random
from datetime import date
from pathlib import Path

import time

from core import costs, curriculum, gallery, job_context, publish_gate
from core.errors import ConfigError
from core.logging_setup import get_logger
from core.paths import PROJECT_ROOT, slugify, unique_stem
from pipeline import description, editor_check, script_gen, similarity, tts
from pipeline.plan import RenderPlan, Seed
from pipeline.quote_source import get_quote

log = get_logger(__name__)


def fetch_seed(channel, pick: dict = None) -> Seed:
    """One candidate seed. No prompts, no side effects — safe to call
    repeatedly while someone rerolls.

    `pick` narrows which subtopic a planned channel offers:
    `{"topic_id": ...}` to stay inside one topic, `{"subtopic_id": ...}`
    for a specific one, `{"mode": "random"}` to shuffle rather than take
    the next in order. Absent, it is the next one in syllabus order — the
    "just make me the next video" case, which is the common one.
    """
    if channel.content_mode == "static_corpus":
        quote = get_quote(channel)
        return Seed(type="quote", text=quote["text"], reference=quote["reference"])
    if channel.content_mode == "topic":
        # A syllabus, when the channel has one, is the whole point:
        # subtopics in a deliberate order, each used once. Channels without
        # one keep drawing from their flat list exactly as before.
        if curriculum.exists(channel.key):
            entry = _pick_subtopic(channel, pick)
            if entry is None:
                raise ConfigError(
                    f"{channel.key} has a curriculum with nothing pending",
                    user_message=(
                        f'"{channel.channel_display_name or channel.key}" has used '
                        f"every subtopic available. Write more on its topic plan, "
                        f"or un-skip some."),
                )
            return Seed(type="topic", topic=entry["title"], topic_id=entry["id"])
        if not channel.topics:
            raise ConfigError(
                f"{channel.key} generates from topics but has neither a "
                f"curriculum nor a topic list",
                user_message=(
                    f'"{channel.channel_display_name or channel.key}" has no '
                    f"topics yet. Make a topic plan, or add some in its "
                    f"settings."),
            )
        return Seed(type="topic", topic=random.choice(channel.topics))
    raise ConfigError(
        f"unknown content_mode {channel.content_mode!r}",
        user_message=f'Channel "{channel.key}" has an unrecognised content mode.',
    )


def _pick_subtopic(channel, pick: dict = None):
    """Which subtopic this video should be about.

    Order of preference: an explicitly named one, then the next pending
    inside a named topic, then a random pending one, then whatever the
    channel's own ordering policy (core.ordering) says is next overall.
    A named subtopic that has already been used falls through to the
    rest rather than failing — the plan page and this page can be open
    at once, and a stale id should not be an error.
    """
    pick = pick or {}
    subtopic_id = (pick.get("subtopic_id") or "").strip()
    topic_id = (pick.get("topic_id") or "").strip()

    if subtopic_id:
        entry = curriculum.find(channel.key, subtopic_id)
        if entry and entry["status"] == curriculum.PENDING:
            return entry

    if pick.get("mode") == "random":
        candidates = curriculum.subtopics(
            channel.key, status=curriculum.PENDING, topic_id=topic_id or None)
        if candidates:
            return random.choice(candidates)

    if topic_id:
        entry = curriculum.next_pending(channel.key, topic_id=topic_id)
        if entry:
            return entry

    from core import ordering
    return ordering.choose_next_subtopic(channel)


def _prepare_output(plan: RenderPlan) -> RenderPlan:
    """Decide where this video lands, reusing an interrupted attempt's
    location when there is one.

    The paths are checkpointed with the script rather than recomputed:
    a freshly derived stem after an interruption would orphan the audio
    and video files the earlier attempt had already written.
    """
    progress = job_context.load_json_checkpoint("progress")
    if progress:
        plan.out_dir = Path(progress["out_dir"])
        plan.stem = progress["stem"]
        plan.out_dir.mkdir(parents=True, exist_ok=True)
        return plan

    plan.out_dir = PROJECT_ROOT / plan.channel.output_dir / date.today().isoformat()
    plan.out_dir.mkdir(parents=True, exist_ok=True)
    # A readable slug, not a hash — filenames alone should say what's in
    # each video and make a repeat visible at a glance.
    plan.stem = unique_stem(plan.out_dir, slugify(plan.seed.title, fallback="video"))

    try:
        job_context.save_json_checkpoint(
            "progress", {"out_dir": str(plan.out_dir), "stem": plan.stem})
    except Exception:  # noqa: BLE001 - checkpointing is best-effort
        pass
    return plan


def _video_cost(started_at: float, channel_key: str) -> dict:
    """What this video cost.

    By job id when there is one. A time window also caught anything the
    UI spent on the same channel meanwhile (a script preview, style
    candidates), and missed an interrupted first attempt's spend, which a
    retry reuses the id of and is genuinely part of this video's cost. A
    plain CLI run has no job, so it falls back to the window.
    """
    job_id = job_context.get_job_id()
    if job_id:
        return costs.summary_for_job(job_id)
    return costs.summary_between(started_at, time.time(), channel_key)


def _with_credits(text: str, credits: list) -> str:
    """Public-domain art needs no credit, but gives one: it's the right
    thing to do, and it shows the work is curated rather than scraped."""
    return f"{text.rstrip()}\n\n" + "\n".join(credits) if credits else text


def _run_checks(plan: RenderPlan) -> dict:
    """The automatic script and picture checks (pipeline.editor_check).
    Each reports whether it ran; neither raises for a service problem."""
    log.info("      Checking the script and the picture...")
    return {
        "script": editor_check.check_script(plan.script, plan.channel).to_jsonable(),
        "frames": editor_check.check_frames(plan.video_path, plan).to_jsonable(),
    }


def _finish(plan: RenderPlan, started_at: float) -> RenderPlan:
    """Metadata, description, the originality check, and the cost record."""
    job_context.report_stage(5)
    log.info("[5/5] Writing metadata...")
    description.write_meta(plan)
    description.write_description(plan)

    # Which video this topic became, so discarding it can hand the topic
    # back and publishing can mark it covered.
    if plan.seed.topic_id:
        try:
            curriculum.attach_video(plan.channel.key, plan.seed.topic_id, plan.stem)
        except Exception:  # noqa: BLE001 - bookkeeping never fails a finished video
            log.exception("Could not link this video to its curriculum topic")

    # Checked (and, if needed, rewritten) before the voiceover by the
    # script stage. A resumed job that reloaded its script from a
    # checkpoint skipped that, so it's checked here instead.
    report = plan.similarity or similarity.check(plan.channel.key, plan.script)
    if report.flagged:
        log.warning(f"  [similarity] {report.summary}")
    similarity.record(plan.channel.key, plan.stem, plan.script, video_path=plan.video_path)
    plan.similarity = report

    # Seed the editable title and description. Stored on the video rather
    # than only in the meta file, so the review screen can show them,
    # let you edit them, and hand them to you to paste.
    gallery.save_title_and_description(
        plan.video_path,
        plan.script.title or plan.stem.replace("_", " ").title(),
        _with_credits(description.generate_description(plan.script, plan.channel.monetization,
                                                       plan.channel.end_screen),
                      getattr(plan, "art_credits", [])),
    )

    # The quality signals this render produced, kept beside the video.
    # They used to exist only as log lines inside a job record that gets
    # pruned after a week.
    render_report = {
        "footage_repeated": plan.footage_repeated,
        "footage_degraded": plan.footage_degraded,
        "footage_unconfident": plan.footage_unconfident,
        "script_suspect": plan.script_suspect,
        # Quiz questions the fact check still didn't pass (pipeline.quiz).
        "quiz_unverified": list((plan.script.quiz or {}).get("unverified") or []),
        "shot_count": len(plan.shots),
        "video_seconds": round(getattr(plan, "video_seconds", 0.0) or 0.0, 1),
        "clips": sorted({s.clip_path.name for s in plan.shots if s.clip_path and not s.scene}),
        "scenes": len([c for c in plan.scene_clips if c.get("kind") != "artwork"]),
        "visuals": [{k: d.get(k) for k in ("index", "medium", "template", "reason")}
                    for d in getattr(plan, "visual_plan", []) or []],
        "artwork": list(getattr(plan, "art_credits", [])),
        "scenes_fell_back": plan.scenes_fell_back,
        "scene_notes": list(plan.scene_notes),
        "similarity": {
            "flagged": report.flagged,
            "max_trigram": report.max_trigram,
            "max_cosine": report.max_cosine,
            "closest_title": report.closest_title,
        },
        "title_options": list(plan.script.title_options),
        "checks": _run_checks(plan),
    }
    # Whether this could go out without a person looking at it. Decided
    # here for every video, not only on channels that publish themselves,
    # so the review queue shows how the gate would have called it.
    render_report["gate"] = publish_gate.evaluate(render_report)
    plan.gate = render_report["gate"]
    gallery.save_report(plan.video_path, render_report)

    # What this specific video cost, saved beside it. A per-video number
    # at the moment you're looking at the video is what makes an
    # expensive step visible; a monthly invoice never is.
    summary = _video_cost(started_at, plan.channel.key)
    gallery.save_cost_summary(plan.video_path, summary)
    log.info(f"      Cost: {costs.format_usd(summary['total_usd'])} "
             f"across {summary['calls']} API call(s).")

    if plan.footage_degraded:
        log.warning("  [video] footage was chosen without scoring (the matching step "
                    "failed). Worth watching closely before publishing.")
    if plan.footage_repeated:
        log.warning("  [video] this video reuses a clip — the library ran out of "
                    "distinct matches. Worth reviewing before publishing.")
    return plan


def _claim_topic(channel, seed: Seed) -> Seed:
    """Take this video's topic out of the pending queue.

    Claimed here rather than in `fetch_seed`, which is explicitly free of
    side effects so a seed can be rerolled. Here is the first moment a
    video is definitely being made.

    Queueing several videos at once captures the same "next" topic in each
    seed, so a claim that finds its topic already taken moves to the next
    pending one — five queued videos become five different videos rather
    than the same one five times.

    Best-effort: a syllabus that cannot be written must not lose a video
    that is otherwise ready to make.
    """
    if seed.type != "topic" or not curriculum.exists(channel.key):
        return seed
    try:
        claimed = curriculum.claim(channel.key, seed.topic_id)
    except Exception:  # noqa: BLE001 - bookkeeping never blocks a render
        log.exception(f"{channel.key}: could not claim a curriculum topic")
        return seed
    if claimed is None:
        return seed
    if claimed["id"] != seed.topic_id:
        log.info(f"{channel.key}: topic {seed.topic_id or '(none)'} was already "
                 f"taken; using {claimed['id']} instead")
    return Seed(type="topic", topic=claimed["title"], topic_id=claimed["id"])


def generate(channel, seed: Seed, interactive: bool = True) -> RenderPlan:
    """Run the whole pipeline for one video and return the finished plan.

    The plan carries everything the caller might want afterwards — output
    paths, the script, whether footage repeated, the originality report —
    so nothing has to be recomputed or passed back separately.
    """
    # Imported here rather than at module scope: assemble pulls in moviepy
    # and Pillow, which are slow to import and not needed by anything that
    # only wants fetch_seed.
    from pipeline import assemble
    from pipeline import visuals

    job_context.set_channel_key(channel.key)
    started_at = time.time()
    seed = _claim_topic(channel, seed)
    plan = RenderPlan(channel=channel, seed=seed, interactive=interactive)

    try:
        _prepare_output(plan)
        script_gen.run(plan)
        tts.run(plan)
        visuals.run(plan)
        assemble.run(plan)
        _finish(plan, started_at)
    except Exception:
        # A claimed subtopic that never became a video (the common case:
        # the run failed before there was anything to discard) must not
        # sit "used" forever with no video and no way back to pending.
        if seed.type == "topic" and seed.topic_id:
            try:
                curriculum.release_unattached(channel.key, seed.topic_id)
            except Exception:  # noqa: BLE001 - the real failure matters more
                log.debug("Could not release the claimed topic after a "
                          "failed generation", exc_info=True)
        raise

    log.info(f"Done: {plan.video_path}")
    return plan
