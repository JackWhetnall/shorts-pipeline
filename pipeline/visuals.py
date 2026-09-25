"""
The visuals stage: carry out the director's plan (pipeline.director).

After the voiceover (everything is timed to it) and the paintings
(pipeline.artwork, which keep their segments), before assembly. For each
segment the director didn't leave to footage, make its clip: a filled
template (pipeline.templates.fill), an illustration (pipeline.illustrate)
or, for geometry and plots only, a free-form diagram (pipeline.scenes).
Anything that fails falls back to footage and says so on the review
page; by now a script and a voiceover are paid for, and nothing here is
worth losing them over. Clips are checkpointed so a retry doesn't pay
twice. See decision 040.
"""

from __future__ import annotations

from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import channel_props_dir
from pipeline import director, illustrate
from pipeline.scenes import art, stage, writer
from pipeline.templates import fill

log = get_logger(__name__)


def run(plan):
    channel = plan.channel
    existing = list(getattr(plan, "scene_clips", None) or [])
    covered = {i for c in existing for i in range(c["first"], c["last"] + 1)}
    plan.scene_clips, plan.scenes_fell_back, plan.scene_notes = existing, 0, []
    plan.visual_plan = []
    share = int(channel.scenes.share or 0)
    if share <= 0:
        return plan

    restored = stage._restore()
    if restored is not None:
        plan.scene_clips, plan.scenes_fell_back, plan.scene_notes = restored
        log.info(f"  [visuals] reusing {len(plan.scene_clips)} clip(s) from the earlier attempt")
        return plan

    segments = plan.script.segments
    style = art.resolve(channel.scenes.art)
    props_dir = channel_props_dir(channel.key, style["key"])
    folder = plan.out_dir / f"{plan.stem}_scenes"
    log.info(f"[3/5] Directing the visuals ({style['label']})...")
    try:
        directions = director.direct(segments, plan.seed.title, share, covered)
    except PipelineError as exc:
        log.warning(f"  [visuals] couldn't direct ({exc}); footage throughout")
        plan.scene_notes.append("The visual plan failed, so this video is all footage.")
        plan.scenes_fell_back = 1
        stage._save(plan)
        return plan
    plan.visual_plan = directions

    narration = "\n".join(f"[{i}] {s.text}" for i, s in enumerate(segments))
    hook_end = stage._hook_end(plan)
    tail = channel.pacing.crossfade
    for d in directions:
        if d["medium"] == "footage":
            continue
        i = d["index"]
        segment = segments[i]
        words = writer.words_for(plan.voiceover.word_timings, segment.start, segment.end)
        not_before = hook_end if i == 0 else 0.0
        stem = folder / f"seg{i}_{d['medium']}"
        log.info(f"  [visuals] segment {i}: {d['medium']} "
                 f"{d.get('template') or ''} ({d.get('reason', '')[:60]})")
        try:
            clip, notes = _make(d, words, segment.duration, narration, style, props_dir, stem,
                                tail, not_before, hook_end, i)
        except Exception as exc:  # noqa: BLE001 - degrades to footage and is flagged, never silent
            if not isinstance(exc, PipelineError):
                log.exception(f"  [visuals] segment {i} failed unexpectedly")
            log.warning(f"  [visuals] segment {i} fell back to footage: {exc}")
            plan.scenes_fell_back += 1
            plan.scene_notes.append(f"Segment {i + 1}'s {d['medium']} couldn't be made; "
                                    f"it uses footage instead.")
            continue
        plan.scene_clips.append({"first": i, "last": i, "clip": str(clip), "kind": d["medium"]})
        plan.scene_clips.sort(key=lambda c: c["first"])
        plan.scene_notes.extend(f"Segment {i + 1}: {n}" for n in notes)

    stage._save(plan)
    return plan


def _make(d, words, duration, narration, style, props_dir, stem, tail, not_before, hook_end, i):
    medium = d["medium"]
    if medium == "template":
        return fill.make(d["template"], d["brief"], words, duration, narration, style, props_dir,
                         stem, tail, not_before)
    if medium == "illustration":
        return illustrate.make(d["brief"], style, duration + tail, stem), []
    if medium == "diagram":
        context = {"before": "", "after": "", "narration": narration,
                   "reserve": stage._reserve_note(hook_end, words) if i == 0 else ""}
        return stage._make(d["brief"], words, duration, style, props_dir, context, stem, tail,
                           [0], not_before)
    raise PipelineError(f"unknown medium {medium}", user_message="A visual couldn't be made.")
