"""
The launch pipeline: every channel's path from an idea to publishing on
its own, as one ordered list with a single "you are here".

It replaced a launch checklist that was shaped around monetisation: its
essentials were "a logo", "a YouTube link pasted in" and "one video
exists", and the rest were Patreon, merch and affiliate links. A channel
could tick every box and still never publish, because nothing on it was
about a tested style, a connected account, a schedule or the checks'
track record. See docs/specs/launch-pipeline-and-publishing.md.

**Launch** stages run in order, and each is computed from what is
actually true every time it's asked. Nothing is stored as "done", so
this can't drift from reality. A stage can be skipped deliberately; that
is recorded (in `manual_checklist_overrides`, its historical name) and
shown as skipped, never as done.

**Grow** items come after launch and are done whenever they're worth
doing: cross-posting, Google's audit, then the money links, once
/insights shows an audience.

No Flask here: the web layer attaches links, so the scheduler and the
home page can ask the same questions without a request context.
"""

from __future__ import annotations

from dataclasses import dataclass

from core import assets, gallery, logos, youtube
from core.errors import PipelineError

# How many reviewed videos, and what share of agreement, the checks need
# before autopilot is offered. Five is enough to catch a gate that's
# plainly wrong; it's a first bar, not proof.
SHADOW_MIN_DECIDED = 5
SHADOW_MIN_AGREEMENT = 0.8


@dataclass
class Stage:
    id: str
    label: str
    who: str            # "you" or "app"
    done: bool
    skipped: bool = False
    detail: str = ""    # what's left, or what's true, in a sentence
    optional: bool = False

    @property
    def settled(self) -> bool:
        return self.done or self.skipped


LAUNCH = (
    ("content", "Say what the channel makes", "you"),
    ("sample", "Make and approve a first video", "you"),
    ("logo", "Choose a logo", "you"),
    ("youtube", "Connect the YouTube channel", "you"),
    ("plan", "Set when it publishes", "you"),
    ("shadow", "Let the automatic checks prove themselves", "app"),
    ("autopilot", "Switch on automatic publishing", "you"),
)

GROW = (
    ("tiktok", "Post to TikTok (hand-off to your phone)", "you"),
    ("instagram", "Post to Instagram (hand-off to your phone)", "you"),
    ("audit", "Pass Google's API audit, so uploads go out public", "you"),
    ("patreon", "Add a Patreon link", "you"),
    ("merch_logo", "Make merch-ready logo versions", "you"),
    ("merch_store", "Add a merch storefront link", "you"),
    ("affiliate", "Add affiliate links", "you"),
)

STAGE_IDS = tuple(i for i, _, _ in LAUNCH) + tuple(i for i, _, _ in GROW)


def gate_agreement(channel) -> tuple:
    """(decided, agreed) over videos the gate judged and you then decided:
    agreed when it passed one you published, or held one you discarded."""
    decided = agreed = 0
    for video in gallery.list_videos(channel.output_dir):
        gate = (video.get("report") or {}).get("gate")
        if not gate:
            continue
        # Approved by the checks themselves isn't a second opinion.
        if video["links"].get("approved_by") == "checks":
            continue
        if video["out"] or video["queued"]:
            decided += 1
            agreed += bool(gate.get("passed"))
        elif video["discarded"]:
            decided += 1
            agreed += not gate.get("passed")
    return decided, agreed


def stages(channel, state: dict = None) -> tuple:
    """(launch, grow): lists of Stage, launch in order."""
    state = state or gallery.video_state_counts(channel.output_dir)
    skipped = set(channel.manual_checklist_overrides)
    connection = youtube.connection(channel.key)
    plan = channel.publishing

    try:
        channel.validate()
        content_ok, content_detail = True, ""
    except PipelineError as exc:
        content_ok, content_detail = False, exc.user_message

    approved = state["published"] + state["queued"]
    decided, agreed = gate_agreement(channel)
    shadow_ok = decided >= SHADOW_MIN_DECIDED and agreed >= SHADOW_MIN_AGREEMENT * decided

    if connection["connected"] and not connection["stats"]:
        youtube_detail = "Connected, but reconnect once so its statistics can be read."
    elif connection["connected"]:
        youtube_detail = f"Connected as {connection['account'] or 'a Google account'}."
    else:
        youtube_detail = "Create the channel on YouTube, then connect it here."

    launch_facts = {
        "content": (content_ok, content_detail or "Voice, style and topics are set."),
        "sample": (approved > 0,
                   f"{approved} approved or published." if approved else
                   "Make a video, watch it, and approve it (or publish it yourself)."),
        "logo": (assets.has_logo(channel.key), ""),
        "youtube": (connection["connected"] and connection["stats"], youtube_detail),
        "plan": (plan.enabled,
                 (f"Publishes at {', '.join(plan.slots) or 'once approved'}, "
                  f"keeping {plan.buffer} ready.") if plan.enabled else
                 "Pick publishing times and how many videos to keep ready."),
        "shadow": (shadow_ok,
                   f"{decided} of {SHADOW_MIN_DECIDED} reviewed; the checks agreed with you on "
                   f"{agreed}." if not shadow_ok else
                   f"The checks agreed with you on {agreed} of {decided}."),
        "autopilot": (channel.autopilot.mode == "when_clean",
                      "Clean videos queue themselves; flagged ones wait for you."
                      if channel.autopilot.mode == "when_clean" else
                      "Clean videos would queue themselves; flagged ones would still wait."),
    }
    socials, money = channel.socials, channel.monetization
    grow_facts = {
        "tiktok": (plan.handoff_tiktok or bool(socials.tiktok_url), ""),
        "instagram": (plan.handoff_instagram or bool(socials.instagram_url), ""),
        "audit": (False, "Mark it done once Google has approved the audit."),
        "patreon": (bool(money.patreon_url), ""),
        "merch_logo": (logos.has_merch_variants(channel.key), ""),
        "merch_store": (bool(money.merch_url), ""),
        "affiliate": (bool(money.affiliate_links), ""),
    }

    def build(defs, facts, optional):
        out = []
        for stage_id, label, who in defs:
            done, detail = facts[stage_id]
            out.append(Stage(stage_id, label, who, done=done,
                             skipped=(stage_id in skipped and not done),
                             detail=detail, optional=optional))
        return out

    return build(LAUNCH, launch_facts, False), build(GROW, grow_facts, True)


def current(launch: list):
    """The first launch stage not yet done or skipped, or None when the
    channel is fully launched."""
    return next((s for s in launch if not s.settled), None)


def section(channel, launch: list, state: dict) -> str:
    """live / setup / future / archived, for the home page."""
    if channel.archived:
        return "archived"
    if state["published"] > 0 or current(launch) is None:
        return "live"
    if any(s.done for s in launch):
        return "setup"
    return "future"
