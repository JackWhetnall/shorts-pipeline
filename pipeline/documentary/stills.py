"""
The storyboard: a drawn still for every scene of a script (decision 074).

Each still is drawn the way an animated shot's first frame is
(pipeline.animation.keyframes), with the channel's style sheet as the
first reference and the model sheet of each cast member in it, so the
whole film, and every film on the channel, is the same hand and the same
people. Then they're looked at together by a vision model, ten at a
time, beside those references, and any off-model, off-style or wrong
picture is redrawn once with the problems named. The owner sees them all
next, and can have any redrawn with a note.

The same function draws a teaser's vertical stills: the frame differs,
the look, style sheet and cast sheets don't (decision 054: a style is
independent of its frame).
"""

from __future__ import annotations

from pathlib import Path

from core import job_context
from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline.animation import keyframes, models, style
from pipeline.documentary import cast as library

log = get_logger(__name__)

CHECK_GROUP = 10                # stills per vision check


def look_for(channel, frame: str = "wide") -> dict:
    return style.compile(channel.animation, frame=frame)[1]


def board(outline: dict, channel_key: str) -> dict:
    """The film's elements, as the keyframe drawer takes them: the
    outline's cast, described as the channel's library has them."""
    elements = {}
    for member in outline.get("cast") or []:
        known = library.find(channel_key, member["name"]) or member
        elements[library.key_of(member["name"])] = {
            "kind": known.get("kind", "character"), "name": known["name"],
            "description": known.get("description", "")}
    return {"elements": elements, "colour_script": outline.get("visual_concept", "")}


def shots(scenes: list) -> list:
    return [{"index": i, "framing": s.get("framing", "medium"), "image": s["direction"],
             "elements": [library.key_of(n) for n in s.get("cast") or []]}
            for i, s in enumerate(scenes)]


def _sheets(channel, look, the_board, the_shots, style_ref) -> dict:
    """{element key: reference picture} for every cast member in a still:
    every character, and a place or object seen more than once."""
    uses = {}
    for s in the_shots:
        for k in s["elements"]:
            uses[k] = uses.get(k, 0) + 1
    sheets = {}
    for key, element in the_board["elements"].items():
        if key not in uses or (element["kind"] != "character" and uses[key] < 2):
            continue
        try:
            sheets[key] = library.sheet(channel, look, element, style_ref)
        except PipelineError as exc:
            # A missing sheet costs consistency, not the still.
            log.warning(f"  [documentary] no sheet for {element['name']}: {exc}")
    return sheets


def draw(channel, outline: dict, scenes: list, folder: Path, frame: str = "wide",
         only: list = None, notes: dict = None, check: bool = True) -> dict:
    """{scene index: still path} for `scenes`, drawn into `folder`.
    `only`: just these indices (the rest are left as they are). `notes`:
    {index: the owner's note}, to redraw those with it."""
    from pipeline.animation import bible
    notes = notes or {}
    look = look_for(channel, frame)
    style_ref = bible.reference(channel, look)
    the_board = board(outline, channel.key)
    the_board["never"] = list(channel.avoid_imagery or [])
    the_shots = shots(scenes)
    wanted = [s for s in the_shots if only is None or s["index"] in only]
    sheets = _sheets(channel, look, the_board, wanted, style_ref)
    model = models.image_model(channel.animation.image_model)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)

    def one(shot, fix=None):
        note = notes.get(shot["index"])
        fixes = ([f"The owner asks: {note}"] if note else []) + (fix or [])
        return keyframes.draw(shot, the_board, look, style_ref, sheets, folder, model,
                              fix=fixes or None)

    drawn = {}
    for shot, path in zip(wanted, job_context.parallel_map(lambda s: _try(one, s), wanted, max_workers=3)):
        if path is not None:
            drawn[shot["index"]] = path
    if not drawn:
        raise PipelineError("no stills drawn", user_message="None of the storyboard's pictures could be drawn.")
    if check:
        for start in range(0, len(wanted), CHECK_GROUP):
            group = [s for s in wanted[start:start + CHECK_GROUP] if s["index"] in drawn]
            try:
                problems = keyframes.check(group, drawn, the_board, style_ref, sheets)
            except PipelineError as exc:
                log.warning(f"  [documentary] couldn't check stills ({exc}); kept unchecked")
                continue
            for index, found in problems.items():
                log.info(f"  [documentary] redrawing still {index + 1}: {'; '.join(found)[:200]}")
                again = _try(one, the_shots[index], found)
                if again is not None:
                    drawn[index] = again
    return drawn


def draw_one(channel, outline: dict, direction: str, cast: list, folder: Path, framing: str = "close-up",
             frame: str = "wide") -> Path:
    """One picture outside the storyboard (a thumbnail's), in the film's
    look with its cast's model sheets. Raises PipelineError if it can't."""
    from pipeline.animation import bible
    look = look_for(channel, frame)
    style_ref = bible.reference(channel, look)
    the_board = board(outline, channel.key)
    the_board["never"] = list(channel.avoid_imagery or [])
    shot = {"index": 99, "framing": framing, "image": direction,
            "elements": [library.key_of(n) for n in cast]}
    sheets = _sheets(channel, look, the_board, [shot], style_ref)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stale = keyframes.path_for(folder, shot)
    stale.unlink(missing_ok=True)
    return keyframes.draw(shot, the_board, look, style_ref, sheets, folder,
                          models.image_model(channel.animation.image_model))


# --- what a still was drawn from, so it can be kept (decision 088) ----------------------

REUSE_SIMILAR = 0.9             # a direction this close, same cast and framing, keeps its picture


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def description(channel, outline: dict, scene: dict) -> dict:
    """Everything a scene's still depends on: what's drawn, who is in it
    (as they look now), how it's framed, and the look it's drawn in."""
    import hashlib
    import json
    look = look_for(channel, "wide")
    looks = {m["name"]: _norm(m.get("description")) for m in outline.get("cast") or []}
    cast = sorted(scene.get("cast") or [])
    style_key = hashlib.sha1(json.dumps([look.get("description") or look.get("key") or "",
                                         getattr(channel.animation, "image_model", "")],
                                        sort_keys=True).encode()).hexdigest()[:12]
    return {"direction": _norm(scene.get("direction")), "cast": cast, "cast_looks": [looks.get(c, "") for c in cast],
            "framing": scene.get("framing", "medium"), "medium": scene.get("medium", "picture"),
            "art_query": _norm(scene.get("art_query")), "look": style_key}


def fingerprint(desc: dict) -> str:
    import hashlib
    import json
    return hashlib.sha1(json.dumps(desc, sort_keys=True).encode()).hexdigest()


def reusable(channel, data: dict, scenes: list) -> dict:
    """{new scene index: the old still that still fits it}, for a
    storyboard drawn again after its script changed: the same thing in the
    same framing, by the same cast, in the same look, or a direction only
    reworded. Cards are left out (they cost nothing to make again)."""
    import difflib
    folder_paths = {int(k): v for k, v in (data.get("stills") or {}).items()}
    old = []
    for k, desc in (data.get("still_keys") or {}).items():
        rel = folder_paths.get(int(k))
        if rel and desc.get("medium") != "card":
            old.append((desc, rel))
    out = {}
    for i, scene in enumerate(scenes):
        if scene.get("medium") == "card":
            continue
        desc = description(channel, data["outline"], scene)
        key = fingerprint(desc)
        match = next((rel for d, rel in old if fingerprint(d) == key), None)
        if match is None:
            same = [(d, rel) for d, rel in old if all(d.get(f) == desc[f] for f in
                                                       ("cast", "cast_looks", "framing", "medium", "look"))]
            scored = [(difflib.SequenceMatcher(None, d["direction"], desc["direction"]).ratio(), rel)
                      for d, rel in same]
            best = max(scored, default=(0, None))
            match = best[1] if best[0] >= REUSE_SIMILAR else None
        if match:
            out[i] = match
    return out


def _try(one, shot, fix=None):
    try:
        return one(shot, fix) if fix else one(shot)
    except PipelineError as exc:
        log.warning(f"  [documentary] still {shot['index'] + 1} failed: {exc}")
        return None


def cost_estimate(channel, count: int) -> float:
    """Roughly what `count` stills cost, checks included."""
    return count * models.image_model(channel.animation.image_model).estimate * 1.25
