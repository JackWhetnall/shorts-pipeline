"""
Several shots from one still (decision 086).

A picture held for fifteen seconds with a slow push reads as a slideshow;
the first Lincoln film held each for 14.8 seconds on average. An editor
with one photograph cuts between the whole of it, the face, and a telling
detail. This does the same: a vision model looks at the stills, a batch
at a time, and names up to two framings worth cutting to in each (where
and how close); a scene longer than SHOT_SECONDS is cut into that many
shots, each with its own camera move. Pictures change about every five
seconds without drawing a single extra one.

The framings are kept beside the production (shots.json), keyed by each
still's name and modification time, so a film made again doesn't pay to
look again, and a redrawn still is looked at afresh. If the look fails,
a scene keeps one shot, as before, and the video says so.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline.llm import call_json

log = get_logger(__name__)

MODEL = "claude-haiku-4-5"
GROUP = 8
SHOT_SECONDS = 5.5              # a scene is cut about this often
MIN_SHOT = 2.6                  # but never into shots shorter than this
MAX_SHOTS = 3
MIN_ZOOM, MAX_ZOOM = 1.35, 2.2  # a crop between ~74% and ~45% of the picture's width
CHECK_SIZE = (512, 288)
DEFAULT_FRAMING = [0.15, 0.12, 0.7, 0.7]   # the middle, a little above centre, ~1.4x closer
RETRY_AFTER = 20                # seconds before a failed batch is asked again, once
HOLD_MAX = 9.0                  # no picture held longer than this (core.scorecard's limit)

SYSTEM = """
You are a documentary editor cutting a film from still pictures. For each
picture, name up to two framings worth cutting to after showing the whole
of it: the main subject's face or action, a telling detail, a second
person. Each is `x` and `y` (the framing's centre, as fractions of the
picture's width and height from the top left) and `zoom` (1.35 to 2.2:
how much closer than the whole picture). Keep a face's eyes in the upper
part of the framing; never frame empty sky or floor. If nothing is worth
a closer look, give none.
""".strip()


def schema() -> dict:
    framing = {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"},
                                                "zoom": {"type": "number"}},
               "required": ["x", "y", "zoom"], "additionalProperties": False}
    row = {"type": "object", "properties": {"picture": {"type": "integer"},
                                            "framings": {"type": "array", "items": framing}},
           "required": ["picture", "framings"], "additionalProperties": False}
    return {"type": "object", "properties": {"pictures": {"type": "array", "items": row}},
            "required": ["pictures"], "additionalProperties": False}


def box(x: float, y: float, zoom: float) -> list:
    """[left, top, width, height] as fractions, the picture's own shape,
    kept inside it."""
    zoom = max(MIN_ZOOM, min(MAX_ZOOM, float(zoom)))
    size = 1 / zoom
    left = min(max(float(x) - size / 2, 0.0), 1 - size)
    top = min(max(float(y) - size / 2, 0.0), 1 - size)
    return [round(left, 4), round(top, 4), round(size, 4), round(size, 4)]


def count(seconds: float, framings: int) -> int:
    """How many shots a scene of `seconds` is cut into."""
    wanted = max(1, round(seconds / SHOT_SECONDS))
    wanted = min(wanted, int(seconds // MIN_SHOT) or 1, MAX_SHOTS, framings + 1)
    return max(1, wanted)


def _key(path: Path) -> str:
    path = Path(path)
    return f"{path.name}:{int(path.stat().st_mtime)}"


def plan(stills: dict, cache_path: Path) -> tuple:
    """({scene index: [box, ...]}, problem or ""): framings for each still
    in `stills` ({index: path}), looked at only where not already known."""
    from pipeline.animation import keyframes
    cache_path = Path(cache_path)
    try:
        known = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        known = {}
    todo = [(i, p) for i, p in sorted(stills.items()) if _key(p) not in known]
    problem = ""
    for start in range(0, len(todo), GROUP):
        group = todo[start:start + GROUP]
        content = []
        for n, (i, p) in enumerate(group, start=1):
            media, data = keyframes.thumbnail(p, CHECK_SIZE)
            content += [{"type": "text", "text": f"Picture {n}:"},
                        {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}]
        content.append({"type": "text", "text": "Give the framings for each picture, by its number."})
        try:
            try:
                answer = call_json(SYSTEM, content, schema(), operation="documentary_shots", model=MODEL,
                                   max_tokens=2500, effort=None)
            except PipelineError:
                # Busy for a moment (the first real film lost 4 of 8 batches
                # this way, and the same calls went through a minute later).
                import time
                time.sleep(RETRY_AFTER)
                answer = call_json(SYSTEM, content, schema(), operation="documentary_shots", model=MODEL,
                                   max_tokens=2500, effort=None)
        except PipelineError as exc:
            problem = f"Shots couldn't be planned for some scenes ({exc.user_message}); they hold one shot."
            log.warning(f"  [documentary] {problem}")
            continue
        found = {r.get("picture"): r.get("framings") or [] for r in answer.get("pictures") or []}
        for n, (i, p) in enumerate(group, start=1):
            known[_key(p)] = [box(f["x"], f["y"], f["zoom"]) for f in found.get(n, [])[:MAX_SHOTS - 1]
                              if all(isinstance(f.get(k), (int, float)) for k in ("x", "y", "zoom"))]
    try:
        cache_path.write_text(json.dumps(known, indent=1), encoding="utf-8")
    except OSError:
        log.warning("  [documentary] couldn't keep the shot plan; it's worked out again next time")
    return {i: known.get(_key(p), []) for i, p in stills.items() if Path(p).exists()}, problem


def cut(still: Path, boxes: list, seconds: float, move: str, folder: Path, stem: str) -> list:
    """[(picture, seconds, move)] for one scene: the whole still first with
    the script's move, then each framing, cropped and moved differently."""
    from PIL import Image
    if not boxes and seconds > HOLD_MAX:
        # Nothing named worth a closer look, but too long to hold: the
        # middle of the picture, a little closer, as an editor would.
        boxes = [DEFAULT_FRAMING]
    n = count(seconds, len(boxes))
    if n == 1:
        return [(Path(still), seconds, move)]
    each = seconds / n
    out = [(Path(still), each, move)]
    image = Image.open(still).convert("RGB")
    w, h = image.size
    for k, (left, top, width, height) in enumerate(boxes[:n - 1], start=1):
        crop = image.crop((int(left * w), int(top * h), int((left + width) * w), int((top + height) * h)))
        path = Path(folder) / f"{stem}_shot{k}.jpg"
        crop.resize((w, h), Image.LANCZOS).save(path, quality=93)
        centre = left + width / 2
        # Towards the framing's side of the picture, or in and out for a centred one.
        moved = "pan_right" if centre < 0.4 else "pan_left" if centre > 0.6 else ("push_in" if k == 2 else "pull_out")
        out.append((path, each, moved))
    return out


def longest_hold(timeline: list) -> float:
    """The longest a single picture stays on screen, from [(start, end)]."""
    return max((end - start for start, end in timeline), default=0.0)


def per_minute(holds: int, seconds: float) -> float:
    return round(holds / max(seconds / 60, 1e-6), 1) if seconds else 0.0

