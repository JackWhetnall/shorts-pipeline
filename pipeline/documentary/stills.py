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

import re
from pathlib import Path

from core import job_context
from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline.animation import images, keyframes, models, style
from pipeline.documentary import cast as library

log = get_logger(__name__)

CHECK_GROUP = 10                # stills per vision check

# Decision 090. The check above looks at ten small pictures at once and
# missed a character with three arms and a drill with a face. A second,
# cheap look, at a larger size, for only those faults.
# Haiku was tried first: nine false alarms in ten (a drill's round teeth
# read as eyes) and the three arms missed. The usual model, at about 15
# cents a film, found the real ones.
FLAW_MODEL = ""                 # "": pipeline.llm's default model
FLAW_GROUP = 6
FLAW_SIZE = (1024, 1024)
FLAWS = """
Each picture below is a frame from a cartoon. Look closely at each one for these faults only:
- a person or animal with extra or missing arms, legs, hands or fingers, or two bodies merged;
- a face on something that isn't a character: look at every tool, machine, rock and planet in
  the picture; cartoon eyes or a smiling mouth drawn on one is a fault (round studs or bolts aren't);
- the same character drawn twice in one picture when the description names them once;
- several panels, a grid or a sheet of small studies instead of one single picture.
Anything else is fine: don't judge style, colour or composition. Most pictures have no fault;
`ok` is false only for a fault you can actually see, said in one short sentence.
""".strip()


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
    # Each setting is drawn from a sheet of its own, like a place, at its
    # own scale (decision 092), so the lab is the same lab in every picture.
    for setting in outline.get("settings") or []:
        elements.setdefault(library.key_of(setting["name"]), {
            "kind": "place", "name": setting["name"],
            "description": f"{setting['description']} (Scale: {setting['scale']}.)"})
    # No colour script for the drawer (decision 093): the visual concept is
    # the writer's, who puts a motif only where it belongs, and every
    # direction already names its light. Sent with every picture, "the same
    # two glasses ... wherever the scene allows them" stood glasses on cliffs.
    return {"elements": elements, "colour_script": ""}


def shots(scenes: list) -> list:
    return [{"index": i, "framing": s.get("framing", "medium"), "image": s["direction"],
             "elements": [library.key_of(n) for n in s.get("cast") or []]
             + ([library.key_of(s["setting"])] if s.get("setting") not in (None, "", "one-off") else [])}
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
    style_ref = bible.reference(channel, look, film=True)
    the_board = board(outline, channel.key)
    the_board["never"] = list(channel.avoid_imagery or [])
    the_shots = shots(scenes)
    wanted = [s for s in the_shots if only is None or s["index"] in only]
    sheets = _sheets(channel, look, the_board, wanted, style_ref)
    model = models.image_model(channel.animation.image_model)
    combined = _combined(channel)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)

    def fixes_for(shot, fix=None):
        note = notes.get(shot["index"])
        return ([f"The owner asks: {note}"] if note else []) + (fix or [])

    def one(shot, fix=None):
        return keyframes.draw(shot, the_board, look, style_ref, sheets, folder, model,
                              fix=fixes_for(shot, fix) or None, combined=combined)

    def draw_set(items: list) -> dict:
        """{index: path} for [(shot, fix)]: one batch at half price when the
        work is made ahead (decision 094), else three at a time."""
        if not items:
            return {}
        from pipeline import llm
        if llm.in_batch_mode():
            jobs, ready = [], {}
            for shot, fix in items:
                asked = fixes_for(shot, fix)
                job = keyframes.request(shot, the_board, look, style_ref, sheets, folder, model, fix=asked or None,
                                        combined=combined)
                if job["out"].exists() and not asked:
                    ready[shot["index"]] = job["out"]       # drawn already, as keyframes.draw keeps it
                else:
                    jobs.append(job)
            try:
                made = images.draw_batch(jobs)
            except PipelineError as exc:
                log.warning(f"  [documentary] the picture batch failed ({exc}); none of it drawn")
                made = {}
            return {**ready, **{i: p for i, p in made.items() if p is not None}}
        paths = job_context.parallel_map(lambda item: _try(one, *item), items, max_workers=3)
        return {shot["index"]: path for (shot, _), path in zip(items, paths) if path is not None}

    drawn = draw_set([(s, None) for s in wanted])
    if not drawn:
        raise PipelineError("no stills drawn", user_message="None of the storyboard's pictures could be drawn.")
    if check:
        from pipeline import llm

        def look_at(group):
            try:
                return keyframes.check(group, drawn, the_board, style_ref, sheets)
            except PipelineError as exc:
                log.warning(f"  [documentary] couldn't check stills ({exc}); kept unchecked")
                return {}
        # Each check's answer and each redraw round is saved as it's done
        # (decision 108): a stage resumed after a restart asks for the same
        # redraws, so it picks up the batch already sent, and doesn't draw
        # again a round that had finished.
        import hashlib
        tag = hashlib.sha1(",".join(str(s["index"]) for s in wanted).encode()).hexdigest()[:10]

        def checked(name, find):
            kept = job_context.load_json_checkpoint(f"stills_{tag}_{name}")
            if kept is not None:
                return {int(k): v for k, v in kept.items()}
            found = find()
            try:
                job_context.save_json_checkpoint(f"stills_{tag}_{name}", {str(k): v for k, v in found.items()})
            except Exception:  # noqa: BLE001 - a checkpoint is best-effort; the stage still runs
                pass
            return found

        def redraw(name, problems):
            for index, found in sorted(problems.items()):
                log.info(f"  [documentary] redrawing still {index + 1}: {'; '.join(found)[:200]}")
            if job_context.load_json_checkpoint(f"stills_{tag}_{name}") is not None:
                return {i: path_of(i) for i in problems if path_of(i).exists()}   # drawn before the restart
            again = draw_set([(the_shots[i], found) for i, found in sorted(problems.items())])
            try:
                job_context.save_json_checkpoint(f"stills_{tag}_{name}", sorted(again))
            except Exception:  # noqa: BLE001 - best-effort, as above
                pass
            return again

        def path_of(i):
            return keyframes.path_for(folder, the_shots[i])

        def look_all():
            groups = [[s for s in wanted[start:start + CHECK_GROUP] if s["index"] in drawn]
                      for start in range(0, len(wanted), CHECK_GROUP)]
            problems = {}
            for found in llm.run_together([lambda g=g: look_at(g) for g in groups if g]):
                problems.update(found)
            return problems
        drawn.update(redraw("redrawn", checked("checked", look_all)))
        faults = checked("flawed", lambda: flaws([s for s in wanted if s["index"] in drawn], drawn))
        drawn.update(redraw("fixed", faults))
    return drawn


def flaws(the_shots: list, drawn: dict) -> dict:
    """{shot index: [fault]} from the cheap close look (decision 090):
    about a cent for ten pictures. A look that fails finds nothing."""
    from pipeline.llm import DEFAULT_MODEL, call_json, run_together

    def look(group) -> dict:
        try:
            pictures = []
            for s in group:
                pictures += [("text", f"Picture {s['index']}: {s['image'][:300]}"),
                             keyframes.thumbnail(drawn[s["index"]], FLAW_SIZE)]
            data = call_json(FLAWS, "Check every picture above.", keyframes._check_schema(), images=pictures,
                             operation="documentary_flaw_check", model=FLAW_MODEL or DEFAULT_MODEL,
                             max_tokens=4000)
        except (PipelineError, OSError) as exc:
            log.warning(f"  [documentary] couldn't look for flaws ({exc}); kept as drawn")
            return {}
        wanted, found_here = {s["index"] for s in group}, {}
        for row in data.get("shots") or []:
            # It sometimes marks a picture failed while saying it's fine
            # ("no actual facial features, so it's fine; no clear fault").
            found = [p for p in row.get("problems") or [] if p and not CLEARED.search(p)]
            if row.get("index") in wanted and not row.get("ok") and found:
                found_here[row["index"]] = found
        return found_here

    # Side by side in batch mode (one batch round, not eleven).
    out = {}
    groups = [the_shots[start:start + FLAW_GROUP] for start in range(0, len(the_shots), FLAW_GROUP)]
    for found in run_together([lambda g=g: look(g) for g in groups]):
        out.update(found)
    return out


CLEARED = re.compile(r"no (clear |actual |real )?(fault|problem)|so it'?s fine|is fine|looks fine", re.IGNORECASE)


# --- the same picture, drawn once (decision 090) ----------------------------------------

REPEATS = """
You are a film's picture editor, deciding which storyboard pictures can be used more than once.
Below are a film's scenes, each with what its picture must show. A scene can reuse an EARLIER
scene's picture only if that same picture, unchanged, would serve it fully: the same subject,
the same people in the same pose doing the same thing, the same place and framing, the same time
of day, light and weather (dawn is not dusk; an empty scene is not one with a crowd). The camera
will move differently over it, so a reuse never looks frozen.

When a scene needs something the earlier picture doesn't show (someone else, a new action or
expression, a change in the thing itself, a closer or wider view), it is a new picture: keep it.
Reuse is for the picture a film keeps coming back to (the same diagram-like cutaway, the same
establishing view of a place), not for every scene in the same location.

For each scene that can reuse an earlier one, give `scene` and `same_as`, the earlier scene's
number. Leave every other scene out.
""".strip()


REPEAT_MODEL = "claude-haiku-4-5"     # a text judgement; a cent a film


def _repeats_schema() -> dict:
    return {"type": "object", "properties": {"reuse": {"type": "array", "items": {
        "type": "object", "properties": {"scene": {"type": "integer"}, "same_as": {"type": "integer"}},
        "required": ["scene", "same_as"], "additionalProperties": False}}},
        "required": ["reuse"], "additionalProperties": False}


def repeats(scenes: list, pool: list) -> dict:
    """{scene: earlier scene whose picture it can use}, among `pool`
    (the scenes about to be drawn): one cheap text call. A scene reuses an
    original, never another reuse, and never the scene just before it."""
    from pipeline.llm import call_json
    pool = sorted(i for i in pool if scenes[i].get("medium", "picture") == "picture")
    if len(pool) < 2:
        return {}
    lines = [f"{i}. ({scenes[i].get('framing', 'medium')}; cast: {', '.join(scenes[i].get('cast') or []) or 'none'})"
             f" {scenes[i]['direction']}" for i in pool]
    try:
        data = call_json(REPEATS, "The scenes:\n" + "\n".join(lines), _repeats_schema(),
                         operation="documentary_repeats", model=REPEAT_MODEL, max_tokens=3000, effort=None)
    except PipelineError as exc:
        log.warning(f"  [documentary] couldn't look for repeated pictures ({exc}); drawing them all")
        return {}
    allowed, out = set(pool), {}
    for row in data.get("reuse") or []:
        i, j = row.get("scene"), row.get("same_as")
        if (i in allowed and j in allowed and j < i - 1 and j not in out and i not in out.values()
                and scenes[i].get("framing") == scenes[j].get("framing")
                and sorted(scenes[i].get("cast") or []) == sorted(scenes[j].get("cast") or [])):
            out[i] = j
    return out


def draw_one(channel, outline: dict, direction: str, cast: list, folder: Path, framing: str = "close-up",
             frame: str = "wide") -> Path:
    """One picture outside the storyboard (a thumbnail's), in the film's
    look with its cast's model sheets. Raises PipelineError if it can't."""
    from pipeline.animation import bible
    look = look_for(channel, frame)
    style_ref = bible.reference(channel, look, film=True)
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
                          models.image_model(channel.animation.image_model), combined=_combined(channel))


def _combined(channel) -> bool:
    """Whether its pictures are drawn from one sheet of references (decision 096)."""
    return bool(getattr(getattr(channel, "documentary", None), "combined_references", True))


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
    out = {"direction": _norm(scene.get("direction")), "cast": cast, "cast_looks": [looks.get(c, "") for c in cast],
           "framing": scene.get("framing", "medium"), "medium": scene.get("medium", "picture"),
           "art_query": _norm(scene.get("art_query")), "look": style_key}
    if scene.get("setting"):
        where = {s["name"]: s for s in outline.get("settings") or []}.get(scene["setting"], {})
        out["setting"] = _norm(f"{scene['setting']} {where.get('description', '')}")
    return out


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
            same = [(d, rel) for d, rel in old if all(d.get(f) == desc.get(f) for f in
                                                       ("cast", "cast_looks", "framing", "medium", "look",
                                                        "setting"))]
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
