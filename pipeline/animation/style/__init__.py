"""
A channel's animated style, as answers to a few plain questions
(decision 053).

The questions and every option live in grammar.yaml: what each option
means for the engines, and when it makes sense. From a channel's answers
this module

- offers only the options that fit the answers before (`options_for`),
- fills and repairs a set of answers (`normalise`): a missing answer gets
  the question's default for its context, one that no longer fits is
  replaced and reported,
- compiles them into what the pipeline runs on (`compile`): the engine's
  settings (`fmt`: composited or generated, the stage, the kit's view,
  labels, layouts, the storyboard's grammar) and the drawing's (`look`:
  medium, light, palette, people, motion, grade),
- says in one sentence what the style is (`summary`).

The browser evaluates the same conditions (web/static/app.js,
`styleValid`), from the same file, so the builder and the pipeline can't
disagree about what's allowed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
GRAMMAR_PATH = HERE / "grammar.yaml"
STARTING_POINTS_PATH = HERE / "starting_points.yaml"
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
CUSTOM_MAX = 300

# What decides how things are drawn: a change to any of these is a new
# set of pictures (kit, style frames). Labels, motion and layout are not.
DRAWN_BY = ("approach", "stage", "material", "people", "mood")


@lru_cache(maxsize=1)
def grammar() -> dict:
    data = yaml.safe_load(GRAMMAR_PATH.read_text(encoding="utf-8"))
    for q in data["questions"]:
        q["by_id"] = {o["id"]: o for o in q["options"]}
    data["by_id"] = {q["id"]: q for q in data["questions"]}
    return data


def questions() -> list:
    return grammar()["questions"]


# --- conditions ---------------------------------------------------------------

def matches(condition, answers: dict) -> bool:
    """A condition: {question: [options]} (every question listed has one
    of its options), or a list of those (any will do)."""
    if not condition:
        return True
    if isinstance(condition, list):
        return any(matches(c, answers) for c in condition)
    return all(answers.get(q) in allowed for q, allowed in condition.items())


def valid(option: dict, answers: dict) -> bool:
    if "when" in option and not matches(option["when"], answers):
        return False
    if "not" in option and _any_listed(option["not"], answers):
        return False
    return True


def _any_listed(condition, answers) -> bool:
    if isinstance(condition, list):
        return any(_any_listed(c, answers) for c in condition)
    return any(answers.get(q) in listed for q, listed in condition.items())


def options_for(qid: str, answers: dict) -> list:
    """The options of question `qid` that fit `answers` (only the
    questions before it are read)."""
    return [o for o in grammar()["by_id"][qid]["options"] if valid(o, answers)]


def default_for(question: dict, answers: dict):
    offered = [o for o in question["options"] if valid(o, answers)]
    ids = {o["id"] for o in offered}
    for rule in question.get("defaults") or []:
        if rule["option"] in ids and matches(rule["when"], answers):
            return rule["option"]
    return offered[0]["id"] if offered else None


def normalise(style: dict) -> tuple:
    """(style, changed): every question answered with an option that fits
    the answers before it; `changed` lists the questions whose given
    answer didn't fit and was replaced. A question none of whose options
    fit isn't asked (and has no answer)."""
    style = dict(style or {})
    custom = {k: str(v)[:CUSTOM_MAX] for k, v in (style.get("custom") or {}).items()
              if str(v or "").strip()}
    answers, changed = {}, []
    for q in questions():
        offered = [o["id"] for o in q["options"] if valid(o, answers)]
        if not offered:
            continue
        given = style.get(q["id"])
        if given in offered and not (q["by_id"][given].get("custom") and not custom.get(q["id"])):
            answers[q["id"]] = given
        else:
            if given:
                changed.append(q["id"])
            answers[q["id"]] = default_for(q, answers)
    answers["custom"] = {k: v for k, v in custom.items()
                         if answers.get(k) and q_option(k, answers[k]).get("custom")}
    return answers, changed


def q_option(qid: str, oid: str) -> dict:
    return grammar()["by_id"][qid]["by_id"].get(oid) or {}


# --- compiling -----------------------------------------------------------------

def _fill(value, custom: str):
    if isinstance(value, str):
        return value.replace("{custom}", custom or "")
    if isinstance(value, dict):
        return {k: _fill(v, custom) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, custom) for v in value]
    return value


def merged(answers: dict) -> dict:
    """Every chosen option's `sets` (and matching variants), in question
    order: later answers override, the `append` fields add up."""
    append = set(grammar().get("append") or [])
    out = {}
    for q in questions():
        oid = answers.get(q["id"])
        if not oid:
            continue
        option = q["by_id"][oid]
        custom = (answers.get("custom") or {}).get(q["id"], "")
        layers = [option.get("sets") or {}]
        layers += [v.get("sets") or {} for v in option.get("variants") or []
                   if matches(v.get("when"), answers)]
        for layer in layers:
            for key, value in _fill(copy.deepcopy(layer), custom).items():
                if key in append and isinstance(value, str):
                    joiner = "\n" if key == "guide" else " "
                    out[key] = (out.get(key, "") + joiner + value).strip()
                elif isinstance(value, dict) and isinstance(out.get(key), dict):
                    out[key] = {**out[key], **value}
                else:
                    out[key] = value
    return out


def compile(animation, frame=None) -> tuple:
    """(fmt, look) for a channel's animation settings (core.channels.
    Animation or anything with the same attributes), for a vertical short
    or a widescreen video (`frame`, pipeline.animation.frame): what the
    engines and the drawing run on. See the module docstring."""
    from pipeline.animation import frame as frames
    from pipeline.animation import look as looks

    answers, _ = normalise(getattr(animation, "style", None) or {})
    m = merged(answers)
    stage, material = answers.get("stage"), answers.get("material")
    boards = m.get("boards") or {}
    board = boards.get(stage) or boards.get("default") or \
        "a clean surface in keeping with the medium"
    medium = m.get("medium") or m.get("image", "")[:80]
    people = m.get("people", "")
    notes = " ".join(str(getattr(animation, "style_notes", "") or "").split())
    palette = [c for c in (getattr(animation, "palette", None) or []) if HEX_RE.match(str(c))]

    fmt = {
        "key": f"{answers.get('approach')}_{stage}",
        "label": title(answers),
        "engine": m.get("engine", "generated"),
        "grammar": m.get("grammar", "drama"),
        "continuity": m.get("continuity", "move"),
        "areas": m.get("areas", "single"),
        "view": m.get("view", "front"),
        "entrance": m.get("entrance", "pop"),
        "avatar": bool(m.get("avatar")),
        "tilt": float(m.get("tilt", 0)),
        "layouts": list(m.get("layouts") or []),
        "captions": bool(m.get("captions")),
        "labels": dict(m.get("labels") or {}),
        "no_labels": bool(m.get("no_labels")),
        "shadow": dict(m.get("shadow") or {"mode": "none"}),
        "surface": (m["surface"].replace("{board}", board) if m.get("surface") else None),
        "backdrop": (m["backdrop"].replace("{medium}", medium) if m.get("backdrop") else None),
        "kit_view": m.get("kit_view", ""),
        "narrator": " ".join(p for p in (m.get("narrator", ""), people) if p),
        "guide": "\n".join(p for p in (m.get("guide", ""), m.get("tone", "")) if p),
        "dark_surface": bool(m.get("dark_surface")),
        "camera": m.get("camera", ""),
        "diagrams": list(m.get("diagrams") or []),
        "frame": frames.get(frame).key,
    }
    look = {
        "label": title(answers),
        "description": summary(answers),
        "image": m.get("image", ""),
        "light": m.get("light", ""),
        "camera": m.get("camera") or "gentle, motivated camera moves",
        "motion": m.get("motion") or "gentle, purposeful movement",
        "palette": palette or list(m.get("palette") or []),
        "avoid": m.get("avoid", "photorealism"),
        "cadence": m.get("cadence", "twos"),
        "texture": m.get("texture", "none"),
        "surface": board,
        "people": people,
        "medium": medium,
        "canvas": m.get("canvas"),
        "notes": notes,
        "suggested_palettes": [list(m.get("palette") or [])] + list(m.get("palettes") or []),
    }
    finish = max(0, min(100, int(getattr(animation, "finish", 100)))) / 100
    look["grade"] = looks.scaled_grade(m.get("grade") or {}, finish)
    look["jitter"] = m.get("jitter")
    look["energy"] = max(0, min(100, int(getattr(animation, "energy", 50))))
    look["pace"] = max(0, min(100, int(getattr(animation, "pace", 50))))
    look["identity"] = identity(answers, look)
    look["key"] = f"{slug(material or 'style')}_{look['identity'][:6]}"
    look["frame"] = fmt["frame"]
    fmt["answers"] = answers
    return fmt, look


def identity(answers: dict, look: dict) -> str:
    """What the pictures were drawn from: the answers that decide drawing,
    any words of the user's, the palette and the notes."""
    basis = json.dumps([{q: answers.get(q) for q in DRAWN_BY}, answers.get("custom") or {},
                        look.get("palette"), look.get("notes")], sort_keys=True)
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def composited(fmt: dict) -> bool:
    return fmt.get("engine") == "compositor"


# --- words for people ------------------------------------------------------------

def _phrase(qid: str, answers: dict) -> str:
    oid = answers.get(qid)
    if not oid:
        return ""
    phrase = q_option(qid, oid).get("phrase", "")
    return phrase.replace("{custom}", (answers.get("custom") or {}).get(qid, "")).strip()


def summary(answers: dict) -> str:
    """The style in a sentence: "Explained with objects on a tabletop seen
    from above, in felt, with cute stubby round people; cute and playful,
    in stop-motion, labelled on handwritten tags." """
    head = ", ".join(p for p in (_phrase("approach", answers), _phrase("stage", answers),
                                 _phrase("material", answers)) if p)
    extras = [p for p in (_phrase("people", answers), _phrase("presenter", answers)) if p]
    tail = [p for p in (_phrase("mood", answers), _phrase("motion", answers),
                        _phrase("words", answers)) if p]
    sentence = head + (", " + ", ".join(extras) if extras else "")
    if tail:
        sentence += "; " + ", ".join(tail)
    sentence = sentence.strip()
    return (sentence[:1].upper() + sentence[1:] + ".") if sentence else ""


def title(answers: dict) -> str:
    """A short name: "Felt tabletop", "Chalk chalkboard" reads badly, so
    the material and the stage's label, trimmed."""
    material = re.split(r"[,(]", q_option("material", answers.get("material", ""))
                        .get("label", ""))[0].strip()
    if answers.get("material") == "custom":
        material = (answers.get("custom") or {}).get("material", "Custom")[:30]
    stage = q_option("stage", answers.get("stage", "")).get("label", "")
    stage = re.split(r"[,(]", stage)[0].strip()
    return f"{material}: {stage.lower()}" if material and stage else material or stage


# --- starting points -------------------------------------------------------------

@lru_cache(maxsize=1)
def starting_points() -> list:
    if not STARTING_POINTS_PATH.exists():
        return []
    data = yaml.safe_load(STARTING_POINTS_PATH.read_text(encoding="utf-8")) or {}
    return data.get("styles") or []


def starting_point(sid: str) -> dict:
    return next((s for s in starting_points() if s["id"] == sid), None)


def for_browser() -> dict:
    """The grammar as the builder needs it: questions, options (without
    the engines' prompt text, but with what the page shows or decides by:
    the engine, a host, a mood's energy and palettes), conditions and
    defaults."""
    out = []
    for q in questions():
        options = []
        for o in q["options"]:
            option = {k: o[k] for k in ("id", "label", "hint", "phrase", "when", "not", "custom")
                      if k in o}
            option.update({k: v for k, v in (o.get("sets") or {}).items() if k in BROWSER_SETS})
            options.append(option)
        out.append({"id": q["id"], "short": q.get("short", q["id"]), "ask": q["ask"],
                    "defaults": q.get("defaults") or [], "options": options})
    return {"questions": out}


BROWSER_SETS = ("engine", "avatar", "energy", "palette", "palettes")
