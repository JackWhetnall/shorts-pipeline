"""
Two other titles for a film that's out, for its title test (decision
125). The owner, on 21 Oct: Why, Though?'s titles "all seem to be
identical format", and "i thought we were supposed to be testing
different ones?". They were tested only in a film's last phase, so none
had been.

Each film's title (A, as it went out) is tested against two that differ
in form, not only in words, so what's learnt is which kind of title
works for the channel:
- B, a statement: the film's most surprising true claim, said outright;
- C, to the viewer: speaks to them or opens a gap ("You've Never...",
  "Here's Why...").
One cheap call a film, about a tenth of a cent; a second only when a
title breaks the rules. A title is never cut to fit: the first ones were,
mid-word ("...never been mapped in detail, whi").
"""

from __future__ import annotations

from pipeline import llm

FORMATS = {"A": "as it went out", "B": "a statement", "C": "to the viewer"}
MAX_CHARS = 60
BANNED = ("you won't believe", "shocking", "insane")

SYSTEM = """
You write two alternative YouTube titles for a documentary that's already made and out. Both must
be true to what the film says and delivers: never a promise it doesn't keep, never a claim its
answer contradicts. Title Case, under 55 characters each, no emojis, no ALL CAPS words, no
"shocking", "insane" or "you won't believe".
- `statement`: the film's most surprising true claim, said outright as a fact. Not a question, and
  it doesn't start with "Why", "How" or "What".
- `viewer`: speaks to the viewer or opens a curiosity gap they need closed ("You've Been Doing X
  Wrong", "Here's Why X", "The X You Never Noticed"). It mustn't repeat the statement's wording.
""".strip()


def schema() -> dict:
    return {"type": "object", "properties": {"statement": {"type": "string"}, "viewer": {"type": "string"}},
            "required": ["statement", "viewer"], "additionalProperties": False}


def problems(text: str, title: str, label: str) -> list:
    """What's wrong with `text` as the `label` title of a film called
    `title`, or nothing."""
    words = [w for w in text.split() if len(w) > 3 and w[0].isalpha()]
    out = []
    if not text:
        out.append("it's missing")
    elif len(text) > MAX_CHARS:
        out.append(f"it's {len(text)} characters, over {MAX_CHARS}")
    if text and text.lower() == title.strip().lower():
        out.append("it's the film's own title")
    if any(b in text.lower() for b in BANNED):
        out.append("it uses a banned phrase")
    if words and sum(w[0].isupper() for w in words) < 0.7 * len(words):
        out.append("it isn't in Title Case")
    if label == "B" and text.split()[:1] and text.split()[0].lower() in ("why", "how", "what"):
        out.append("a statement can't start with Why, How or What")
    return out


def write(title: str, about: str) -> dict:
    """{"B": statement, "C": to the viewer} for a film called `title`
    whose story is `about` (its promise and hook). A title that still
    breaks the rules after a second try is left out."""
    prompt = f"The film's title: {title}\n\nWhat it says and shows: {about}"
    out = {}
    for attempt in range(2):
        data = llm.call_json(SYSTEM, prompt, schema(), operation="title_variants", model=llm.FAST_MODEL,
                             max_tokens=600, effort=None)
        wrong = {}
        for label, key in (("B", "statement"), ("C", "viewer")):
            if label in out:
                continue
            text = " ".join(str(data.get(key) or "").split())
            found = problems(text, title, label)
            if found:
                wrong[key] = found
            else:
                out[label] = text
        if not wrong:
            break
        prompt += "\n\nYour last answer broke the rules: " + "; ".join(
            f"`{k}`: {', '.join(v)}" for k, v in wrong.items()) + ". Write both again."
    return out


def about_film(video_path) -> str:
    """The film's promise and hook, from its production, for the writer."""
    from core import production
    from pipeline.documentary import thumbs
    try:
        _, data, _ = thumbs._film(video_path)
    except (OSError, ValueError, KeyError):
        return ""
    angle = production.chosen_angle(data) or {}
    outline = data.get("outline") or {}
    return " ".join(x for x in (angle.get("promise", ""), angle.get("hook", ""), outline.get("through_line", "")) if x)
