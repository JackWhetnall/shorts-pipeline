"""
A pitch in, a complete draft channel out, for a person to review.

"Science news", "daily stoic quote", "maths for the curious": one Claude
call turns an idea into every decision a new channel needs. Names, the
format, a style prompt, length and pacing, what imagery to keep off it,
three narrator voices chosen from the account's own ElevenLabs list, a
caption palette from the vetted set, the art direction for its animated
scenes and how much of each video to animate, and the risks worth knowing
before starting. A second, cheaper call (the existing
`curriculum_gen.plan_outline`) designs the topic plan for a channel that
generates its own topics.

Nothing is created here. The draft is reviewed and edited as a whole,
then accepted into a real channel by core.drafts. See
docs/specs/launch-pipeline-and-publishing.md, stages 1-3.

Everything the model returns that has to match something real (a voice
id, a palette key, a built-in source, a number in a sensible range) is
checked against it here, so a confident wrong answer becomes a sensible
default rather than a broken channel.
"""

from __future__ import annotations

from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline.llm import SystemBlock, call_json

log = get_logger(__name__)

DRAFT_MAX_TOKENS = 12000
DRAFT_EFFORT = "medium"      # real judgement: positioning, tone, risk
OUTLINE_TOPICS = 25
OUTLINE_SUBTOPICS = 750      # ~2 years at one a day; units are written as needed

BUILT_IN_SOURCES = ("bible", "shakespeare")
VOICE_DESCRIPTION_CHARS = 220

SYSTEM = """
You design new channels for an automated short-form video pipeline, from a
one-line pitch. Your draft is reviewed by the channel's owner before
anything is created, so be decisive and specific, and say plainly where
the idea is weak.

What the pipeline makes: vertical videos of about 30-90 seconds. A script
is split into a few spoken segments, read by an AI narrator voice, with
burned-in word-by-word captions. Under the captions, each segment shows
either stock b-roll matched to it, or an animated scene drawn for it:
shapes that draw themselves, labels, equations, counters, charts and
illustrated props (a piggy bank, a candle), built up in time with the
words. Stock footage carries mood and cannot demonstrate anything precise.
Scenes explain: structures, processes, quantities, comparisons, symbols.

Every channel has its own art direction for its scenes, used in every
video so the channel is recognisable: a starting preset, its own palette
(background, ink and five accents that read well on the background),
fonts from the installed list, and a prop style (how its illustrated
objects are drawn: medium, line, colour, mood; never a subject). Choose
the look from the audience's relationship to the subject, not from the
subject's stereotype: adults who were put off maths at school should not
be shown a school chalkboard, and a calm devotional audience should not
get neon. Clean and uncluttered beats textured unless texture is the
point. Distinct, not generic. Then set when a segment uses a graphic
(an illustration in this look, or a designed motion graphic: a number, a
comparison, a list, a process) instead of real footage, 0-100. It is a
threshold on how much a segment needs one: 0 is always footage; 20-35
suits channels about people, animals, places and everyday life, where
real footage is usually best and a graphic only earns its place for a
statistic or a comparison; 40-60 suits science, history and ideas; 80+
only subjects explained visually throughout, like maths. Never set 100
for a channel whose subject can be filmed.

Where the words come from: either `topic` mode, where every script is
written from one topic in an ordered syllabus that runs from what anyone
could follow to what only an enthusiast would search for; or
`static_corpus` mode, where each video reads an existing public-domain
text verbatim (a built-in Bible or Shakespeare library, or the channel's
own list of quotes) and then comments on it.

What decides whether a channel can earn: YouTube's rules against
"inauthentic" and "reused" content single out AI-generated videos made
from generic templates that give the impression of mass production. A
channel survives that by having a specific audience, a real point of view
and genuinely new analysis in every video. A generic "facts about X"
channel is exactly the kind that gets demonetised. Push the pitch toward
something narrower and ownable, and name the risk if it can't be.

The style prompt is the instruction every script is written from. Write
it as real instructive prose, the way an experienced showrunner briefs a
writer: who it's for, the voice and register, how a video tends to open
(a strong first line decides whether anyone keeps watching), how it moves
between ideas, what it never does, and how careful it must be with facts
and claims. Never include a quotable example line or an exact sentence to
follow. The writer model reuses any sample sentence almost verbatim in
nearly every video, which is exactly the sameness that gets a channel
demonetised. Describe what a good opening DOES, never what one SAYS.

Every video opens with a hook: in its first sentence, a specific question
or tension that this video then pays off, honestly and in full. That is
true of every channel. The hook style says how THIS channel does it: what
kind of loop it opens (a quiet question a listener is carrying, a
surprising number, a common belief that is wrong), at what intensity, and
what it never does. A reflective channel hooks gently and must never
sound like clickbait; an energetic one can hook hard. Same rule as above:
describe, never give an example line.
""".strip()


def _art_schema() -> dict:
    from pipeline.scenes import art

    colour = {"type": "string", "description": "#RRGGBB"}
    fonts = list(art.FONTS)
    return {
        "type": "object",
        "properties": {
            "preset": {"type": "string", "enum": list(art.presets())},
            "background": colour, "ink": colour, "ink_soft": colour, "label_fill": colour,
            "accent1": colour, "accent2": colour, "accent3": colour, "accent4": colour,
            "accent5": colour,
            "font_display": {"type": "string", "enum": fonts,
                             "description": "Headings AND every label, number and equation."},
            "font_text": {"type": "string", "enum": fonts},
            "prop_style": {"type": "string",
                           "description": "How illustrated props are drawn, in one sentence: "
                                          "medium, linework, palette, mood. No subject."},
            "scene_share": {"type": "integer", "description": "0-100: the threshold for "
                                                             "animating a segment, as above."},
            "reason": {"type": "string", "description": "Why this look and this amount, "
                                                        "in a sentence."},
        },
        "required": ["preset", "background", "ink", "ink_soft", "label_fill", "accent1",
                     "accent2", "accent3", "accent4", "accent5", "font_display", "font_text",
                     "prop_style", "scene_share", "reason"],
        "additionalProperties": False,
    }


def _art_menu() -> str:
    from pipeline.scenes import art

    presets = "\n".join(f"- {k}: {p['label']}. {p['description']}" for k, p in art.presets().items())
    fonts = "\n".join(f"- {name}: {what}" for name, what in art.FONTS.items())
    return f"Art direction presets:\n{presets}\n\nFonts available:\n{fonts}"


def _schema(palette_keys: list, voice_ids: list) -> dict:
    return {
        "type": "object",
        "properties": {
            "name_options": {"type": "array", "items": {"type": "string"},
                             "description": "Three distinct channel names, best first. "
                                            "Short, memorable, not generic."},
            "summary": {"type": "string",
                        "description": "One sentence: what this channel is and who it's for."},
            "audience": {"type": "string"},
            "content_mode": {"type": "string", "enum": ["topic", "static_corpus"]},
            "corpus_source": {"type": "string", "enum": ["", *BUILT_IN_SOURCES, "custom"],
                              "description": "static_corpus only. '' for topic mode."},
            "custom_quotes": {"type": "array", "items": {"type": "string"},
                              "description": "Only when corpus_source is 'custom': 30 real, "
                                             "public-domain quotes, one per entry, as "
                                             "'quote — author'. Only quotes you are sure are "
                                             "correctly attributed. Otherwise empty."},
            "subject": {"type": "string",
                        "description": "topic mode: the subject the syllabus covers, in a "
                                       "phrase. '' for static_corpus."},
            "style_prompt": {"type": "string"},
            "hook_style": {"type": "string",
                           "description": "How this channel's videos open, in 1-3 sentences: "
                                          "the kind of question or tension its hooks open and "
                                          "at what intensity, in its own register. Guidance, "
                                          "never an example line."},
            "target_seconds": {"type": "integer",
                               "description": "Finished video length, 30-90."},
            "segment_count": {"type": "integer", "description": "Spoken segments, 2-6."},
            "speed": {"type": "number", "description": "Narrator speed, 0.8-1.15; 1.0 is normal."},
            "avoid_imagery": {"type": "array", "items": {"type": "string"},
                              "description": "Single words or short phrases for stock "
                                             "footage this channel must never show. Matched "
                                             "from the start of words in clip descriptions."},
            "voice_brief": {"type": "string",
                            "description": "The ideal narrator, in a sentence."},
            "voice_ids": {"type": "array", "items": {"type": "string", "enum": voice_ids},
                          "description": "The three best-fitting voices from the list, "
                                         "best first."},
            "palette_key": {"type": "string", "enum": palette_keys},
            "art": _art_schema(),
            "music_moods": {"type": "array", "items": {"type": "string"},
                            "description": "Three short searches (2-4 words: mood, instrument, "
                                           "style) for instrumental background music that suits "
                                           "the channel under narration."},
            "needs_news_source": {"type": "boolean",
                                  "description": "True if the idea depends on recent "
                                                 "events that a syllabus can't provide."},
            "risks": {"type": "array", "items": {"type": "string"},
                      "description": "Up to five plain-English risks: monetisation, "
                                     "accuracy, audience, sameness. Each with what "
                                     "the draft does about it."},
        },
        "required": ["name_options", "summary", "audience", "content_mode",
                     "corpus_source", "custom_quotes", "subject", "style_prompt", "hook_style",
                     "target_seconds", "segment_count", "speed", "avoid_imagery",
                     "voice_brief", "voice_ids", "palette_key", "art", "music_moods",
                     "needs_news_source", "risks"],
        "additionalProperties": False,
    }


def draft(pitch: str, voices: list, note: str = "", previous: dict = None) -> dict:
    """A draft channel for `pitch`. `voices` is the account's voice list
    (core.voice_lab); `note` and `previous` redraft an earlier attempt
    with the owner's correction."""
    from core import palettes

    pitch = (pitch or "").strip()
    if not pitch:
        raise PipelineError("empty pitch", user_message="Describe the channel idea first.")
    if not voices:
        raise PipelineError("no voices", user_message=(
            "No ElevenLabs voices are available to choose from. Open the Voice Lab "
            "once to load them, then try again."))

    voice_list = "\n".join(
        f"- {v['voice_id']}: {v['name']}. {(v.get('description') or '')[:VOICE_DESCRIPTION_CHARS]}"
        for v in voices)
    palette_list = "\n".join(f"- {p.key}: {p.label} ({p.mood})" for p in palettes.PALETTES)
    system = [
        SystemBlock(SYSTEM, cacheable=True),
        SystemBlock(f"Narrator voices available:\n{voice_list}\n\n"
                    f"Caption palettes available:\n{palette_list}\n\n{_art_menu()}"),
    ]
    user = f"The pitch: {pitch}"
    if previous and note:
        user += (f"\n\nA previous draft was:\n- names: {', '.join(previous.get('name_options', []))}"
                 f"\n- summary: {previous.get('summary', '')}"
                 f"\n\nThe owner's note on it: {note.strip()}\n\n"
                 f"Redraft the whole channel with that note taken into account.")
    elif note:
        user += f"\n\nThe owner adds: {note.strip()}"

    voice_ids = [v["voice_id"] for v in voices]
    data = call_json(system, user, _schema([p.key for p in palettes.PALETTES], voice_ids),
                     operation="channel_draft", max_tokens=DRAFT_MAX_TOKENS,
                     effort=DRAFT_EFFORT)
    return clean(data, voice_ids)


def clean(data: dict, voice_ids: list) -> dict:
    """Hold the model's answer to what the app can actually use."""
    from core import palettes

    out = dict(data)
    names = [n.strip() for n in data.get("name_options") or [] if n and n.strip()]
    out["name_options"] = names[:3] or ["New channel"]

    mode = data.get("content_mode")
    source = data.get("corpus_source") or ""
    if mode == "static_corpus" and source in BUILT_IN_SOURCES:
        out["custom_quotes"] = []
    elif mode == "static_corpus" and source == "custom" and data.get("custom_quotes"):
        out["custom_quotes"] = [q.strip() for q in data["custom_quotes"] if q and q.strip()]
    else:
        # A quote channel with nothing to quote can't make a video; fall
        # back to generating from a topic plan, which always can.
        mode, source = "topic", ""
        out["custom_quotes"] = []
    out["content_mode"], out["corpus_source"] = mode, source
    if mode == "topic" and not (data.get("subject") or "").strip():
        out["subject"] = out.get("summary") or out["name_options"][0]

    out["target_seconds"] = int(_clamp(data.get("target_seconds"), 45, 30, 90))
    out["segment_count"] = int(_clamp(data.get("segment_count"), 3, 2, 6))
    out["speed"] = round(_clamp(data.get("speed"), 1.0, 0.8, 1.15), 2)

    ids = [v for v in data.get("voice_ids") or [] if v in voice_ids]
    out["voice_ids"] = list(dict.fromkeys(ids + voice_ids))[:3]
    if data.get("palette_key") not in palettes.PALETTES_BY_KEY:
        out["palette_key"] = palettes.DEFAULT_PALETTE
    out["art"] = clean_art(data.get("art") or {})
    out["avoid_imagery"] = [a.strip().lower() for a in data.get("avoid_imagery") or []
                            if a and a.strip()][:30]
    out["risks"] = [r for r in data.get("risks") or [] if r][:5]
    if not (out.get("style_prompt") or "").strip():
        raise PipelineError("draft had no style prompt", user_message=(
            "The draft came back without a style prompt. Try again, perhaps with a "
            "more specific pitch."))
    return out


def clean_art(raw: dict) -> dict:
    """The art direction as the channel stores it, plus the share and the
    reason, with anything unusable dropped (the preset's value is used)."""
    from pipeline.scenes import art

    out = art.clean(raw)
    out["scene_share"] = int(_clamp(raw.get("scene_share"), 30, 0, 100))
    out["reason"] = (raw.get("reason") or "").strip()
    return out


def _clamp(value, default, low, high) -> float:
    """Missing means the default; present but out of range means the
    nearest bound. (0 is a value, not a missing one.)"""
    try:
        number = float(default if value is None else value)
    except (TypeError, ValueError):
        number = float(default)
    return min(high, max(low, number))


def outline(style_prompt: str, subject: str, name: str) -> list:
    """The topic plan's outline for a topic-mode draft: ordered topics,
    no subtopics yet. Reuses the syllabus designer every channel uses."""
    from core.channels import ChannelConfig
    from pipeline import curriculum_gen

    stand_in = ChannelConfig(key="draft", channel_display_name=name, style_prompt=style_prompt)
    data = curriculum_gen.plan_outline(stand_in, topic_count=OUTLINE_TOPICS,
                                       total_subtopics=OUTLINE_SUBTOPICS,
                                       subject_hint=subject)
    return data.get("topics") or []
