"""
The picture editor: every scene's picture looked at together, before any
is drawn (decision 092).

The writer writes a chapter at a time, so it can't see that it has asked
for the same picture a dozen times, and it will happily put things in a
picture that can't be there together. The first explainers did both: a
dozen pictures of the planet cut open with people looking up at it,
which is two scales (a planet in space, people on the ground) in one
frame, and the same composition again and again with a layer more
peeled. The owner's example of the general problem: in a film about
amoebas, the amoebas belong in the Petri dish and the people in the lab;
the amoebas must never turn up on the lab bench.

So the outline names the places the film returns to, each at one scale,
and where each cast member exists (pipeline.documentary.outline); a
picture the film doesn't return to, a visual metaphor or an example, is
a one-off with a place of its own. This pass reads every picture at once
and fixes three things:

- a picture that puts something where it can't be is redirected, to the
  right setting or with the thing seen through something real there (a
  screen, a model, a map);
- pictures a viewer would feel they'd already seen are either the same
  picture shown again (`same_as`: drawn once, recut by the editor), when
  the narration is still about it, or redirected to something genuinely
  new, when it has moved on;
- no setting carries too much of the film or runs too long (BALANCE), so
  the ideas get pictures of their own. A first try with five settings
  and no one-offs put 40 of 77 scenes in two cutaways.

Then `audit` checks the rules with no model at all (anyone named where
they don't exist, a setting over its share, a run too long), and
anything still wrong goes back to the editor once. `validate` holds every
scene to the rules in the end: cast only where it exists, a picture shown
at most three times, never twice in a row. The storyboard draws what this
decided; the older `stills.repeats` stays for scripts made before it.
"""

from __future__ import annotations

import re

from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline.llm import call_json

log = get_logger(__name__)

# One answer is at most 20,000 tokens, thinking included: an editor asked
# to fix a whole film at once, at medium effort, ran past it twice.
MAX_TOKENS = 16000
EFFORT = "low"
PER_ANSWER = 15                 # changes in one answer
BATCH = 10                      # problems sent back to the editor at a time
FIX_ROUNDS = 2
MAX_SHOWINGS = 3                # one picture on screen at most this many times in a film
ONE_OFF = "one-off"
# (the most of a film's pictures one setting may carry, the most in a row):
# an explainer's ideas need pictures of their own; a story can stay put.
# At 25% and four in a row, a plan turned 29 scenes into generic one-offs
# (a hand turning a screw, a straining cable); the looks' count does the
# work against sameness, so balance only keeps one place from dominating.
# Decision 113: six in a row pushed a cabin sequence out to an unrelated
# cutaway; a run is now longer, and broken by other views of the place.
BALANCE = {"explainer": (0.35, 9), "story": (0.45, 10)}
# Pictures of their own one look (the same subject in the same place, any
# framing) may have;
# the rest of that group show one of them again or become something else.
# The editor, asked only to avoid near-duplicates, let thirteen pictures of
# the drill bit in its shaft through as "different": it groups, code counts.
LOOKS_MAX = {"explainer": 4, "story": 5}
ONE_OFF_MAX = 2                 # a metaphor used twice is a callback; more is a habit
# Times one look may be on screen in a film, pictures shown again counted:
# four pictures each shown three times put the shaft on screen eleven times.
SHOWN_MAX = {"explainer": 6, "story": 9}

SUBJECTS = """
For each picture of a film's storyboard, name its main subject: the one thing a viewer's eye goes
to, in two to four words. Name the thing, not the place, the action or the framing. Use exactly
the same words every time the same thing is the main subject, however it is framed or what it is
doing: a cast member by their name; "the drill bit" whether it is descending, coated in rock or
seized; "the planet's layers" whether one band or all of them is shown.
""".strip()

SYSTEM = """
You are a film's picture editor. The script is written; before a single picture is drawn you go
through every scene's picture together and fix what a viewer would notice.

1. A picture happens in one setting, at that setting's scale, and shows only what exists there.
   The film's settings, and the settings each cast member exists in, are listed; "one-off" is a
   picture with a place of its own that the film doesn't return to (a visual metaphor, an example).
   A picture that puts something where it can't be (a person standing beside a planet cut open
   in space, a person inside a cutaway where no one could stand, a microbe on a lab bench) is
   redirected: to the setting where it belongs, or with the thing seen through something real in
   this setting (a screen, a model, a map, a window, a specimen jar).

2. No picture the viewer would feel they'd already seen. Two pictures are the same when they show
   the same main subject from about the same viewpoint at the same scale, whatever small details
   differ (one more layer peeled back, the onlookers moved, a different time of day, a glow a
   little brighter). Look for every such group across the whole film. For each later member:
   - if the narration over it is still about what the earlier picture shows, `reuse` that
     earlier picture: it is shown again, recut, so nothing new is drawn;
   - if the narration has moved on, `redirect` it to a genuinely different picture that shows
     what is being said now: another setting, subject, viewpoint or scale, often a one-off
     visual metaphor for the idea (pressure as a stack of elephants on a chair, flowing rock as
     toffee, a scale as something the viewer has held).
   One picture is shown at most three times in a film, never in two scenes in a row.
   The same goes for ideas: an idea gets one picture, its metaphor, and when the narration comes
   back to that idea the film shows that picture again rather than a new prop for the same point
   (wet clay, wax, sand and mud all closing over something are one idea four times). A one-off
   belongs to the film's own world wherever it can (its places, materials and things), not a
   generic object on a plain table.

3. Balance: {balance}

4. Every picture shows what its line is about. While the narration stays in a place (a run of
   lines inside the spacecraft cabin), its pictures stay there too; cutting away to a different
   place mid-thought (the cabin, then a climbing harness in a gear shed, then the cabin) is a
   fault the viewer feels, even if the cutaway is a fair metaphor. Break a long run in one place
   with another view of it (a close-up of a hand or a detail there, a different angle, the same
   place in different light), not by leaving it. A cutaway to a one-off belongs where the
   narration itself turns to an idea the place can't show, and the cutaway must show that idea.

5. A picture stays right however it's drawn: an image model can't be trusted with exact detail
   (decision 118). Where a picture's point is a precise position, angle, direction, orientation,
   count, sequence of stages, shape's outline, reflection, text, map or diagram (a cap lodged
   sideways, a sign's shape changing step by step, which way a shadow moves), redirect it to one
   that doesn't depend on that detail: the object whole and at rest, the person it happens to,
   their face, the place. The narration says the detail; the picture never has to show it.

Most scenes need nothing; list only the ones that do, at most {most} in this answer, the most
important first (whatever is left is sent back to you). A redirect gives the new `direction` (one
frozen, drawable moment, as concrete and careful as the others, with no text, charts or labels
in the picture; never a process: "tighter and tighter" or "slowly covered until it vanishes" is
drawn as a strip of panels), its `setting` (a listed one or "one-off") and its `cast` (none for a one-off); `same_as`
is -1. A reuse gives `same_as`, the earlier scene's number, and leaves `direction` empty. `why`
says in a few words what was wrong.
""".strip()

BALANCE_TEXT = ("no setting carries more than {share:.0%} of the film's pictures (shown-again ones "
                "count), and no more than {run} pictures in a row are in one setting. Where a setting "
                "is over, redirect some of its pictures, only the ones whose narration is about an idea "
                "rather than that place, to one-off pictures of that idea; a long run whose lines are all "
                "about the place gets other views of the place instead (rule 4), never a cutaway that "
                "doesn't show what's said.")


def schema() -> dict:
    row = {"type": "object", "properties": {
        "scene": {"type": "integer"}, "action": {"type": "string", "enum": ["reuse", "redirect"]},
        "same_as": {"type": "integer"}, "direction": {"type": "string"}, "setting": {"type": "string"},
        "cast": {"type": "array", "items": {"type": "string"}}, "why": {"type": "string"}},
        "required": ["scene", "action", "same_as", "direction", "setting", "cast", "why"],
        "additionalProperties": False}
    return {"type": "object", "properties": {"changes": {"type": "array", "items": row}},
            "required": ["changes"], "additionalProperties": False}


def _context(outline: dict) -> str:
    """The settings and cast: the same in every call of a plan (cached)."""
    settings = "\n".join(f"- {s['name']} ({s['scale']}): {s['description']}" for s in outline.get("settings") or [])
    cast = "\n".join(f"- {m['name']} ({m.get('kind', 'character')}; exists in: "
                     f"{', '.join(m.get('settings') or []) or 'anywhere'})" for m in outline.get("cast") or [])
    return f"Settings:\n{settings or '(none named)'}\n\nCast:\n{cast or '(none)'}\n\n"


def _brief(outline: dict, scenes: list) -> str:
    settings = "\n".join(f"- {s['name']} ({s['scale']}): {s['description']}" for s in outline.get("settings") or [])
    cast = "\n".join(f"- {m['name']} ({m.get('kind', 'character')}; exists in: "
                     f"{', '.join(m.get('settings') or []) or 'anywhere'})" for m in outline.get("cast") or [])
    lines = []
    for i, s in enumerate(scenes):
        if s.get("medium") == "card":
            lines.append(f"{i}. (an on-screen card, not a picture)")
            continue
        shown = f" shows scene {s['same_as']}'s picture again;" if isinstance(s.get("same_as"), int) else ""
        lines.append(f"{i}. [chapter {s['chapter']}; setting: {s.get('setting') or '?'};{shown} "
                     f"{s.get('framing', 'medium')}; cast: {', '.join(s.get('cast') or []) or 'none'}] "
                     f"{s.get('direction', '')}\n    Narration: {s.get('narration', '')[:160]}")
    return (f"Settings:\n{settings or '(none named)'}\n\nCast:\n{cast or '(none)'}\n\n"
            "The scenes, in order:\n" + "\n".join(lines))


def system_text(kind: str, most: int = PER_ANSWER) -> str:
    """The picture editor's instructions for this kind of film."""
    share, run = BALANCE.get(kind, BALANCE["story"])
    return SYSTEM.replace("{balance}", BALANCE_TEXT.format(share=share, run=run)).replace("{most}", str(most))


def problems(outline: dict, scenes: list, groups: list, kind: str = "story") -> list:
    """[{scene, problem}] the code still finds in a planned storyboard."""
    return _merged(audit(outline, scenes, kind) + crowded(groups, scenes, kind))


def _ask(outline: dict, scenes: list, kind: str, extra: str = "") -> dict:
    system = system_text(kind)
    brief = _brief(outline, scenes)
    context = _context(outline)
    return call_json(system, brief[len(context):] + (f"\n\n{extra}" if extra else ""), schema(),
                     operation="documentary_pictures", max_tokens=MAX_TOKENS, effort=EFFORT,
                     cache_prefix=context if brief.startswith(context) else None)


def _apply(outline: dict, scenes: list, data: dict) -> list:
    settings = {s["name"].lower(): s["name"] for s in outline.get("settings") or []}
    settings[ONE_OFF] = ONE_OFF
    names = {m["name"].lower(): m["name"] for m in outline.get("cast") or []}
    notes = []
    for row in data.get("changes") or []:
        i = row.get("scene")
        if not isinstance(i, int) or not 0 <= i < len(scenes) or scenes[i].get("medium") == "card":
            continue
        scene = scenes[i]
        if row.get("action") == "reuse" and isinstance(row.get("same_as"), int) and row["same_as"] >= 0:
            scene["same_as"] = row["same_as"]
        elif row.get("action") == "redirect" and " ".join(str(row.get("direction") or "").split()):
            scene["direction"] = " ".join(str(row["direction"]).split())
            scene.pop("same_as", None)
            setting = settings.get(str(row.get("setting") or "").strip().lower())
            if setting:
                scene["setting"] = setting
            scene["cast"] = [names[n.strip().lower()] for n in row.get("cast") or [] if n.strip().lower() in names]
        else:
            continue
        notes.append({"scene": i, "action": row["action"], "why": " ".join(str(row.get("why") or "").split())})
    return notes


def _key(text: str) -> str:
    words = re.findall(r"[a-z0-9']+", str(text).lower())
    return " ".join(w for w in words if w not in ("the", "a", "an", "its", "his", "her", "their"))


def looks(outline: dict, scenes: list) -> list:
    """[{"look", "scenes"}]: the storyboard's pictures grouped by what a
    viewer would see, the same main subject in the same setting, whatever
    the framing. The model names each picture's subject (one small call);
    the code groups them. Asked to group the pictures itself, it either
    split one subject by framing or lumped a whole place into one look.
    Shown-again scenes and cards are left out. One-offs are grouped by
    subject too: left out of the count, the first plan put wet clay
    swallowing something in four of them."""
    pictures = [i for i, s in enumerate(scenes) if s.get("medium", "picture") != "card"
                and not isinstance(s.get("same_as"), int)]
    if len(pictures) < 2:
        return [{"look": "", "scenes": pictures}]
    cast = ", ".join(m["name"] for m in outline.get("cast") or [])
    lines = [f"{i}. {scenes[i].get('direction', '')}" for i in pictures]
    schema = {"type": "object", "properties": {"pictures": {"type": "array", "items": {
        "type": "object", "properties": {"scene": {"type": "integer"}, "subject": {"type": "string"}},
        "required": ["scene", "subject"], "additionalProperties": False}}},
        "required": ["pictures"], "additionalProperties": False}
    data = call_json(SUBJECTS, (f"The cast: {cast}\n\n" if cast else "") + "The pictures:\n" + "\n".join(lines),
                     schema, operation="documentary_looks", max_tokens=6000, effort="low")
    return grouped(outline, scenes, {r.get("scene"): r.get("subject") or "" for r in data.get("pictures") or []})


def grouped(outline: dict, scenes: list, subjects: dict) -> list:
    """`looks` from {scene: its main subject}, however named: the model's
    one call, or the newsroom's picture editor (decision 127)."""
    pictures = [i for i, s in enumerate(scenes) if s.get("medium", "picture") != "card"
                and not isinstance(s.get("same_as"), int)]
    if len(pictures) < 2:
        return [{"look": "", "scenes": pictures}]
    named = {i: _key(subject) for i, subject in subjects.items()}
    # A cutaway is one view whatever its subject is called: the shaft cut
    # open came back eleven times as "the drill bit" and "the borehole shaft".
    cutaways = {s["name"] for s in outline.get("settings") or [] if s.get("scale") == "cutaway"}
    groups = {}
    for i in pictures:
        setting = scenes[i].get("setting") or ""
        subject = "the view" if setting in cutaways else (named.get(i) or f"#{i}")
        groups.setdefault((setting, subject), []).append(i)
    return [{"look": f"{subject} ({setting or 'somewhere'})", "scenes": members}
            for (setting, subject), members in groups.items()]


def crowded(groups: list, scenes: list, kind: str = "story") -> list:
    """[{scene, problem}] for each look with more pictures of its own than
    LOOKS_MAX allows (shown-again scenes don't count; redirected ones have
    left it), or on screen more often than SHOWN_MAX allows, counting the
    scenes that show its pictures again."""
    found = []
    for g in groups:
        own = [i for i in g["scenes"] if not isinstance(scenes[i].get("same_as"), int)]
        appearances = sorted(set(own) | {i for i, s in enumerate(scenes) if s.get("same_as") in own})
        cap = SHOWN_MAX.get(kind, SHOWN_MAX["story"])
        if len(appearances) > cap:
            found += [{"scene": i, "problem": f'the look "{g["look"]}" is on screen {len(appearances)} times (at most '
                                              f"{cap}); make this a genuinely different picture"}
                      for i in appearances[cap:]]
        most = ONE_OFF_MAX if own and scenes[own[0]].get("setting") == ONE_OFF else LOOKS_MAX.get(
            kind, LOOKS_MAX["story"])
        if len(own) > most:
            listed = ", ".join(str(i) for i in own)
            found += [{"scene": i, "problem": f'one of {len(own)} pictures of the same look ("{g["look"]}": scenes '
                                              f"{listed}); at most {most} may stay pictures of their own: show one of "
                                              f"those again, or make this a genuinely different picture"}
                      for i in own[most:]]
    return found


def _merged(problems: list) -> list:
    """One entry a scene, its problems joined, in scene order."""
    by = {}
    for p in problems:
        by.setdefault(p["scene"], []).append(p["problem"])
    return [{"scene": i, "problem": "; ".join(dict.fromkeys(ps))} for i, ps in sorted(by.items())]


def plan(outline: dict, script: dict, kind: str = "story") -> dict:
    """The script with its pictures planned: misplaced ones redirected,
    repeated ones shown again or made new (`same_as`), the settings
    balanced, every scene then held to the rules. The model names each
    picture's subject and edits; the code groups, counts and checks.

    One pass over the whole film first; then what the code still finds
    goes back BATCH scenes at a time, each with the whole storyboard to
    see, for up to FIX_ROUNDS rounds. One answer fixing thirty scenes hit
    the 20,000-token ceiling and the film went unplanned. Ten to twenty
    cents. Raises PipelineError if the first pass can't be made;
    `validate` alone still applies the rules."""
    scenes = [dict(s) for s in script["scenes"]]
    try:
        groups = looks(outline, scenes)
    except PipelineError as exc:
        log.warning(f"  [documentary] the storyboard couldn't be sorted by look ({exc}); counting skipped")
        groups = []
    notes = []

    def edit(extra: str) -> None:
        nonlocal scenes
        notes.extend(_apply(outline, scenes, _ask(outline, scenes, kind, extra)))
        scenes = validate(outline, scenes)

    def relabel() -> None:
        # Redirected pictures are new and may repeat each other: label again.
        nonlocal groups
        try:
            groups = looks(outline, scenes)
        except PipelineError as exc:
            log.warning(f"  [documentary] couldn't sort the storyboard again ({exc}); the last count stands")

    edit("")
    relabel()
    left = _merged(audit(outline, scenes, kind) + crowded(groups, scenes, kind))
    for _ in range(FIX_ROUNDS):
        if not left:
            break
        log.info(f"  [documentary] {len(left)} picture problem(s) left; the picture editor fixes them")
        for start in range(0, len(left), BATCH):
            batch = left[start:start + BATCH]
            try:
                edit("These pictures break the rules. Fix each one listed, and nothing else:\n"
                     + "\n".join(f"- scene {p['scene']}: {p['problem']}" for p in batch))
            except PipelineError as exc:
                log.warning(f"  [documentary] the picture editor couldn't fix a batch ({exc})")
        relabel()
        left = _merged(audit(outline, scenes, kind) + crowded(groups, scenes, kind))
    out = {**script, "scenes": scenes}
    out["pictures"] = {"planned": True, "changes": notes, "unfixed": left,
                       "looks": [g for g in groups if len(g["scenes"]) > 1],
                       "shown_again": sum(1 for s in scenes if isinstance(s.get("same_as"), int))}
    return out


THROUGH = re.compile(r"\b(screens?|monitors?|models?|maps?|photo(graph)?s?|windows?|jars?|globes?|posters?|"
                     r"paintings?|reflections?|eyepieces?|tablets?|televisions?|tvs?|displays?|slides?)\b",
                     re.IGNORECASE)


def _mentions(name: str, text: str) -> bool:
    """Whether a direction puts `name` in its picture in person: named,
    and not only through something real there (a screen, a model)."""
    bare = re.sub(r"^the\s+", "", name, flags=re.IGNORECASE)
    return bool(re.search(rf"\b{re.escape(bare)}\b", text or "", re.IGNORECASE)) and not THROUGH.search(text or "")


def audit(outline: dict, scenes: list, kind: str = "story") -> list:
    """[{scene, problem}] for the rules a model isn't needed to check:
    anyone a picture names who doesn't exist in its setting, a setting over
    its share of the film, a run of pictures too long in one setting."""
    lives = {m["name"]: set(m.get("settings") or []) for m in outline.get("cast") or [] if m.get("settings")}
    found = []
    pictures = [(i, s) for i, s in enumerate(scenes) if s.get("medium", "picture") != "card"]
    for i, s in pictures:
        if isinstance(s.get("same_as"), int):
            continue
        setting = s.get("setting")
        for name, where in lives.items():
            if setting and (setting == ONE_OFF or setting not in where) and _mentions(name, s.get("direction", "")):
                found.append({"scene": i, "problem": f"{name} doesn't exist in {setting}; move the picture, "
                                                     f"or show them only through something real there"})
    share, run = BALANCE.get(kind, BALANCE["story"])
    allowed = max(4, int(share * len(pictures) + 0.999))
    counts = {}
    for i, s in pictures:
        if s.get("setting") and s["setting"] != ONE_OFF:
            counts.setdefault(s["setting"], []).append(i)
    for setting, members in counts.items():
        if len(members) > allowed:
            over = [i for i in members if not isinstance(scenes[i].get("same_as"), int)][-(len(members) - allowed):]
            found += [{"scene": i, "problem": f"{setting} carries {len(members)} of {len(pictures)} pictures "
                                              f"(at most {allowed}); give this idea a picture of its own"}
                      for i in over]
    streak = []
    for i, s in pictures:
        if streak and s.get("setting") and s.get("setting") == scenes[streak[-1]].get("setting") \
                and s["setting"] != ONE_OFF:
            streak.append(i)
        else:
            streak = [i]
        if len(streak) == run + 1:
            found.append({"scene": i, "problem": f"{run + 1} pictures in a row in {s['setting']}; cut away"})
            streak = [i]
    seen = set()
    return [p for p in found if not (p["scene"] in seen or seen.add(p["scene"]))]


def validate(outline: dict, scenes: list) -> list:
    """Every scene held to the rules, with no model: its setting one the
    outline names, or a one-off; its cast only members who exist there
    (none in a one-off); a picture shown again only an earlier, drawn,
    unrepeated one, at most MAX_SHOWINGS times in all, never the scene
    just before."""
    settings = {s["name"].lower(): s["name"] for s in outline.get("settings") or []}
    lives = {m["name"]: set(m.get("settings") or []) for m in outline.get("cast") or []}
    shown, described = {}, {}
    out = []
    for i, s in enumerate(scenes):
        s = dict(s)
        # A picture described like an earlier one, word for word or with a
        # few words added ("..., now still and final"), is that picture.
        words = " ".join(re.findall(r"[a-z0-9']+", str(s.get("direction") or "").lower()))
        if words and s.get("medium", "picture") == "picture" and not isinstance(s.get("same_as"), int):
            earlier = next((j for w, j in described.items()
                            if words == w or (words.startswith(w + " ") and len(words.split()) - len(w.split()) <= 6)),
                           None)
            if earlier is not None:
                s["same_as"] = earlier
            else:
                described[words] = i
        raw = str(s.get("setting") or "").lower()
        setting = settings.get(raw)
        if raw == ONE_OFF:
            s["setting"], s["cast"] = ONE_OFF, []
        elif setting:
            s["setting"] = setting
            s["cast"] = [c for c in s.get("cast") or [] if not lives.get(c) or setting in lives[c]]
        else:
            s.pop("setting", None)
        j = s.get("same_as")
        if isinstance(j, int):
            ok = (0 <= j < i - 1 and s.get("medium", "picture") == "picture"
                  and out[j].get("medium", "picture") == "picture" and not isinstance(out[j].get("same_as"), int)
                  and shown.get(j, 1) < MAX_SHOWINGS)
            if ok:
                shown[j] = shown.get(j, 1) + 1
                # It shows that picture, so it is where that picture is.
                s["cast"] = list(out[j].get("cast") or [])
                if out[j].get("setting"):
                    s["setting"] = out[j]["setting"]
                else:
                    s.pop("setting", None)
            else:
                s.pop("same_as")
        out.append(s)
    return out
