"""
The pipeline stage: after the voiceover (the scenes are timed to it),
before assembly (which lays them in as shots).

For a channel with `scenes.share` above 0: plan which stretches of the
script become scenes, write each one, check it, repair it once if the
checks found problems, draw any props it needs, and render it. A scene
that still can't be made safely falls back to stock footage for its
segments, and says so on the video's report. By this stage a script and a
voiceover are paid for; nothing here is worth losing them over.

Rendered scenes are checkpointed, so a retried job doesn't pay for them
twice.
"""

from __future__ import annotations

import json
from pathlib import Path

from core import job_context
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import channel_props_dir
from pipeline.scenes import art, props, render, writer

log = get_logger(__name__)

MAX_NEW_PROPS_PER_VIDEO = 4


def run(plan):
    channel = plan.channel
    share = int(channel.scenes.share or 0)
    plan.scene_clips, plan.scenes_fell_back, plan.scene_notes = [], 0, []
    if share <= 0:
        return plan

    restored = _restore()
    if restored is not None:
        plan.scene_clips, plan.scenes_fell_back, plan.scene_notes = restored
        log.info(f"  [scene] reusing {len(plan.scene_clips)} rendered scene(s) from the earlier attempt")
        return plan

    segments = plan.script.segments
    style = art.resolve(channel.scenes.art)
    library = channel_props_dir(channel.key, style["key"])
    folder = plan.out_dir / f"{plan.stem}_scenes"
    log.info(f"[3/5] Planning animated scenes ({share}% of the video, {style['label']})...")

    try:
        stretches = writer.plan(segments, share, plan.seed.title)
    except PipelineError as exc:
        log.warning(f"  [scene] couldn't plan scenes ({exc}); using stock footage throughout.")
        plan.scene_notes.append("The scene plan failed, so this video is all stock footage.")
        plan.scenes_fell_back = 1
        _save(plan)
        return plan

    # Every scene sees the whole script: which number is which, and what
    # has been revealed by its turn. Written alone, the Pythagoras demo's
    # third scene put the 6 on the wall and gave the answer away early.
    narration = "\n".join(f"[{i}] {s.text}" for i, s in enumerate(segments))
    reserve = _opening_reserve(plan)
    new_props = [0]
    for i, stretch in enumerate(stretches):
        first, last = stretch["first"], stretch["last"]
        start, end = segments[first].start, segments[last].end
        words = writer.words_for(plan.voiceover.word_timings, start, end)
        context = {"before": stretches[i - 1]["idea"] if i else "",
                   "after": stretches[i + 1]["idea"] if i + 1 < len(stretches) else "",
                   "narration": narration,
                   "reserve": reserve if first == 0 else ""}
        log.info(f"  [scene] {i + 1}/{len(stretches)}: segments {first}-{last}, "
                 f"{end - start:.1f}s: {stretch['idea'][:80]}")
        try:
            clip, notes = _make(stretch["idea"], words, end - start, style, library, context,
                                folder / f"scene_{i + 1}", plan.channel.pacing.crossfade, new_props)
        except Exception as exc:  # noqa: BLE001 - degrades to stock and is flagged, never silent
            if not isinstance(exc, PipelineError):
                log.exception(f"  [scene] scene {i + 1} failed unexpectedly")
            log.warning(f"  [scene] scene {i + 1} fell back to stock footage: {exc}")
            plan.scenes_fell_back += 1
            plan.scene_notes.append(f"Scene {i + 1} ({stretch['idea'][:60]}) couldn't be made "
                                    f"and was replaced by stock footage.")
            continue
        plan.scene_clips.append({"first": first, "last": last, "clip": str(clip)})
        plan.scene_notes.extend(f"Scene {i + 1}: {n}" for n in notes)

    _save(plan)
    return plan


def _make(idea, words, duration, style, library, context, stem: Path, tail: float, new_props):
    """One scene, written, checked, repaired once if needed, and rendered.
    Returns (clip path, notes about anything that remained imperfect)."""
    existing = sorted(p.stem.replace("_", " ") for p in library.glob("*.png"))
    raw = writer.write(idea, words, duration, style, existing, **context)
    scene, problems, assets = _check(raw, words, duration, style, library, new_props, look=True)
    if problems:
        log.info(f"  [scene] repairing: {'; '.join(problems)[:300]}")
        raw = writer.write(idea, words, duration, style, existing, previous=raw,
                           problems=problems, **context)
        scene, problems, assets = _check(raw, words, duration, style, library, new_props)
    if scene is None:
        raise PipelineError("; ".join(problems), user_message="An animated scene couldn't be made.")

    # Held on its last picture for the crossfade into whatever follows.
    scene["duration"] = round(duration + tail, 3)
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".json").write_text(json.dumps(scene, indent=1), encoding="utf-8")
    clip = render.render(scene, style, assets, stem.with_suffix(".mp4"))
    return clip, problems          # what's left is layout only: cosmetic, and noted


def _check(raw, words, duration, style, library, new_props, look: bool = False):
    """(scene or None, problems, assets). None means it can't be rendered
    as is; problems alone (with a scene) are layout imperfections.

    `look` also has a vision model look at stills of the scene: on the
    first pass only, since its findings go into the one repair round."""
    scene, problems = writer.validate(raw, words, duration)
    if problems:
        return None, problems, {}
    assets = {}
    for key, spec in scene["props"].items():
        path = library / f"{props.slug(spec.get('name') or key)}.png"
        if not path.exists():
            if new_props[0] >= MAX_NEW_PROPS_PER_VIDEO:
                return None, [f"The scene needs a new prop ({spec.get('name')}), but this video has "
                              f"already drawn {MAX_NEW_PROPS_PER_VIDEO}. Use shapes, or a prop "
                              f"from the library."], {}
            new_props[0] += 1
        assets[key] = props.get(library, spec.get("name") or key, style["prop_style"],
                                spec.get("detail") or "", icons=_icons(style))
    stills = _still_times(duration) if look else ()
    boxes, images = render.layout(scene, style, assets, stills=stills)
    problems = writer.layout_problems(boxes) + writer.too_small(boxes)
    if look:
        spoken = [" ".join(w for w, t in words if t <= at)[-160:] for at in stills]
        problems += writer.picture_problems(images, spoken, " ".join(w for w, _ in words))
    return scene, problems, assets


def _still_times(duration: float) -> tuple:
    """Halfway through, and once everything has arrived."""
    return (round(duration * 0.5, 2), round(max(0.0, duration - 0.1), 2))


def _opening_reserve(plan) -> str:
    """The on-screen hook covers the top of the frame for the video's first
    seconds; a scene there must leave that band clear until it has gone."""
    from pipeline import assemble

    if not (getattr(plan.channel.style, "screen_hook_enabled", True)
            and getattr(plan.script, "screen_hook", "")):
        return ""
    _, end = assemble.screen_hook_window(plan.voiceover.word_timings)
    top = assemble.SCREEN_HOOK_Y - 240
    return (f"The video's opening text covers y {top}-{assemble.SCREEN_HOOK_Y + 240} "
            f"until {end:.1f}s. Put nothing in that band before then: start the picture "
            f"lower, or bring things in there after {end:.1f}s.")


def _icons(style: dict) -> dict:
    """The art direction's free prop library, with its tint as a colour."""
    icons = dict(style.get("prop_library") or {})
    if icons.get("tint"):
        icons["tint"] = style["colors"].get(icons["tint"], icons["tint"])
    return icons


def _save(plan) -> None:
    try:
        job_context.save_json_checkpoint("scenes", {
            "clips": plan.scene_clips, "fell_back": plan.scenes_fell_back,
            "notes": plan.scene_notes})
    except Exception:  # noqa: BLE001 - checkpointing is best-effort
        pass


def _restore():
    data = job_context.load_json_checkpoint("scenes")
    if not data or not all(Path(c["clip"]).exists() for c in data.get("clips") or []):
        return None
    return data.get("clips") or [], data.get("fell_back", 0), data.get("notes") or []
