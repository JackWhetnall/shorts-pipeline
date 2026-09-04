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

from core import costs, gallery, job_context
from core.errors import ConfigError
from core.logging_setup import get_logger
from core.paths import PROJECT_ROOT, slugify, unique_stem
from pipeline import description, script_gen, similarity, tts
from pipeline.plan import RenderPlan, Seed
from pipeline.quote_source import get_quote

log = get_logger(__name__)


def fetch_seed(channel) -> Seed:
    """One candidate seed. No prompts, no side effects — safe to call
    repeatedly while someone rerolls."""
    if channel.content_mode == "static_corpus":
        quote = get_quote(channel.source)
        return Seed(type="quote", text=quote["text"], reference=quote["reference"])
    if channel.content_mode == "topic":
        return Seed(type="topic", topic=random.choice(channel.topics))
    raise ConfigError(
        f"unknown content_mode {channel.content_mode!r}",
        user_message=f'Channel "{channel.key}" has an unrecognised content mode.',
    )


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


def _finish(plan: RenderPlan, started_at: float) -> RenderPlan:
    """Metadata, description, the originality check, and the cost record."""
    job_context.report_stage(5)
    log.info("[5/5] Writing metadata...")
    description.write_meta(plan)
    description.write_description(plan)

    report = similarity.check(plan.channel.key, plan.script)
    if report.flagged:
        log.warning(f"  [similarity] {report.summary}")
    similarity.record(plan.channel.key, plan.stem, plan.script)
    plan.similarity = report

    # Seed the editable title and description. Stored on the video rather
    # than only in the meta file, so the review screen can show them,
    # let you edit them, and hand them to you to paste.
    gallery.save_title_and_description(
        plan.video_path,
        plan.script.title or plan.stem.replace("_", " ").title(),
        description.generate_description(plan.script, plan.channel.monetization,
                                         plan.channel.end_screen),
    )

    # The quality signals this render produced, kept beside the video.
    # They used to exist only as log lines inside a job record that gets
    # pruned after a week.
    gallery.save_report(plan.video_path, {
        "footage_repeated": plan.footage_repeated,
        "footage_degraded": plan.footage_degraded,
        "shot_count": len(plan.shots),
        "clips": sorted({s.clip_path.name for s in plan.shots if s.clip_path}),
        "similarity": {
            "flagged": report.flagged,
            "max_trigram": report.max_trigram,
            "max_cosine": report.max_cosine,
            "closest_title": report.closest_title,
        },
        "title_options": list(plan.script.title_options),
    })

    # What this specific video cost, saved beside it. A per-video number
    # at the moment you're looking at the video is what makes an
    # expensive step visible; a monthly invoice never is.
    summary = costs.summary_between(started_at, time.time(), plan.channel.key)
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

    job_context.set_channel_key(channel.key)
    started_at = time.time()
    plan = RenderPlan(channel=channel, seed=seed, interactive=interactive)

    _prepare_output(plan)
    script_gen.run(plan)
    tts.run(plan)
    assemble.run(plan)
    _finish(plan, started_at)

    log.info(f"Done: {plan.video_path}")
    return plan
