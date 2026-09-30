"""
Composited formats (tabletop, canvas) made into finished clips
(decision 052).

    beats    the storyboard as beats (pipeline.animation.beats)
    kit      the objects it uses, drawn only if the channel hasn't got them
    stage    the surface or canvas, the narrator, the layouts, the timing
             (compositor.script)
    render   filmed in Chrome (compositor.render)
    finish   the look's grade and grain, as for generated shots

A video costs its storyboard call and whatever objects are new; a
channel's second video on a subject usually costs the storyboard alone.
Written to the working folder as it goes, and reused on a retry.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline.animation import beats as beat_board, finish, formats, kit, models, storyboard
from pipeline.animation.compositor import render, script

log = get_logger(__name__)


def make(plan, ranges: list, folder: Path, tail: float, look: dict, fmt: dict, result):
    """Fills `result` (a stage.Result) with one clip per animated range."""
    channel = plan.channel
    segments = plan.script.segments
    words = plan.voiceover.word_timings
    windows = storyboard.spans(segments, ranges, words)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)

    board = _board(plan, folder, ranges, windows, words, look, fmt)
    for b in board["beats"]:                  # each object once a beat, even in an older board
        if b["layout"] == "travel":
            for position, it in enumerate(b["items"][1:3], start=1):
                it.setdefault("place", "start" if position == 1 else "end")
        seen = set()
        b["items"] = [it for it in b["items"] if not (it["key"] in seen or seen.add(it["key"]))]
    pictures = kit.objects(channel, look, fmt, board["kit"])
    missing = set(board["kit"]) - set(pictures)
    if missing:
        result.notes.append(f"{len(missing)} object(s) couldn't be drawn and were left out.")
        for b in board["beats"]:
            b["items"] = [it for it in b["items"] if it["key"] in pictures]
            b["layout"] = beat_board._fitting(b["layout"], b["items"])

    style = formats.style_for(fmt, look)
    assets = dict(pictures)
    if fmt.get("continuity") == "move":
        assets["surface"] = kit.surface(channel, look, fmt)
        style["surface"] = {"image": "surface"}
    if fmt.get("avatar"):
        try:
            poses = kit.narrator(channel, look, fmt)
            for name, path in poses.items():
                assets[f"narrator_{name}"] = path
            style["avatar"] = {"poses": {name: f"narrator_{name}" for name in poses},
                               "x": 300, "y": 1270, "h": 900}
        except PipelineError as exc:
            log.warning(f"  [animation] no narrator ({exc}); presenter beats become statements")
            result.notes.append("The narrator couldn't be drawn, so it doesn't appear.")
            for b in board["beats"]:
                if b["layout"] == "presenter":
                    b["layout"] = "hero" if b["items"] else "statement"
    aspects = kit.aspects(pictures)

    for w_index, (first, last) in enumerate(ranges):
        window = windows[w_index]
        mine = [b for b in board["beats"] if b["window"] == w_index]
        if not mine:
            result.fell_back += list(range(first, last + 1))
            continue
        duration = window["end"] - window["start"] + tail
        stage_data = script.build(mine, words, window["start"], duration, aspects, fmt, style)
        (folder / f"stage_{first}_{last}.json").write_text(json.dumps(stage_data, indent=1),
                                                            encoding="utf-8")
        raw = render.render(stage_data, assets, folder / f"stage_{first}_{last}.mp4")
        clip = finish.grade(raw, folder / f"animation_{first}_{last}.mp4", look)
        result.clips.append({"first": first, "last": last, "clip": str(clip),
                             "kind": "animation"})

    result.summary = {"format": fmt["label"], "look": look["label"], "model": "compositor",
                      "beats": len(board["beats"]), "objects": len(pictures),
                      "seconds": round(sum(w["end"] - w["start"] for w in windows), 1),
                      "concept": board.get("concept", "")}
    result.board = board
    return result


def _board(plan, folder, ranges, windows, words, look, fmt) -> dict:
    path = folder / "beats.json"
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("ranges") == [list(r) for r in ranges] and saved.get("format") == fmt["key"]:
                log.info("  [animation] reusing the beats from the earlier attempt")
                return saved
        except (OSError, json.JSONDecodeError):
            pass
    existing = kit.index(plan.channel.key, look, kit._view(fmt))
    raw = beat_board.write(plan.script.segments, words, windows,
                           subject=plan.seed.title if plan.seed else "", fmt=fmt, look=look,
                           existing=existing, avoid=list(plan.channel.avoid_imagery or []),
                           mean=models.mean_shot_seconds(plan.channel.animation.pace))
    beats, kit_needed, notes = beat_board.settle(raw, windows, words, fmt)
    if notes:
        log.info(f"  [animation] beats settled: {'; '.join(notes)}")
    # An object already in the kit keeps its own name and look.
    for key in kit_needed:
        if key in existing:
            kit_needed[key] = {"name": existing[key]["name"],
                               "description": existing[key].get("description", "")}
    board = {"format": fmt["key"], "concept": raw.get("concept") or "", "beats": beats,
             "kit": kit_needed, "ranges": [list(r) for r in ranges]}
    log.info(f"  [animation] {len(beats)} beats, {len(kit_needed)} objects: "
             f"{board['concept'][:120]}")
    path.write_text(json.dumps(board, indent=1), encoding="utf-8")
    return board
