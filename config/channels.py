"""
One entry per channel, defined in channels.json (this file loads and
merges it) — everything downstream (content source, voice, pacing, style,
branding) is driven by that config, not code. Footage is not per-channel —
all channels draw from the shared, tagged library in footage/ (see
footage_library.py and CLAUDE.md).

Channel data lives in channels.json, not here, so it can be edited
through the web GUI (webapp/) without touching Python. This module is
just the loader/merge layer: it applies DEFAULT_PACING/DEFAULT_STYLE/
DEFAULT_AVOID_IMAGERY on top of whatever channels.json specifies, exactly
as it always has for the in-code defaults.

`topic_demo` in channels.json is a throwaway smoke-test channel proving
the topic-driven path end to end — not a real channel, safe to delete
once a real topic-driven channel replaces it.

Two content modes:
- "static_corpus": a fixed source text is fetched (quote_source.SOURCES)
  and read aloud; "source" names which one. The read-aloud citation
  ("Job 1:8") is optional per-quote metadata, not a channel setting.
- "topic": no fixed text — script_gen generates every segment from a
  topic (rotated from "topics") and the channel's style_prompt, which
  carries the actual format ("write dad jokes about...", "explain one
  scientific concept about...") — the code has no format-specific logic
  at all, it's entirely config.

"pacing" controls timing/rhythm (a reflective-quote channel wants slower,
lingering shots; a jokes channel wants a tighter setup/pause/punchline
beat) and "style" controls caption/outro visuals — both default to the
values this pipeline already used before they were per-channel, so an
existing channel that doesn't override them renders identically.

"voice" is an ElevenLabs voice ID (requires ELEVENLABS_API_KEY — see
README.md), not a name. The IDs in channels.json are ElevenLabs' own
stable premade voices, used only as distinct placeholders per channel —
swap in your own picks from https://elevenlabs.io/app/voice-library.
"""

import json
from pathlib import Path

DEFAULT_PACING = {
    "pause_after_first_segment": 0.7,
    "pause_after_citation": 0.5,
    "pause_between_segments": 0.4,
    "max_shot_seconds": 5.0,
    "crossfade": 0.5,
    "outro_seconds": 3.0,
    "caption_max_group_size": 4,
    "caption_pause_gap_threshold": 0.25,
    "segment_count": 3,   # static_corpus: analysis segments beyond the quote itself; topic: total segments
}

DEFAULT_STYLE = {
    "font_size": 68,
    "base_color": "#FFFFFF",
    "highlight_color": "#FFD400",
    "stroke_color": "#000000",
    "stroke_width": 4,
    "outro_bg_color": (10, 10, 14, 255),
    "outro_title_color": "#FFFFFF",
    "outro_subtext_color": "#FFD400",
}

# Footage is shared across all channels (see module docstring), which means
# a clip that's a fine match by theme/keywords can still be the WRONG
# imagery for a specific channel's audience — e.g. a clip literally
# described as an outdoor Islamic prayer service can score well against a
# Bible verse about "prayer" or "devotion" on theme alone, but mixing that
# imagery into a Christian-audience channel is a real problem, not a
# nitpick. "avoid_imagery" is a list of words/phrases checked against each
# candidate clip's description (case-insensitive substring) before it's
# even offered to the matching call, plus stated explicitly in the prompt
# as a hard disqualifier regardless of thematic fit — see
# footage_library.pick_clips_for_shots. Empty by default; every channel
# should set a sensible list for what it should never show (a science
# channel, for instance, would set something like ["church", "mosque",
# "prayer", "worship", "religious ceremony"] to keep religious imagery out
# of secular science content).
DEFAULT_AVOID_IMAGERY = []

# ElevenLabs' own voice_settings.speed (1.0 = normal, <1 slower, >1
# faster) — see tts_captions.generate_voiceover. Left at ElevenLabs'
# default so a channel that doesn't set it behaves exactly as before this
# was added. webapp/voice_lab.py exercises this directly for auditioning
# before you commit a value to a channel.
DEFAULT_SPEED = 1.0

# Plain config, pasted in manually — this pipeline never creates a
# Patreon page, merch store, or Amazon Associates account on your behalf
# (see webapp/templates/_channel_form.html's "setting up monetization"
# checklist for where those actually get created). Per-channel only, not
# a shared/global list — a science channel and a Bible channel shouldn't
# necessarily promote the same products. affiliate_links is a small list
# of {"label", "url"} — the label is what shows in the description
# ("My favorite journal: <url>"); falls back to the bare URL if unset.
DEFAULT_MONETIZATION = {
    "patreon_url": "",
    "merch_url": "",
    "affiliate_links": [],
}

# The channel's own social profile links (not a stock-footage/monetization
# concept) - set through the webapp's setup wizard's "socials" step, shown
# on the channel dashboard. Purely informational/organizational for now
# (no video-assembly or description-generation code reads these) - just a
# place to keep track of where this channel actually lives.
DEFAULT_SOCIALS = {
    "youtube_url": "",
    "tiktok_url": "",
    "instagram_url": "",
}

# An optional second video segment (after the branding outro) surfacing
# CTAs for the monetization links above. Each CTA's own "enabled" flag is
# the single source of truth for "this is actively being promoted" — used
# by BOTH the end-screen visual (video_assemble.build_video, only if
# end_screen["enabled"] is also true) AND the auto-generated description
# (description_gen.generate_description, regardless of whether the video
# segment itself is on) — so a link can be promoted in the description
# without necessarily spending extra video seconds on it, or vice versa.
# A CTA only actually renders anywhere if its flag is true AND the
# matching monetization field is non-empty — an enabled-but-empty CTA is
# silently skipped rather than showing a blank line.
DEFAULT_END_SCREEN = {
    "enabled": False,
    "duration_seconds": 3.0,
    "ctas": {
        "patreon": {"enabled": False, "text": "Support us on Patreon"},
        "merch": {"enabled": False, "text": "Check out our merch"},
        "affiliate": {"enabled": False, "text": "Shop our picks below"},
    },
}

# Lifecycle/organization for the web GUI's home page — purely a display
# grouping, nothing in the pipeline itself reads this. "setup" is the
# default for every new channel (including ones created as a placeholder
# for a "future" idea — there's no separate lightweight creation path,
# you just create it normally and move it once it's ready). Valid values:
# "live", "setup", "future", "archived".
DEFAULT_STATUS = "setup"

CHANNELS_JSON_PATH = Path(__file__).parent / "channels.json"


def _merge_end_screen(override: dict = None) -> dict:
    override = override or {}
    ctas_override = override.get("ctas") or {}
    ctas = {
        key: {**default_cta, **(ctas_override.get(key) or {})}
        for key, default_cta in DEFAULT_END_SCREEN["ctas"].items()
    }
    return {**DEFAULT_END_SCREEN, **override, "ctas": ctas}


def _channel(pacing=None, style=None, avoid_imagery=None, speed=None,
             monetization=None, end_screen=None, socials=None, status=None, **fields):
    """Merges per-channel pacing/style/avoid_imagery/speed/monetization/
    end_screen/socials/status overrides onto the shared defaults."""
    merged_style = {**DEFAULT_STYLE, **(style or {})}
    # channels.json can only store lists, but PIL wants a tuple for a
    # color — round-trips fine as long as this is fixed on the way back in.
    if isinstance(merged_style.get("outro_bg_color"), list):
        merged_style["outro_bg_color"] = tuple(merged_style["outro_bg_color"])
    fields["pacing"] = {**DEFAULT_PACING, **(pacing or {})}
    fields["style"] = merged_style
    fields["avoid_imagery"] = list(DEFAULT_AVOID_IMAGERY) + list(avoid_imagery or [])
    fields["speed"] = DEFAULT_SPEED if speed is None else speed
    fields["monetization"] = {**DEFAULT_MONETIZATION, **(monetization or {})}
    fields["end_screen"] = _merge_end_screen(end_screen)
    fields["socials"] = {**DEFAULT_SOCIALS, **(socials or {})}
    fields["status"] = status or DEFAULT_STATUS
    return fields


def resolve_active_ctas(monetization: dict, end_screen: dict) -> list:
    """The single place that decides which monetization CTAs are actually
    "active" — enabled AND pointing at something real. Both the end-screen
    video segment (video_assemble.build_video) and the auto-generated
    description (description_gen.generate_description) call this so they
    never disagree about which CTAs show. Returns, in a fixed
    patreon/merch/affiliate order, one dict per active CTA:
    {"type": "patreon"|"merch", "text": str, "url": str} or
    {"type": "affiliate", "text": str, "links": [{"label", "url"}, ...]}."""
    ctas = end_screen.get("ctas", {})
    active = []

    patreon = ctas.get("patreon", {})
    if patreon.get("enabled") and monetization.get("patreon_url"):
        active.append({
            "type": "patreon",
            "text": patreon.get("text") or DEFAULT_END_SCREEN["ctas"]["patreon"]["text"],
            "url": monetization["patreon_url"],
        })

    merch = ctas.get("merch", {})
    if merch.get("enabled") and monetization.get("merch_url"):
        active.append({
            "type": "merch",
            "text": merch.get("text") or DEFAULT_END_SCREEN["ctas"]["merch"]["text"],
            "url": monetization["merch_url"],
        })

    affiliate = ctas.get("affiliate", {})
    affiliate_links = monetization.get("affiliate_links") or []
    if affiliate.get("enabled") and affiliate_links:
        active.append({
            "type": "affiliate",
            "text": affiliate.get("text") or DEFAULT_END_SCREEN["ctas"]["affiliate"]["text"],
            "links": affiliate_links,
        })

    return active


def load_channels() -> dict:
    """Rebuilds CHANNELS fresh from channels.json. Call this directly
    (rather than importing the module-level CHANNELS name) anywhere a
    just-saved edit needs to be visible without a process restart — the
    webapp does this on every request."""
    with open(CHANNELS_JSON_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return {key: _channel(**entry) for key, entry in raw.items()}


CHANNELS = load_channels()
