"""
A long-form channel's setup, as a list of steps that say whether they're
done (decision 076).

The owner, setting up History Unmystified's first film: "it is unclear if
i have achieved doing those settings, and if so do i need to then
actually click the create video button or not." So the settings page and
Productions both show the same short list, worked out from real state:
each step done or not, the one to do next, and what it unblocks. Steps
marked optional never hold anything up.

Pure apart from reading state; the pages turn each step's id into a link.
"""

from __future__ import annotations

from dataclasses import dataclass

from core import curriculum, production
from core.channels import LONG_FORM_PICTURES, LONG_FORM_PICTURES_READY


@dataclass
class Step:
    id: str             # also where its link goes: see the templates
    label: str
    done: bool
    detail: str = ""    # what's set, or what to do
    optional: bool = False
    blocked: bool = False   # can't be done yet, whatever the owner does


def steps(channel) -> list:
    """Every setup step, in order, for a long-form channel."""
    out = []
    out.append(Step("about", "Say what the films are about and how they're told",
                    bool((channel.style_prompt or "").strip()),
                    "Settings, Channel: the writing brief."))
    try:
        channel.validate()
        voice_ok = True
    except Exception:  # noqa: BLE001 - validate() says why elsewhere; here it's only done or not
        voice_ok = bool((channel.voice or "").strip())
    out.append(Step("voice", "Choose the narrator's voice", voice_ok and bool(channel.voice),
                    "Settings, Voice."))

    pictures = channel.documentary.pictures
    if pictures not in LONG_FORM_PICTURES_READY:
        out.append(Step("look", "Choose the look", False,
                        f"{LONG_FORM_PICTURES[pictures]} films aren't built yet. Switch the channel to "
                        f"{LONG_FORM_PICTURES['drawn'].lower()} in Settings, Films, or wait for them.",
                        blocked=True))
    else:
        out.append(Step("look", "Choose the look", bool(channel.animation.style),
                        "Settings, Look: every picture in every film is drawn in it."))
        out.append(Step("frames", "See the look on this channel's world", _frames_drawn(channel),
                        "Settings, Look: Draw style frames (about 3 cents) and pick one. If you skip "
                        "this, they're drawn with the first storyboard.", optional=True))

    pending = curriculum.subtopics(channel.key, status="pending") if curriculum.exists(channel.key) else []
    out.append(Step("films", "Have films in the plan", bool(pending),
                    f"{len(pending)} waiting on the Plan tab." if pending else "Plan tab: add topics and films."))

    started = [d for d in production.all_for(channel.key) if _started(d)]
    out.append(Step("first", "Start the first film", bool(started),
                    "Productions: open the first film and press Pitch angles. Nothing is made, "
                    "or spent, until you do; each stage then waits for you to approve it."))

    from core import youtube
    try:
        connected = youtube.connection(channel.key).get("connected", False)
    except Exception:  # noqa: BLE001 - a setup list must always render
        connected = False
    out.append(Step("youtube", "Connect its YouTube channel", connected,
                    "Settings, Publishing. Only needed once a film is ready to go out.", optional=True))
    plan = channel.publishing
    out.append(Step("slots", "Choose when films go out", bool(plan.enabled and plan.long_slots and plan.long_weekdays),
                    "Settings, Publishing. Approved films wait for these times; nothing goes out unapproved.",
                    optional=True))
    return out


def next_step(channel) -> Step | None:
    """The first step not done that isn't optional, or None when ready."""
    return next((s for s in steps(channel) if not s.done and not s.optional), None)


def _started(data: dict) -> bool:
    return any(production.state(data, s) != "todo" for s in production.STAGES)


def _frames_drawn(channel) -> bool:
    if not channel.animation.style:
        return False
    try:
        from pipeline.animation import bible, style
        _, look = style.compile(channel.animation, frame="wide")
        return bool(bible.current(channel.key, look) and bible.frames(channel.key, look))
    except Exception:  # noqa: BLE001 - optional step; unknown reads as not done
        return False
