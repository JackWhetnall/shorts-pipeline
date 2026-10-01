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
TAGLINE_MAX = 50
KEYWORDS_MAX = 480
FTC_AFFILIATE_DISCLOSURE = "As an Amazon Associate I earn from qualifying purchases."

SYSTEM = """
You write a YouTube channel's public descriptions: its "About" text and
its TikTok and Instagram bios. The reader is someone who has just found
the channel and is deciding in a few seconds whether it's for them. Write
what they get out of it, the way the person who runs the channel would
describe it to a friend.

Never describe how the videos are made or what's mechanically on screen:
no countdowns, clocks, timers, on-screen text, captions, narration,
voices, hosts "reading" anything, formats, editing, automation or AI.
Never make claims about the channel's own quality ("clean questions",
"unambiguous", "no trick wording", "well researched"). Those read like a
production spec, not a reason to watch. Say instead what it's like to
watch: what you'll be tested on, the feeling of it (getting one nobody
else in the room knew, the easy ones you're sure of, the hard ones you
argue about), who it's for, and that there's always a new one.

Don't invent facts about the channel: no awards, numbers of videos,
schedules, a team or a history it hasn't been given.

- `tagline`: for the channel banner, at most 50 characters. Says what a
  viewer gets, with a bit of personality. No hashtags or emoji.
- `about`: two or three short paragraphs, at most 700 characters, British
  English. The first sentence shows in search results: say plainly what the
  channel is and who it's for. End with an easy invitation to subscribe or
  play along, in your own words. No links, hashtags, emoji or headings.
- `tiktok_bio`: at most 80 characters. Punchy: what it is, why follow.
- `instagram_bio`: at most 150 characters, one or two short lines, at most
  one emoji.
- `keywords`: 8 to 12 things people would search for to find this kind of
  video, lower case, no hashtags.

An example of the register wanted, for an unrelated channel (don't reuse
its words): "Five-minute history for people who were bored by it at school.
Every video is one strange, true story: the emperor who declared war on
the sea, the town that danced itself to death. Pick one at random and see
if you can stop at one."
""".strip()

# Production talk that reads as a spec rather than a reason to watch. A
# reply using any of it is written again once.
LEAKS = ("countdown", "clock", "timer", "on-screen", "on screen", "onscreen", "caption", "narrat",
         "voice", "voiceover", "read aloud", "reads aloud", "read the way", "quizmaster would",
         " ai ", "a.i.", "artificial intelligence", "automated", "unambiguous", "trick wording",
         "clean question", "matching text")


def leaks(words: dict) -> list:
    """The production talk in the written words, if any."""
    text = " " + " ".join(str(words.get(k, "")) for k in ("tagline", "about", "tiktok_bio",
                                                            "instagram_bio")).lower() + " "
    return sorted({w.strip() for w in LEAKS if w in text})


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


def _what_it_is(channel) -> str:
    """The channel in a viewer's terms. Not its host brief: that is
    instructions for writing the videos (pacing, what's on screen), and
    given it, the model described the production ("a countdown clock,
    matching on-screen text") instead of the channel."""
    from core import curriculum
    lines = [f"Name: {channel.channel_display_name or channel.key}"]
    if channel.format == "quiz":
        from pipeline import quiz
        levels = quiz.labels(channel)
        lines.append("What it is: short pub-quiz rounds to play along with on your own or with "
                     "friends, one category at a time, with the answers given after each question.")
        if levels:
            lines.append(f"Rounds come at these difficulties: {', '.join(levels)}.")
    else:
        lines.append("What it is: short videos.")
    try:
        subject = curriculum.load(channel.key).get("subject") if curriculum.exists(channel.key) else ""
    except Exception:  # noqa: BLE001 - written without the plan's subject
        subject = ""
    if subject:
        lines.append(f"About: {subject}")
    topics = _topics(channel)
    lines.append(f"Topics: {', '.join(topics) if topics else '(not set yet)'}")
    return "\n".join(lines)


def generate(channel) -> dict:
    """Write the descriptions for a channel (a cent or two), keep them,
    and return them. Written again once if they talk about production."""
    from pipeline.llm import SystemBlock, call_json
    about = _what_it_is(channel)
    words, note = None, ""
    for _ in range(2):
        data = call_json([SystemBlock(SYSTEM, cacheable=False)], about + note, SCHEMA,
                         operation="channel_profile", max_tokens=3000, effort="low")
        attempt = clean(data)
        if words is None or len(leaks(attempt)) < len(leaks(words)):
            words = attempt
        found = leaks(words)
        if not found:
            break
        log.info(f"  [profile] the descriptions talked about production ({', '.join(found)}); writing again")
        note = (f"\n\nA first attempt talked about how the videos are made ({', '.join(found)}). "
                f"Leave all of that out: describe what it's like to watch.")
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
