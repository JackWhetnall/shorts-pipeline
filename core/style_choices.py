"""
The fixed vocabulary behind the style & tone picker.

Setting up a channel used to mean inventing, from a blank textarea, a
paragraph of English that reliably steers a script generator toward a
specific voice — "so today we're going to learn how to use incense when
manifesting" is easy to *want* and hard to *specify*. This module is the
alternative: a small set of named, described choices that a drafting
call (`pipeline.style_gen.draft_candidates`) turns into real prompt text,
so the person setting up a channel is selecting rather than writing.

Three axes are required because they change the shape of a script the
most — everything else defaults to something reasonable and can be left
alone. Each option's description is shown to the person choosing AND fed
to the drafting call as-is; writing it once for both audiences is why
these read a little more explanatory than a typical UI label.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Option:
    key: str
    label: str
    description: str


@dataclass(frozen=True)
class Axis:
    key: str
    label: str
    required: bool
    options: tuple
    default: str        # option key used when this axis is left alone


AXES = (
    Axis("format", "Format", True, (
        Option("tutorial", "Sequential tutorial",
              "Walks through one thing to do, in order: \"first you'll..., "
              "then...\". Suits a series someone follows lesson to lesson."),
        Option("reveal", "Surprising reveal",
              "Opens with an intriguing claim or question, then explains it."),
        Option("myth_busting", "Myth-busting",
              "States a common belief, then corrects or complicates it."),
        Option("listicle", "Quick list",
              "Frames the video as a short numbered list of related points."),
        Option("personal_narrative", "Personal story",
              "Told as one person's own experience or discovery, first person."),
        Option("documentary", "Documentary narration",
              "Third person, observational, no direct address to the viewer."),
    ), "tutorial"),

    Axis("register", "Register", True, (
        Option("casual", "Casual",
              "Relaxed, informal wording, like talking to a friend."),
        Option("conversational", "Conversational",
              "Natural spoken English, friendly but not slangy."),
        Option("formal", "Formal",
              "Precise, considered wording; no slang or contractions."),
    ), "conversational"),

    Axis("personality", "Personality", True, (
        Option("intellectual", "Intellectual",
              "Assumes a curious, engaged audience willing to sit with "
              "nuance and detail."),
        Option("accessible", "Friendly & accessible",
              "Plain language, explains anything unfamiliar, no assumed "
              "background."),
        Option("gossipy", "Tabloid & gossipy",
              "Breathless, speculative, personality-driven — "
              "\"you won't believe...\"."),
        Option("deadpan", "Deadpan & dry",
              "Matter-of-fact, understated, lets the facts do the work."),
        Option("hype", "High-energy & hype",
              "Enthusiastic, exclamation-heavy, treats everything as exciting."),
    ), "accessible"),

    Axis("delivery", "Delivery", False, (
        Option("clean", "Clean narration",
              "Polished, no filler words — reads like an edited script."),
        Option("natural", "Natural speech",
              "Occasional \"so\", \"like\", \"you know\" — the way someone "
              "actually talks. Never \"um\" or \"err\" either way: those are "
              "audible hesitations, not word choices, and a scripted one "
              "reads as fake."),
    ), "clean"),

    Axis("epistemic", "How certain it sounds", False, (
        Option("confident", "Confident & factual",
              "States things as established fact. Right for a channel "
              "whose claims are checkable."),
        Option("hedged", "Hedged",
              "Acknowledges uncertainty — \"some believe\", \"it's thought "
              "that\"."),
        Option("suggestive", "Suggestive, not factual",
              "Deliberately never makes a falsifiable claim — offers, like "
              "a horoscope, rather than asserts."),
        Option("opinionated", "Opinionated",
              "Confident but explicitly subjective — \"here's why I "
              "think...\"."),
    ), "confident"),

    Axis("humor", "Humour", False, (
        Option("none", "None", "Played straight."),
        Option("dry", "Dry wit", "Occasional understated, ironic humour."),
        Option("playful", "Playful", "Light, upbeat jokes throughout."),
    ), "none"),

    Axis("english", "English", False, (
        Option("neutral", "Neutral / international", "No particular regional flavour."),
        Option("british", "British", "British spelling and phrasing."),
        Option("american", "American", "American spelling and phrasing."),
    ), "neutral"),

    Axis("hook", "Opening", False, (
        Option("needs_hook", "Needs a scroll-stopping opener",
              "A cold audience scrolling past — the first line has to earn "
              "the next five seconds."),
        Option("natural_start", "Can start naturally",
              "A warm audience already following a series — no need to "
              "manufacture a hook every time."),
    ), "needs_hook"),
)

AXES_BY_KEY = {a.key: a for a in AXES}
REQUIRED_AXES = tuple(a for a in AXES if a.required)
OPTIONAL_AXES = tuple(a for a in AXES if not a.required)


def resolve(choices: dict) -> dict:
    """Fill in defaults for any axis the picker left alone.

    `choices` is `{axis_key: option_key}` from the form; only required axes
    are guaranteed to be present. Unknown axis or option keys are dropped
    rather than trusted, since this dict reaches here from a browser.
    """
    resolved = {}
    for axis in AXES:
        picked = choices.get(axis.key)
        if picked not in {o.key for o in axis.options}:
            picked = axis.default
        resolved[axis.key] = picked
    return resolved


def describe(choices: dict) -> str:
    """The resolved choices as a short block of text for a drafting prompt:
    one line per axis, in the same words shown to the person who picked
    them, so the model is working from the same meaning they saw."""
    resolved = resolve(choices)
    lines = []
    for axis in AXES:
        option = next(o for o in axis.options if o.key == resolved[axis.key])
        lines.append(f"{axis.label}: {option.label} — {option.description}")
    return "\n".join(lines)
