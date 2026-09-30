"""
The animation stage: the segments the visual director gave to animation,
made into finished animated clips.

    budget   what this video may spend (channel `animation.budget`); the
             stretches it can't cover go back to the other media, noted
    bible    the channel's style frame and cast sheets (drawn on first need)
    board    the storyboard (pipeline.animation.storyboard)
    sheets   a reference picture of each character, place and object the
             film uses more than once (the cast's come from the bible)
    frames   keyframes, checked, failures redrawn once
    motion   shots, checked, failures made again once if affordable
    finish   retimed, drawn on the look's cadence, graded and cut together

Everything is written to the video's working folder as it's made and
reused on a retry, so an interrupted job never pays for a picture or a
shot twice. By now a script and a voiceover are paid for, so anything
that fails degrades (a shot the video model can't make is held as its
keyframe; a stretch that can't be animated falls back) and says so on the
video's report, never silently (CLAUDE.md, "Failure cost").
"""

from __future__ import annotations

import json
from pathlib import Path

from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline.animation import bible, finish, keyframes, models, motion, storyboard, style
from pipeline.animation.compositor import theme

log = get_logger(__name__)

# Keyframe checks, storyboard and the motion check, per video.
OVERHEAD_USD = 0.08


def runs(indices) -> list:
    """Contiguous runs of segment indices, as (first, last)."""
    out = []
    for i in sorted(set(indices)):
        if out and out[-1][1] == i - 1:
            out[-1] = (out[-1][0], i)
        else:
            out.append((i, i))
    return out


def affordable(ranges: list, segments: list, budget: float, video, image, quality: str,
               pace: int) -> tuple:
    """(ranges it can afford, ranges it can't). Segments are given back
    from the end until the rest fits: the opening is where animation
    earns the most, as the hook."""
    kept = [i for a, b in ranges for i in range(a, b + 1)]
    dropped = []
    while kept:
        seconds = sum(segments[i].duration for i in kept)
        est = models.estimate(seconds, models.mean_shot_seconds(pace), video, image, quality)
        if est.total + OVERHEAD_USD <= budget + 1e-6:
            break
        dropped.insert(0, kept.pop())
    return runs(kept), runs(dropped)


class Result:
    def __init__(self):
        self.clips = []                 # [{"first", "last", "clip", "kind"}]
        self.notes = []
        self.fell_back = []             # segment indices animation couldn't cover
        self.summary = {}
        self.board = {}
        self.frames = {}


def make(plan, indices: list, briefs: dict, folder: Path, tail: float,
         animate: bool = True) -> Result:
    """Animate the segments in `indices` (the director's choice); `briefs`
    are its per-segment notes. Clips go in `folder`; each is held `tail`
    seconds on its last frame for the crossfade into what follows.

    `animate=False` stops before the video model: every shot is its
    checked keyframe, held and pushed in, cut to the narration. That is
    an animatic, for judging a look and a storyboard for a few cents
    (tools/animate.py, the settings page's preview).

    The frame is the plan's (`plan.frame`: "vertical" for a short, "wide"
    for a widescreen video; decision 054), vertical when it has none."""
    result = Result()
    channel = plan.channel
    settings = channel.animation
    fmt, look = style.compile(settings, frame=getattr(plan, "frame", None))
    if style.composited(fmt):
        # Tabletop and canvas: drawn once, composited, costing cents; no
        # video model and nothing to hold back for the budget.
        from pipeline.animation import compose
        return compose.make(plan, runs(indices), folder, tail, look, fmt, result)
    video = models.video_model(settings.video_model)
    image = models.image_model(settings.image_model)
    quality = settings.quality if settings.quality in video.price else "standard"
    segments = plan.script.segments
    words = plan.voiceover.word_timings

    ranges, dropped = affordable(runs(indices), segments, float(settings.budget), video, image,
                                 quality, look["pace"])
    for a, b in dropped:
        result.fell_back += list(range(a, b + 1))
    if dropped:
        result.notes.append(
            f"The animation budget (${settings.budget:.2f}) didn't cover the last "
            f"{len(result.fell_back)} animated segment(s); they use other pictures.")
    if not ranges:
        return result

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    style_ref = bible.reference(channel, look)
    cast = bible.cast_members(channel)
    windows = storyboard.spans(segments, ranges, words)
    seconds = sum(w["end"] - w["start"] for w in windows)
    video_budget = max(0.0, float(settings.budget) - OVERHEAD_USD - models.estimate(
        seconds, models.mean_shot_seconds(look["pace"]), video, image, quality).image_usd)

    board = _board(plan, folder, ranges, windows, words, look, cast, briefs, video, quality,
                   video_budget, result, fmt)
    shots = board["shots"]

    sheets = _sheets(channel, board, look, style_ref, cast, folder / "elements")
    frames = _keyframes(shots, board, look, style_ref, sheets, folder, image, result)
    if animate:
        clips, held = _motion(shots, board, look, frames, video, quality, folder, video_budget,
                              result)
    else:
        clips, held = {}, 0

    # Finish each shot, then cut each stretch together.
    finished = {}
    for s in shots:
        is_last = s is shots[-1] or shots[s["index"] + 1]["window"] != s["window"]
        hold = tail if is_last else 0.0
        out = folder / "finished" / f"f_{s['index']:02d}.mp4"
        if s["index"] in clips:
            finished[s["index"]] = finish.finish_shot(clips[s["index"]], out, s["duration"],
                                                      look, hold)
        else:
            still = frames.get(s["index"]) or _nearest_frame(s, frames)
            if still is None:
                raise PipelineError(f"shot {s['index']} has neither a clip nor a frame",
                                    user_message="An animated shot couldn't be made.")
            finished[s["index"]] = finish.still_shot(still, out, s["duration"], look, hold)
    for w_index, (first, last) in enumerate(ranges):
        parts = [finished[s["index"]] for s in shots if s["window"] == w_index]
        if not parts:
            # A stretch with no words heard in it gets no shots; it falls back.
            result.fell_back += list(range(first, last + 1))
            continue
        clip = finish.join(parts, folder / f"animation_{first}_{last}.mp4")
        if fmt.get("captions"):
            clip = _captions(clip, [s for s in shots if s["window"] == w_index], windows[w_index],
                             fmt, look, folder)
        result.clips.append({"first": first, "last": last, "clip": str(clip),
                             "kind": "animation"})

    if held and animate:
        result.notes.append(f"{held} animated shot(s) couldn't be generated and are held "
                            f"as still frames instead.")
    result.summary = {"look": look["label"], "model": video.label, "quality": quality,
                      "shots": len(shots), "seconds": round(seconds, 1),
                      "generated": sum(s["generate"] for s in shots if s["index"] in clips),
                      "held": held, "concept": board.get("concept", "")}
    result.board, result.frames = board, frames
    return result


def _captions(clip, shots, window, fmt, look, folder) -> Path:
    """A paper theatre's names, dates and places, on the shots that carry
    them (drawn in the format's face, in the look's ink)."""
    from pipeline.animation.compositor import render as compositor

    labels = theme.theme(fmt, look)["labels"]
    captions = []
    for s in shots:
        if not s.get("caption"):
            continue
        png = compositor.caption_png(s["caption"], labels,
                                     folder / "captions" / f"c_{s['index']:02d}.png")
        start = s["start"] - window["start"] + 0.35
        captions.append((png, round(start, 3), round(max(start + 1.2, s["end"] - window["start"] - 0.25), 3)))
    if not captions:
        return clip
    return finish.overlay_captions(clip, captions, Path(clip).with_name(Path(clip).stem + "_c.mp4"))


def _board(plan, folder, ranges, windows, words, look, cast, briefs, video, quality,
           video_budget, result, fmt=None) -> dict:
    """The storyboard, from an earlier attempt when there is one for the
    same stretches (so its keyframes and shots still match it)."""
    path = folder / "storyboard.json"
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("ranges") == [list(r) for r in ranges]:
                log.info("  [animation] reusing the storyboard from the earlier attempt")
                return saved
        except (OSError, json.JSONDecodeError):
            pass
    limits = storyboard.shot_limits(sum(w["end"] - w["start"] for w in windows), look["pace"],
                                    video, video_budget, quality)
    hook_until = _hook_until(plan)
    raw = storyboard.write(plan.script.segments, words, windows,
                           subject=plan.seed.title if plan.seed else "",
                           look=look, cast=cast, avoid=list(plan.channel.avoid_imagery or []),
                           limits=limits, briefs=briefs, hook_until=hook_until,
                           fmt=fmt if fmt and fmt.get("guide") else None)
    board, notes = storyboard.settle(raw, windows, words, video, quality, video_budget, cast)
    for s in board["shots"]:
        if not s["image"].strip():
            segment = plan.script.segments[ranges[s["window"]][0]]
            s["image"] = briefs.get(ranges[s["window"]][0]) or segment.shot_brief or segment.text
            s["motion"] = s["motion"] or "A slow, gentle camera push-in."
    if notes:
        log.info(f"  [animation] storyboard settled: {'; '.join(notes)}")
    board["ranges"] = [list(r) for r in ranges]
    log.info(f"  [animation] {len(board['shots'])} shots: {board.get('concept', '')[:120]}")
    path.write_text(json.dumps(board, indent=1), encoding="utf-8")
    return board


def _hook_until(plan) -> float:
    try:
        from pipeline.scenes import stage as scene_stage
        return scene_stage._hook_end(plan)
    except Exception:  # noqa: BLE001 - only shapes the first shot's advice
        return 0.0


def _sheets(channel, board, look, style_ref, cast, folder) -> dict:
    """{element key: reference picture} for the cast in this film and
    for anything else it shows in more than one shot."""
    uses = {}
    for s in board["shots"]:
        for k in s["elements"]:
            uses[k] = uses.get(k, 0) + 1
    sheets = {}
    by_name = {storyboard._slug(c["name"]): c for c in cast}
    for key, element in board["elements"].items():
        if key not in uses:
            continue
        try:
            if element.get("cast") and key in by_name:
                sheets[key] = bible.cast_sheet(channel, look, by_name[key])
            elif uses[key] >= 2:
                sheets[key] = bible.element_sheet(
                    element["kind"], element["name"], element["description"], look, style_ref,
                    Path(folder) / f"{key}.png", models.image_model(channel.animation.image_model))
        except PipelineError as exc:
            # A missing sheet costs consistency, not the shot.
            log.warning(f"  [animation] no reference for {element['name']}: {exc}")
    return sheets


def _keyframes(shots, board, look, style_ref, sheets, folder, image, result) -> dict:
    frames = {}
    for s in shots:
        if s.get("continues"):
            continue
        try:
            frames[s["index"]] = keyframes.draw(s, board, look, style_ref, sheets, folder, image)
        except PipelineError as exc:
            log.warning(f"  [animation] keyframe {s['index']} failed: {exc}")
    if not frames:
        raise PipelineError("no keyframes could be drawn",
                            user_message="None of the animation's pictures could be drawn.")
    try:
        problems = keyframes.check(shots, frames, board, style_ref, sheets)
    except PipelineError as exc:
        log.warning(f"  [animation] couldn't check the keyframes ({exc}); using them unchecked")
        result.notes.append("The animation's first frames couldn't be checked.")
        problems = {}
    for index, found in problems.items():
        log.info(f"  [animation] redrawing keyframe {index}: {'; '.join(found)[:200]}")
        try:
            frames[index] = keyframes.draw(shots[index], board, look, style_ref, sheets,
                                           folder, image, fix=found)
        except PipelineError as exc:
            log.warning(f"  [animation] redraw of keyframe {index} failed: {exc}")
    if problems:
        try:
            still = keyframes.check([shots[i] for i in problems], frames, board, style_ref,
                                    sheets)
        except PipelineError:
            still = {}
        for index, found in still.items():
            result.notes.append(f"Animated shot {index + 1}'s first frame: {'; '.join(found)}")
    return frames


def _nearest_frame(shot, frames):
    """A continued take with no clip: the keyframe of the take it continues."""
    earlier = [i for i in frames if i < shot["index"]]
    return frames[max(earlier)] if earlier else None


def _motion(shots, board, look, frames, video, quality, folder, video_budget, result) -> tuple:
    """({shot index: generated clip}, how many shots are held as stills)."""
    from core import job_context

    spent = [0.0]
    clips = {}

    def chain(start: int) -> list:
        """A shot and the takes that continue it, in order."""
        out = [shots[start]]
        j = start + 1
        while j < len(shots) and shots[j].get("continues"):
            out.append(shots[j])
            j += 1
        return out

    def run_chain(members: list) -> dict:
        made = {}
        first = frames.get(members[0]["index"])
        for s in members:
            if first is None:
                break
            price = video.cost(s["generate"], quality)
            if spent[0] + price > video_budget + 0.01 and not motion.path_for(folder, s).exists():
                log.warning(f"  [animation] shot {s['index']}: over budget, held as a still")
                break
            try:
                clip = motion.animate(s, board, look, first, video, quality, folder)
            except PipelineError as exc:
                log.warning(f"  [animation] shot {s['index']} failed: {exc}")
                break
            spent[0] += price
            made[s["index"]] = clip
            _, used = models.fit(s["duration"], motion.length(clip))
            first = motion.last_frame(clip, folder / f"last_{s['index']:02d}.jpg", used)
        return made

    heads = [s["index"] for s in shots if not s.get("continues")]
    for made in job_context.parallel_map(lambda i: run_chain(chain(i)), heads, max_workers=4):
        clips.update(made)

    # Look at every shot; make the broken ones again while the budget allows.
    try:
        problems = motion.check(shots, clips, frames, folder)
    except PipelineError as exc:
        log.warning(f"  [animation] couldn't check the shots ({exc}); using them unchecked")
        result.notes.append("The animated shots couldn't be checked.")
        problems = {}
    for index, found in sorted(problems.items()):
        s = shots[index]
        first = frames.get(index) if not s.get("continues") else None
        price = video.cost(s["generate"], quality)
        if first is None or spent[0] + price > video_budget + 0.01:
            result.notes.append(f"Animated shot {index + 1}: {'; '.join(found)}")
            continue
        log.info(f"  [animation] making shot {index} again: {'; '.join(found)[:200]}")
        try:
            clips[index] = motion.animate(s, board, look, first, video, quality, folder,
                                          avoid=found)
            spent[0] += price
        except PipelineError as exc:
            log.warning(f"  [animation] second try at shot {index} failed: {exc}")
            result.notes.append(f"Animated shot {index + 1}: {'; '.join(found)}")
    held = len([s for s in shots if s["index"] not in clips])
    return clips, held
