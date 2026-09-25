"""
Filling a template: the model writes its slots and times each beat to a
spoken word; this checks the result and turns it into a clip.

One small Sonnet call per template scene (about a cent), with the whole
narration for context, then validation: required slots present, text
within each template's limits (a slot that runs long is a problem to fix,
not something to shrink invisibly), beats on real words and in order.
One repair round if needed. Nothing may enter before the opening hook
text has gone (decision 039); any beat that does is held back.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline.llm import SystemBlock, call_json
from pipeline.templates import library, page

log = get_logger(__name__)

FILL_MAX_TOKENS = 4000
FILL_EFFORT = "low"
ANIM_TAIL = 0.6          # a beat's entrance takes about this long
HOLD_BACK_STAGGER = 0.2

GUIDE = """
You fill in an animated explainer template for a short vertical video.
The template is already designed; you only write its words, numbers and
icon names, and say on which spoken word each part appears.

Rules:
- Every word and number on screen matches what the narration says. Never
  invent a statistic; if the narration gives no number, don't show one.
- Short, punchy wording: the limits in the slot guide are maximums, not
  targets. Title case is not needed; write like a good caption.
- Icons are plain emoji-style names ("dog", "person", "brain", "light
  bulb", "stopwatch", "globe showing europe-africa"): common names only.
- beats: for each beat name given, the index of the spoken word on which
  it should appear. In order, on the word that says it, never later than
  the word after it.

Answer with one JSON object and nothing else:
{"slots": {...}, "beats": {"beat name": word index, ...}}
""".strip()


def _numbered(words: list) -> str:
    return " ".join(f"{i}:{w}@{t:.2f}" for i, (w, t) in enumerate(words))


def write(name: str, brief: str, words: list, narration: str,
          previous: dict = None, problems: list = None) -> dict:
    spec = library.TEMPLATES[name]
    user = [f"The whole video's narration, for context:\n{narration}",
            f"Template: {name}. {spec['use']}\nSlots: {spec['slots']}",
            f"What this scene should show: {brief}",
            f"Spoken words for this scene (index:word@seconds):\n{_numbered(words)}"]
    if previous is not None:
        user.append("Your previous answer:\n" + json.dumps(previous)
                    + "\n\nFix these problems and keep what works:\n- " + "\n- ".join(problems or []))
    return call_json([SystemBlock(GUIDE, cacheable=True)], "\n\n".join(user), None,
                     operation="template_fill" if previous is None else "template_repair",
                     max_tokens=FILL_MAX_TOKENS, effort=FILL_EFFORT)


# Longest text allowed per slot, in characters: past this a template's
# fitting would shrink the text too far to read on a phone.
LIMITS = {"title": 48, "kicker": 40, "caption": 80, "verdict": 64, "text": 60, "label": 24,
          "value": 28, "myth": 90, "fact": 90, "term": 28, "definition": 120, "example": 90,
          "when": 14, "note": 70, "who": 50}
QUOTE_LIMIT = 200


def _texts(slots, path=""):
    if isinstance(slots, dict):
        for k, v in slots.items():
            yield from _texts(v, k)
    elif isinstance(slots, list):
        for v in slots:
            yield from _texts(v, path)
    elif isinstance(slots, str):
        yield path, slots


def validate(name: str, raw: dict, words: list, duration: float) -> tuple:
    """(slots, times, problems)."""
    spec = library.TEMPLATES[name]
    slots = dict(raw.get("slots") or {})
    problems = [f"Missing slot {key!r}." for key in spec["required"] if not slots.get(key)]
    for key, text in _texts(slots):
        limit = QUOTE_LIMIT if name == "quote" and key == "text" else LIMITS.get(key)
        if limit and len(text) > limit:
            problems.append(f"{key!r} is {len(text)} characters: keep it under {limit}: {text!r}")
    for key in ("items", "steps", "events", "bars", "lines"):
        if key in slots and not (isinstance(slots[key], list) and len(slots[key]) >= 1):
            problems.append(f"{key!r} needs a list of entries.")
    try:
        beat_names = spec["beats"](slots)
    except Exception:  # noqa: BLE001 - malformed slots are reported above
        beat_names = []
    times = _times(beat_names, raw.get("beats") or {}, words, duration, problems)
    return slots, times, problems


def _times(names: list, beats: dict, words: list, duration: float, problems: list) -> dict:
    """Beat names to seconds from the scene's start. Missing or bad beats
    are spread between their neighbours rather than failing the scene."""
    latest = max(0.2, duration - 1.2)
    raw = []
    for name in names:
        w = beats.get(name)
        raw.append(words[w][1] if isinstance(w, int) and 0 <= w < len(words) else None)
    if any(v is None for v in raw) and names:
        known = [v for v in raw if v is not None]
        if not known:
            raw = [0.2 + i * (latest - 0.2) / max(1, len(names)) for i in range(len(names))]
        else:
            last = 0.2
            for i, v in enumerate(raw):
                if v is None:
                    nxt = next((x for x in raw[i + 1:] if x is not None), latest)
                    raw[i] = (last + nxt) / 2
                last = raw[i]
    out, previous = {}, 0.0
    for name, v in zip(names, raw):
        v = min(max(v, previous), latest)          # in order, and never past the end
        out[name] = round(v, 3)
        previous = v
    return out


def hold_back(times: dict, not_before: float) -> dict:
    """Beats before `not_before` (the hook text) moved just after it."""
    if not_before <= 0:
        return times
    early = sorted((t, k) for k, t in times.items() if t < not_before)
    for n, (_, key) in enumerate(early):
        times[key] = round(not_before + n * HOLD_BACK_STAGGER, 3)
    return times


def cues(name: str, times: dict) -> list:
    """The few sounds this template makes: its big moments only."""
    return [[round(times[beat] + 0.15, 3), kind, 0.8]
            for beat, kind in library.TEMPLATES[name]["sounds"].items() if beat in times]


def make(name: str, brief: str, words: list, duration: float, narration: str, style: dict,
         icon_folder: Path, out_stem: Path, tail: float, not_before: float = 0.0):
    """One filled template, rendered. Returns (clip, notes)."""
    from pipeline.scenes import render

    raw = write(name, brief, words, narration)
    slots, times, problems = validate(name, raw, words, duration)
    if problems:
        log.info(f"  [template] repairing {name}: {'; '.join(problems)[:240]}")
        raw = write(name, brief, words, narration, previous=raw, problems=problems)
        slots, times, problems = validate(name, raw, words, duration)
    missing = [p for p in problems if p.startswith("Missing slot")]
    if missing:
        raise PipelineError("; ".join(missing), user_message="A template couldn't be filled.")
    times = hold_back(times, not_before)
    total = round(duration + tail, 3)
    icons = page.icon_resolver(style, icon_folder)
    html = page.build(name, slots, times, style, total, icons)
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    out_stem.with_suffix(".json").write_text(json.dumps(
        {"template": name, "slots": slots, "times": times, "cues": cues(name, times)}, indent=1),
        encoding="utf-8")
    clip = render.render_page(html, total, out_stem.with_suffix(".mp4"))
    return clip, problems
