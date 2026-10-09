"""
TikTok and Instagram captions written for search (decision 085).

Both platforms are search engines now: TikTok reads the caption's words
(the first 80 to 100 characters most) to decide what a video is about,
and Instagram has used caption keywords as a search signal since it cut
hashtags to five. What these captions used to be was the YouTube
description pasted in: the title, a line, "Reference: John 9:12", a music
licence and ten hashtags; on TikTok, the title and hashtags alone.

One cheap call writes both platforms' captions from what the video is
about: what someone would type to find it, said first and said naturally,
then a line or two of the related things people search for, then a few
hashtags. It's given the questions a quiz asks but never the answers, and
a caption that names an answer anyway isn't used.
"""

from __future__ import annotations

import re

from core.logging_setup import get_logger
from pipeline import llm

log = get_logger(__name__)

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 1500           # no thinking on this call: the answer alone is ~300 tokens
PLATFORMS = ("tiktok", "instagram")
MAX_TAGS = 4                # the channel's own tag makes five, Instagram's limit
MAX_CAPTION = {"tiktok": 400, "instagram": 600}

SYSTEM = """You write captions for short vertical videos on TikTok and Instagram Reels.
Their job is search: on both platforms the caption's words decide which
searches a video turns up in, and on Instagram only the first ~125
characters show before "more". A caption is not a summary of the video
and not an advert for the channel.

Write each caption like this:
- The first sentence leads with the words someone would actually type
  to find this video, inside its first 80 characters: the search phrase
  given below, word for word (a passage's reference, a quiz's category
  and "quiz"), in a natural sentence that also makes a scroller curious.
  Never a list of keywords.
- Then one or two short sentences that work in the related things people
  search for (the person, the book or the topic, the kind of question,
  how hard it is), still sounding like a person wrote them.
- No hashtags in the caption itself, no emoji walls, no "link in bio",
  "follow for more", "comment below", or the channel's name.
- Say nothing the details below don't support. Never give away an answer.
- British spelling. No dashes of any kind between words: use a full stop
  or a comma.

TikTok: 120 to 250 characters. Instagram: 150 to 400 characters, its
first 125 characters able to stand alone.

Hashtags: up to 4 per platform, without the channel's own (it's added),
the most specific first: one or two for this exact topic (for a passage,
its book and chapter, e.g. #john9, never the verse number), one for the
kind of video (e.g. #biblestudy, #quiztime), one broad one people
browse. Only tags people really use, never invented compounds. Lower
case, no spaces, nothing longer than 25 characters."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {p: {
        "type": "object",
        "additionalProperties": False,
        "properties": {"caption": {"type": "string"},
                       "hashtags": {"type": "array", "items": {"type": "string"}}},
        "required": ["caption", "hashtags"],
    } for p in PLATFORMS},
    "required": list(PLATFORMS),
}


def search_phrase(reference: str = "", quiz: dict = None, title: str = "") -> str:
    """What someone would type to find this video: a passage's reference
    ("John 9:12"), a quiz's category and "quiz", or else its title."""
    if reference:
        return reference
    if quiz and quiz.get("category"):
        return f"{quiz['category']} quiz"
    return title


def _dashes(text: str) -> str:
    return re.sub(r"\s*[–—]\s*|\s+-\s+", ", ", text)


def brief(*, channel_name: str, about: str = "", keywords: list = (), title: str = "",
          description: str = "", reference: str = "", spoken: list = (), quiz: dict = None) -> str:
    """What the video is about, for the writer. A quiz's questions, never
    its answers."""
    lines = [f"Search phrase: {search_phrase(reference, quiz, title)}", f"Channel: {channel_name}"]
    if about:
        lines.append(f"What the channel is: {about}")
    if keywords:
        lines.append("What people search to find this kind of channel: " + ", ".join(keywords))
    lines.append(f"Video title: {title}")
    if reference:
        lines.append(f"Passage: {reference}")
    if description:
        lines.append(f"About this video: {description}")
    if quiz:
        lines.append(f"Quiz category: {quiz.get('category', '')}; difficulty: {quiz.get('difficulty', '')}")
        questions = [q.get("question", "") for q in quiz.get("questions") or [] if q.get("question")]
        if questions:
            lines.append("Its questions (answers are kept secret):\n" + "\n".join(f"- {q}" for q in questions[:10]))
    if spoken:
        lines.append("What's said, in order:\n" + "\n".join(f"- {s}" for s in spoken[:8]))
    return "\n".join(lines)


def _clean_tag(tag: str) -> str:
    word = re.sub(r"[^a-z0-9]", "", (tag or "").lower())
    return f"#{word}" if 2 < len(word) <= 25 else ""


def _gives_away(text: str, answers: list) -> bool:
    low = f" {text.lower()} "
    for answer in answers:
        a = " ".join(re.findall(r"[a-z0-9]+", (answer or "").lower()))
        if len(a) > 3 and re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", low):
            return True
    return False


def write(prompt: str, answers: list = ()) -> dict:
    """{platform: {"caption", "hashtags"}} for the platforms whose caption
    came back usable. Raises what `llm.call_json` raises."""
    data = llm.call_json(SYSTEM, prompt, SCHEMA, operation="social_caption",
                         model=MODEL, max_tokens=MAX_TOKENS, effort=None)
    out = {}
    for platform in PLATFORMS:
        part = data.get(platform) or {}
        text = _dashes(" ".join((part.get("caption") or "").replace("#", "").split()).strip())
        if not text or len(text) > MAX_CAPTION[platform]:
            log.warning(f"social caption for {platform} unusable ({len(text)} characters)")
            continue
        if _gives_away(text, answers):
            log.warning(f"social caption for {platform} named a quiz answer; not used")
            continue
        tags = []
        for tag in part.get("hashtags") or []:
            tag = _clean_tag(tag)
            if tag and tag not in tags and not _gives_away(tag[1:], answers):
                tags.append(tag)
        out[platform] = {"caption": text, "hashtags": tags[:MAX_TAGS]}
    return out
