"""
A channel's public descriptions, written for it (decision 058): the
YouTube "About" text, the TikTok and Instagram bios, a tagline, and the
links that go with them.

Setting up the socials meant writing the same pitch four times by hand and
remembering every link. One short model call (about a cent) writes the
words from what the channel already knows about itself: its name, its host
brief and its topics. The links are never written by the model. They're
put in from the channel's own settings each time the text is shown, so
they can't be wrong or go stale: where the channel lives (YouTube, TikTok,
Instagram), and how to support it (Patreon, merch, affiliate picks, with
the disclosure those need).

The words are kept in `channels/<key>/profile.json` and are the owner's to
edit; the links are not stored in them.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import CHANNELS_DIR

log = get_logger(__name__)

# Each platform's own limits.
YOUTUBE_ABOUT_MAX = 1000
TIKTOK_BIO_MAX = 80
INSTAGRAM_BIO_MAX = 150
TAGLINE_MAX = 60
KEYWORDS_MAX = 480
FTC_AFFILIATE_DISCLOSURE = "As an Amazon Associate I earn from qualifying purchases."

SYSTEM = """
You write a content channel's public descriptions for YouTube, TikTok and
Instagram. You're given its name, the brief its host is written to, and its
topics. Write from what's given; don't invent facts about the channel
(awards, numbers, a history, a team, a schedule it hasn't said).

- `tagline`: a short line for the channel banner, at most 60 characters.
  Says what a viewer gets, plainly. No hashtags, no emoji.
- `about`: the YouTube channel's "About" text, two or three short
  paragraphs, at most 800 characters, British English. The first sentence
  is the one that shows in search results, so it says what the channel is
  and who it's for. Then what's in it and what to expect. End with a
  friendly nudge to subscribe, in your own words. No links, no hashtags, no
  emoji, no headings.
- `tiktok_bio`: at most 80 characters. What it is and a reason to follow.
- `instagram_bio`: at most 150 characters. The same, with room for one
  or two line breaks and at most one emoji.
- `keywords`: 8 to 12 search keywords or short phrases for the YouTube
  channel, lower case, no hashtags.

Keep the channel's own voice: warm and plain-spoken where its brief is,
dry where it is. Never oversell, never use "ultimate" or "game-changing".
""".strip()

SCHEMA = {"type": "object", "properties": {
    "tagline": {"type": "string"}, "about": {"type": "string"}, "tiktok_bio": {"type": "string"},
    "instagram_bio": {"type": "string"}, "keywords": {"type": "array", "items": {"type": "string"}}},
    "required": ["tagline", "about", "tiktok_bio", "instagram_bio", "keywords"],
    "additionalProperties": False}


def path_for(channel_key: str):
    return CHANNELS_DIR / channel_key / "profile.json"


def load(channel_key: str) -> dict:
    """The saved words, or {} if none have been written."""
    try:
        return json.loads(path_for(channel_key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(channel_key: str, data: dict) -> None:
    path = path_for(channel_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _clip(text: str, limit: int) -> str:
    """At most `limit` characters, cut at a word, never mid-word."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return cut or text[:limit]


def _topics(channel) -> list:
    from core import curriculum
    try:
        if curriculum.exists(channel.key):
            titles = [t["title"] for t in curriculum.load(channel.key)["topics"] if t.get("title")]
            if titles:
                return titles[:30]
    except Exception:  # noqa: BLE001 - the description can be written without the plan
        log.debug("couldn't read the topic plan for the profile", exc_info=True)
    return list(channel.topics or [])[:30]


def clean(data: dict) -> dict:
    """What the model returned, held to each platform's limits."""
    keywords, total = [], 0
    for word in data.get("keywords") or []:
        word = " ".join(str(word).replace("#", "").split()).lower()
        if word and word not in keywords and total + len(word) + 1 <= KEYWORDS_MAX:
            keywords.append(word)
            total += len(word) + 1
    return {"tagline": _clip(data.get("tagline", ""), TAGLINE_MAX),
            "about": _clip(data.get("about", ""), YOUTUBE_ABOUT_MAX),
            "tiktok_bio": _clip(data.get("tiktok_bio", ""), TIKTOK_BIO_MAX),
            "instagram_bio": _clip(data.get("instagram_bio", ""), INSTAGRAM_BIO_MAX),
            "keywords": keywords}


def generate(channel) -> dict:
    """Write the descriptions for a channel (one cheap model call), keep
    them, and return them."""
    from pipeline.llm import SystemBlock, call_json
    topics = _topics(channel)
    brief = (f"Name: {channel.channel_display_name or channel.key}\n"
             f"Kind: {'a pub quiz: rounds of questions with a countdown' if channel.format == 'quiz' else 'short narrated videos'}\n"
             f"Topics: {', '.join(topics) if topics else '(not set yet)'}\n\n"
             f"The brief its host is written to:\n{channel.style_prompt or '(none)'}")
    data = call_json([SystemBlock(SYSTEM, cacheable=False)], brief, SCHEMA, operation="channel_profile",
                     max_tokens=3000, effort="low")
    words = clean(data)
    if not words["about"] or not words["tagline"]:
        raise PipelineError("empty profile", user_message="The description came back empty. Try again.")
    words["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(channel.key, words)
    return words


def update(channel_key: str, edits: dict) -> dict:
    """Keep the owner's edits to the words (held to the platform limits)."""
    data = load(channel_key)
    data.update({k: v for k, v in clean({**data, **edits}).items() if k in edits})
    save(channel_key, data)
    return data


# --- the links ---------------------------------------------------------------

def links(channel) -> dict:
    """Where the channel lives and how to support it, from its settings:
    {"find": [(label, url)], "support": [(label, url)], "missing": [label]}.
    `missing` is what would improve the text if it were set."""
    socials, money = channel.socials, channel.monetization
    find = [(label, url.strip()) for label, url in (
        ("YouTube", socials.youtube_url), ("TikTok", socials.tiktok_url),
        ("Instagram", socials.instagram_url)) if (url or "").strip()]
    support = []
    if (money.patreon_url or "").strip():
        support.append(("Patreon", money.patreon_url.strip()))
    if (money.merch_url or "").strip():
        support.append(("Merch", money.merch_url.strip()))
    for link in money.affiliate_links or []:
        if (link.get("url") or "").strip():
            support.append((link.get("label") or "Our picks", link["url"].strip()))
    missing = [label for label, url in (("YouTube channel link", socials.youtube_url),
                                        ("TikTok link", socials.tiktok_url),
                                        ("Instagram link", socials.instagram_url)) if not (url or "").strip()]
    return {"find": find, "support": support, "missing": missing,
            "affiliate": bool(money.affiliate_links)}


def about_with_links(channel, words: dict) -> str:
    """The YouTube About text with the channel's links under it. (Its own
    YouTube link isn't repeated: it's the page the text is on.)"""
    found = links(channel)
    parts = [words.get("about", "").strip()]
    elsewhere = [f"{label}: {url}" for label, url in found["find"] if label != "YouTube"]
    if elsewhere:
        parts.append("Find us:\n" + "\n".join(elsewhere))
    if found["support"]:
        parts.append("Support the channel:\n" + "\n".join(f"{label}: {url}" for label, url in found["support"]))
    if found["affiliate"]:
        parts.append(FTC_AFFILIATE_DISCLOSURE)
    return "\n\n".join(p for p in parts if p)


def bio_link(channel) -> str:
    """The one link a TikTok or Instagram bio can carry: the YouTube
    channel, where the full videos and the other links are."""
    return (channel.socials.youtube_url or "").strip()
