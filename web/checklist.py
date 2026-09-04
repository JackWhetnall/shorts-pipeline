"""
The launch checklist: one definition, used by the home page, the channel
dashboard, and the scheduler.

Built fresh from real state every time it's asked for — there is no
stored "is this done" flag anywhere, so it can never drift out of sync
with what's actually true. The one exception is manual overrides, which
are a deliberate "I'm skipping this one" rather than a claim that it's
done, and render differently for exactly that reason.

Item ids are stable and independent of their labels, because they key the
override list and appear in URLs. Rewording a label must not silently
un-skip an item.

No Flask import: links are attached by the web layer, so the scheduler
can ask "how many items are outstanding" without an application context.
"""

from __future__ import annotations

from dataclasses import dataclass

from core import assets, gallery, logos

# Order here IS checklist order, and matches the setup wizard's steps
# with "first video" appended — that one sits outside the wizard.
ITEM_IDS = (
    "logo", "youtube", "tiktok", "instagram", "patreon",
    "merch_logo", "merch_store", "affiliate", "first_video",
)

# What a channel genuinely needs before it can publish, as opposed to
# what it might want eventually.
#
# These used to be one list, and all nine gated whether a channel counted
# as "live" — so a channel that will never have a Patreon had to be
# manually marked done to escape "Setting up". Two of the real channel's
# items were already overridden that way, which is the system asking to
# be told a small lie. Splitting them removes the need.
ESSENTIAL_IDS = ("logo", "youtube", "first_video")
OPTIONAL_IDS = tuple(i for i in ITEM_IDS if i not in ESSENTIAL_IDS)

LABELS = {
    "logo": "Create a logo",
    "youtube": "Add a YouTube link",
    "tiktok": "Add a TikTok link",
    "instagram": "Add an Instagram link",
    "patreon": "Add a Patreon link",
    "merch_logo": "Generate merch-ready logo versions",
    "merch_store": "Add a merch storefront link",
    "affiliate": "Add affiliate links",
    "first_video": "Create your first video",
}

# Which page fixes each item, and which section of it. The web layer turns
# these into URLs. Settings is one page now, so most of these are anchors
# into it rather than separate steps.
FIX_STEP = {
    "logo": ("logo_page", {}),
    "youtube": ("settings", {"_anchor": "section-publishing"}),
    "tiktok": ("settings", {"_anchor": "section-publishing"}),
    "instagram": ("settings", {"_anchor": "section-publishing"}),
    "patreon": ("settings", {"_anchor": "section-money"}),
    "merch_logo": ("logo_page", {}),
    "merch_store": ("settings", {"_anchor": "section-money"}),
    "affiliate": ("settings", {"_anchor": "section-money"}),
    "first_video": ("create_video", {}),
}


@dataclass
class Item:
    id: str
    label: str
    done: bool          # done for progress purposes: really done OR skipped
    manual: bool        # which of those it was


def real_state(channel, video_count: int) -> dict:
    """What is actually true, before overrides."""
    socials = channel.socials
    monetization = channel.monetization
    return {
        "logo": assets.has_logo(channel.key),
        "youtube": bool(socials.youtube_url),
        "tiktok": bool(socials.tiktok_url),
        "instagram": bool(socials.instagram_url),
        "patreon": bool(monetization.patreon_url),
        "merch_logo": logos.has_merch_variants(channel.key),
        "merch_store": bool(monetization.merch_url),
        "affiliate": bool(monetization.affiliate_links),
        "first_video": video_count > 0,
    }


def build(channel, video_count: int) -> list:
    real = real_state(channel, video_count)
    overrides = set(channel.manual_checklist_overrides)
    return [
        Item(id=item_id, label=LABELS[item_id],
             done=real[item_id] or item_id in overrides,
             manual=item_id in overrides and not real[item_id])
        for item_id in ITEM_IDS
    ]


def remaining_count(key: str, channel, state: dict = None) -> int:
    """Outstanding ESSENTIAL items — what actually gates going live."""
    state = state or gallery.video_state_counts(channel.output_dir)
    return sum(1 for item in build(channel, state["active"])
               if item.id in ESSENTIAL_IDS and not item.done)


def section_for(channel, checklist_remaining: int, checklist_total: int,
                published_count: int) -> str:
    """live / setup / future / archived.

    Only `archived` is stored. The other three are computed from real
    state every time, because moving a channel between them by hand was
    busywork for something that should just follow from what's true.

    "Live" needs a video actually published, which is stricter than the
    checklist's own "created a video" item — a channel with a rendered
    but unpublished video isn't live yet.
    """
    if channel.archived:
        return "archived"
    if checklist_remaining == 0 and published_count > 0:
        return "live"
    if checklist_remaining < checklist_total:
        return "setup"
    return "future"


def split(items: list) -> tuple:
    """(essentials, extras). The first list gates going live; the second
    is a to-do list you work through whenever you feel like it."""
    essentials = [i for i in items if i["id"] in ESSENTIAL_IDS]
    extras = [i for i in items if i["id"] in OPTIONAL_IDS]
    return essentials, extras
