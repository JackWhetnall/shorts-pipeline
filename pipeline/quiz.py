"""
Quiz videos: a pub-quiz host asking a round of questions over a board.

A quiz channel's video is one round: a category (the topic plan's topic)
at one difficulty (its subtopic). The host says what today's round is,
reads each question with its whole text on screen, lets a clock run for a
few seconds, gives the answer, and moves on; the answers fill a numbered
list down the left as they're revealed. No footage and no captions: the
board is the picture. See decision 041.

Three steps, each its own function so the pipeline's stages can call them:

- `write_script` — one Sonnet call for the round, then an independent
  fact check (`verify`) that answers every question itself. Anything it
  disagrees with, finds ambiguous or dated is rewritten once and checked
  again; what still fails is recorded in the script and holds the video
  for a person. A wrong answer is the one mistake a quiz can't survive.
- `to_script` — the round as spoken segments, each question followed by
  a silence the length of the countdown (Segment.pause_after).
- `board` — the pipeline stage that films the board for the whole video
  from the real voiceover timings, as one motion-template page.
"""

from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path
from types import SimpleNamespace

from core import curriculum
from core.errors import PipelineError
from core.paths import PROJECT_ROOT
from core.logging_setup import get_logger
from pipeline.llm import SystemBlock, call_json
from pipeline.plan import Script, Segment

log = get_logger(__name__)

WRITE_MAX_TOKENS = 10000
WRITE_EFFORT = "medium"
VERIFY_MAX_TOKENS = 16000
VERIFY_EFFORT = "high"         # a wrong answer is the one unrecoverable mistake
QUESTION_CHARS = 170      # read aloud and shown whole: a sentence, not a paragraph
ANSWER_CHARS = 40         # one row of the board

SYSTEM = """
You write one round for a pub-quiz channel of short vertical videos. The
host is chilled, fun and friendly: a good pub quizmaster, relaxed and a
bit playful, never a game-show announcer and never corporate. It is
spoken aloud, so write the way a person talks.

The round: a short intro, then the questions in order, then a sign-off.
Each question's full text is shown on screen while the host reads it,
then a clock counts down for a few seconds, then the host gives the
answer and the answer appears on a numbered board. Nothing else is on
screen: no pictures, no multiple-choice options.

The intro (2-3 sentences, under 45 words): casually say today's quiz is
all about the category and how hard this one is, invite the viewer to
keep score, and end by leading straight into question one (so the first
question needs no lead-in of its own). Vary the wording from video to
video; never the same stock opener.

Each question:
- `question`: the complete question as shown and read. One sentence,
  self-contained, plain, under 25 words. No "which of these", since no
  options are shown. No trick wording.
- Exactly one correct answer, which you are certain of, and which does
  not change over time: never current record holders, office holders,
  populations, prices or "the latest" anything. If reasonable sources
  disagree, don't ask it.
- `answer`: the answer as it appears on the board: a name, a number, a
  word or a very short phrase, 1-4 words.
- `spoken_answer`: how the host gives it, under 14 words. When the
  answer is short, the host usually says it twice, sometimes with the
  question's context the second time ("Beijing. Beijing is the capital
  of China."), now and then with a quick fact, often just plainly. Mix
  these across the round; not the same shape every time. Any fact the
  host adds must be as certain as the answer.
- Read each question back as a sentence: it must be grammatical and say
  exactly one thing ("What is the boundary between the crust and the
  mantle called?", never "What is the name of ... called?").
- Superlatives and "only", "first", "never" questions are where quiz
  answers go wrong: ask one only when you are sure there is no second
  case, today.
- Everything spoken is read by a voice engine exactly as written. List
  in `pronunciations` any word in the questions or answers it might
  misread, with how to say it in plain respelling: symbols and
  abbreviations as letter names ("Au" as "ay you", "DNA" is fine as it is),
  and words whose stress or spelling misleads ("aphelion" as
  "af-EE-lee-on", "Worcestershire" as "WUSS-ter-sher"). Only what a
  careful reader might get wrong; usually none or one or two. The board
  shows the real word; only the voice uses the respelling. No dashes in
  anything spoken.
- `lead_in`: for every question after the first, the host's short move
  to it, which says its number: "Question two.", "Number three." and so
  on, with the odd bit of colour ("halfway there", "last one"). Under 7
  words. Empty for the first question.

Difficulty is given as a level on this 1-10 scale. The level is what
counts; the label is only this channel's name for it.
- 1-2: almost every adult knows it.
- 3-4: most adults would get it: everyday general knowledge.
- 5-6: a regular at the pub quiz would; about a third of adults.
- 7-8: keen quizzers and fans of the category; about one in ten.
- 9-10: specialists, or the rare person who happens to know an obscure
  but real, checkable fact. Still fair: never a trick, never something
  unknowable.
Hold the whole round within about a point of its level, easing in with
the first question or two.

Cover the category broadly, not one narrow corner of it, and never ask
two questions whose answers give each other away.

The sign-off (under 30 words): ask how many they got, and either for
their score and next category in the comments or to send it to a friend
to see how they do. Vary it.

Titles: short (under 60 characters), naming the category and the
difficulty, inviting the viewer to test themselves. The description body:
one or two plain sentences about the round, no hashtags.
""".strip()


def _schema(kind: str = None) -> dict:
    question = {
        "type": "object",
        "properties": {
            "lead_in": {"type": "string"},
            "question": {"type": "string"},
            "answer": {"type": "string"},
            "spoken_answer": {"type": "string"},
        },
        "required": ["lead_in", "question", "answer", "spoken_answer"],
        "additionalProperties": False,
    }
    if kind and kind != "dingbats":
        question["properties"]["subject"] = {"type": "string"}
        question["required"].append("subject")
    if kind == "dingbats":
        question["properties"]["layout"] = {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "x": {"type": "number"},
                           "y": {"type": "number"}, "size": {"type": "number"},
                           "rotate": {"type": "number"},
                           "flip": {"type": "string", "enum": ["none", "horizontal", "vertical"]},
                           "strike": {"type": "boolean"},
                           "color": {"type": "string", "enum": ["ink", "red", "blue", "green",
                                                                "yellow", "orange", "purple"]}},
            "required": ["text", "x", "y", "size", "rotate", "flip", "strike", "color"],
            "additionalProperties": False}}
        question["required"].append("layout")
    return {
        "type": "object",
        "properties": {
            "intro": {"type": "string"},
            "questions": {"type": "array", "items": question},
            "pronunciations": {"type": "array", "items": {
                "type": "object",
                "properties": {"written": {"type": "string"}, "say": {"type": "string"}},
                "required": ["written", "say"], "additionalProperties": False}},
            "outro": {"type": "string"},
            "title_options": {"type": "array", "items": {"type": "string"}},
            "description_body": {"type": "string"},
        },
        "required": ["intro", "questions", "pronunciations", "outro", "title_options",
                     "description_body"],
        "additionalProperties": False,
    }


VERIFY_SYSTEM = """
You are the fact checker for a quiz video before it is published. Quiz
writers repeat popular trivia "facts" that are wrong or no longer true,
and a checker who reads the proposed answer first tends to agree with
it. So for each question, in this order:

1. `working`: check it systematically, as if you'd never seen the
   proposed answer. For a superlative or an "only", "first", "never",
   "no other" question, go through the whole set it ranges over (every
   planet, every element symbol, every country...) rather than recalling
   the famous answer. Consider changes over time (renamed elements,
   redrawn borders, reclassified species).
2. `correct_answers`: every answer a knowledgeable player could give and
   be right, however many that is.
3. `verdict`, comparing with the proposed answer:

- "ok": the proposed answer is right, and your correct answers hold
  nothing else (spellings and forms of the same answer are one answer).
- "wrong": the proposed answer is incorrect.
- "ambiguous": more than one answer is defensible, or the wording is
  unclear enough that a fair player could answer differently and be
  right.
- "dated": the answer depends on when it's asked (a current holder,
  record, population or price) and could be out of date.
- "unclear": the question is ungrammatical or muddled as a sentence.

Also check any extra fact in the host's line: if it's wrong, the
question is "wrong".

Be strict: a published wrong answer is what ruins a quiz channel. Don't
flag a question for being easy or hard.
""".strip()

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "working": {"type": "string"},
                    "correct_answers": {"type": "array", "items": {"type": "string"}},
                    "verdict": {"type": "string",
                                "enum": ["ok", "wrong", "ambiguous", "dated", "unclear"]},
                    "note": {"type": "string"},
                },
                "required": ["number", "working", "correct_answers", "verdict", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


# --- what this round is --------------------------------------------------

def base_category(title: str) -> str:
    """A category without its number: "General Knowledge 2" and
    "General Knowledge (3)" are more of General Knowledge, and share its
    memory of what has been asked."""
    return re.sub(r"\s*(\(\s*\d+\s*\)|\d+|\b[IVX]+\b)\s*$", "", (title or "").strip()) or (title or "").strip()


def round_of(seed, channel) -> tuple:
    """(category, difficulty) for a seed. The topic plan knows exactly;
    a bare seed title of the form "Science: Hard" is split instead."""
    if seed.topic_id and curriculum.exists(channel.key):
        entry = curriculum.find(channel.key, seed.topic_id)
        if entry:
            topic = curriculum.find_topic(channel.key, entry["topic"]) or {}
            difficulty = entry.get("angle") or ""
            if topic.get("title") and difficulty:
                return base_category(topic["title"]), difficulty
    title = seed.topic or seed.title or "General knowledge"
    for sep in (":", " — ", " - "):
        if sep in title:
            category, difficulty = title.split(sep, 1)
            return base_category(category.strip()), difficulty.split("(")[0].strip()
    return base_category(title.strip()), levels(channel.quiz.difficulties)[0][0]


# --- the difficulty scale ------------------------------------------------------
#
# What the writer is held to is a number on one fixed 1-10 scale; the
# label is only the channel's name for it. A level added later (say
# "Tricky" between Hard and Fiendish) therefore slots in between its
# neighbours instead of stretching every other level, and "Hard" means the
# same thing on every channel.

KNOWN_LEVELS = {"very easy": 1, "easy": 2, "medium": 4, "moderate": 4, "hard": 5.5,
                "tricky": 6.5, "very hard": 7, "fiendish": 8, "expert": 8.5, "brutal": 8.5,
                "impossible": 9.5}
LEVEL_RE = re.compile(r"^(.*?)\s*\((\d+(?:\.\d+)?)\)\s*$")


def parse_level(text: str) -> tuple:
    """("Tricky", 7.0) from "Tricky (7)"; ("Tricky", None) from "Tricky"."""
    text = " ".join(str(text or "").split())
    match = LEVEL_RE.match(text)
    if match:
        return match.group(1).strip(), max(1.0, min(10.0, float(match.group(2))))
    return text, None


def levels(difficulties: list) -> list:
    """[(label, level)] in the channel's order. A level given in brackets
    is used as is; a familiar name gets its usual level when that keeps the
    order rising; anything else sits evenly between its neighbours."""
    parsed = [parse_level(d) for d in difficulties if str(d).strip()] or [("Medium", None)]
    anchors = [None] * len(parsed)
    last = 0.0
    for i, (label, given) in enumerate(parsed):
        level = given if given is not None else KNOWN_LEVELS.get(label.lower())
        if level is not None and (given is not None or level > last):
            anchors[i] = level
            last = level
    known = [i for i, a in enumerate(anchors) if a is not None]
    if not known:
        n = len(parsed)
        anchors = [2 + 7.5 * i / max(1, n - 1) for i in range(n)] if n > 1 else [5.0]
    else:
        for i in range(len(parsed)):
            if anchors[i] is not None:
                continue
            before = max((k for k in known if k < i), default=None)
            after = min((k for k in known if k > i), default=None)
            if before is None:
                anchors[i] = max(1.0, anchors[after] - 1.5 * (after - i))
            elif after is None:
                anchors[i] = min(10.0, anchors[before] + 1.0 * (i - before))
            else:
                share = (i - before) / (after - before)
                anchors[i] = anchors[before] + (anchors[after] - anchors[before]) * share
    return [(label, round(level * 2) / 2) for (label, _), level in zip(parsed, anchors)]


def level_of(channel, label: str) -> float:
    for name, level in levels(channel.quiz.difficulties):
        if name.lower() == (label or "").lower():
            return level
    return KNOWN_LEVELS.get((label or "").lower(), 5.0)


def labels(channel) -> list:
    return [label for label, _ in levels(channel.quiz.difficulties)]


def subtopic_rows(category: str, difficulties: list, round_number: int = 1) -> list:
    """One topic's subtopics for a quiz channel: one per difficulty.
    Written by rule rather than by a model: free, and exactly what the
    format needs. Titles carry the category and, after the first, the
    round, because the plan drops any title it already has."""
    suffix = f" (round {round_number})" if round_number > 1 else ""
    return [{"title": f"{category}: {label}{suffix}", "angle": label}
            for label, _ in levels(difficulties)]


def _named(topic: dict) -> bool:
    return bool((topic.get("title") or "").strip()) and not topic.get("placeholder")


def next_round(channel, topic_id: str) -> int:
    """This category's next round (Easy up to the hardest level again,
    numbered on), free and by rule; the question bank keeps it clear of
    everything already asked. Returns how many quizzes were added."""
    data = curriculum.load(channel.key)
    topic = next((t for t in data["topics"] if t["id"] == topic_id), None)
    if topic is None or not _named(topic):
        return 0
    number = max([_round_number(s["title"]) for s in data["subtopics"]
                  if s["topic"] == topic_id] or [0]) + 1
    before = len(data["subtopics"])
    curriculum.add_subtopics(channel.key, topic_id,
                             subtopic_rows(topic["title"], channel.quiz.difficulties, number))
    return len(curriculum.load(channel.key)["subtopics"]) - before


def top_up(channel, force: bool = False) -> int:
    """Another round for every category when the plan runs low (or,
    `force`, now). Returns how many quizzes were added."""
    if not curriculum.exists(channel.key):
        return 0
    data = curriculum.load(channel.key)
    pending = sum(1 for s in data["subtopics"] if s["status"] == curriculum.PENDING)
    if (pending >= curriculum.LOW_WATER_MARK and not force) or not data["topics"]:
        return 0
    added = sum(next_round(channel, topic["id"]) for topic in data["topics"])
    log.info(f"{channel.key}: added {added} quizzes, another round of every category")
    return added


def sync_ladders(channel) -> int:
    """Give every round already in the plan a rung for each difficulty
    the channel now has: a level added in settings ("Tricky") arrives in
    every category at once, not only from the next round. Nothing is
    removed; a level taken out of settings keeps its written rounds."""
    if not curriculum.exists(channel.key):
        return 0
    data = curriculum.load(channel.key)
    added = 0
    for topic in data["topics"]:
        if not _named(topic):
            continue
        mine = [s for s in data["subtopics"] if s["topic"] == topic["id"]]
        for n in sorted({_round_number(s["title"]) for s in mine}):
            have = {(s.get("angle") or "").lower() for s in mine if _round_number(s["title"]) == n}
            missing = [r for r in subtopic_rows(topic["title"], channel.quiz.difficulties, n)
                       if r["angle"].lower() not in have]
            if missing:
                curriculum.add_subtopics(channel.key, topic["id"], missing)
                added += len(missing)
    if added:
        log.info(f"{channel.key}: added {added} quizzes for its new difficulty levels")
    return added


# --- the question bank -------------------------------------------------------------
#
# Every question a channel has asked, kept for good. The originality
# history keeps only the last 200 videos, which a daily quiz channel
# outgrows in seven months. The writer is shown this category's questions
# (and other categories' questions that touch on it); beyond what fits in
# a prompt, a local check against the whole bank catches repeats, which
# are then replaced like answers the fact check didn't pass.

QUESTION_BANK_DIR = PROJECT_ROOT / "config" / "question_banks"
SAME_CATEGORY_CONTEXT = 300     # ~6k tokens: a few cents a round on Sonnet
RELATED_CONTEXT = 80
STOPWORDS = frozenset("""
what which who whom whose when where why how that this these those with from into
than then there their they them have has had were was does did been being about
after before under over also only first name called known most many much more
""".split())


def _bank_path(channel_key: str) -> Path:
    return QUESTION_BANK_DIR / f"{channel_key}.json"


def bank(channel_key: str) -> list:
    """[{video, category, questions: [{question, answer}]}], oldest first.
    Seeded from the originality history the first time, so rounds made
    before the bank existed are remembered too."""
    path = _bank_path(channel_key)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning(f"{channel_key}: the question bank couldn't be read; starting from the history")
    from pipeline import similarity
    history = similarity._load().get(channel_key) or []
    return [{"video": e.get("title", ""), "category": e["quiz"].get("category", ""),
             "questions": e["quiz"].get("questions") or []} for e in history if e.get("quiz")]


def remember(channel_key: str, video: str, script: Script) -> None:
    """Add a finished quiz's questions to the bank."""
    quiz = script.quiz or {}
    rounds = [r for r in bank(channel_key) if r.get("video") != video]
    rounds.append({"video": video, "category": base_category(quiz.get("category", "")),
                   "questions": [{"question": q.get("question", ""), "answer": q.get("answer", ""),
                                  **({"kind": q["kind"], "subject": q.get("subject", "")}
                                     if q.get("kind") else {})}
                                 for q in quiz.get("questions") or []]})
    path = _bank_path(channel_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rounds, indent=1, ensure_ascii=False), encoding="utf-8")


def _made(channel_key: str) -> list:
    """[(video stem, {category, questions})] for every quiz this channel
    has made, newest first."""
    return [(r.get("video", ""), r) for r in reversed(bank(channel_key))]


def _written(channel_key: str) -> list:
    """[(subtopic, its stored round's quiz dict)] for rounds written ahead
    of their video (the ladder writes easier rungs first)."""
    if not curriculum.exists(channel_key):
        return []
    return [(s, s["script"]["quiz"]) for s in curriculum.subtopics(channel_key)
            if (s.get("script") or {}).get("quiz") and s["status"] == curriculum.PENDING]


def _keywords(text: str) -> set:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    out = set()
    for w in words:
        if len(w) < 4 or w in STOPWORDS:
            continue
        out.add(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def _all_questions(channel_key: str) -> list:
    """[(category, {question, answer})] for everything made or written."""
    rounds = [q for _, q in _made(channel_key)] + [q for _, q in _written(channel_key)]
    return [(base_category(r.get("category", "")), q) for r in rounds
            for q in r.get("questions") or [] if q.get("question")]


def context_questions(channel_key: str, category: str) -> tuple:
    """(this category's earlier questions, other categories' questions that
    touch on it): what the writer is shown. "Snakes" sees the snake
    questions a "Biology" round asked."""
    base = base_category(category).lower()
    words = _keywords(base)
    same, related = [], []
    for cat, q in _all_questions(channel_key):
        if cat.lower() == base:
            same.append(q)
        elif words & _keywords(f"{q['question']} {q.get('answer', '')}"):
            related.append(q)

    def unique(rows, limit):
        seen, out = set(), []
        for q in rows:
            if q["question"] not in seen:
                seen.add(q["question"])
                out.append(q)
        return out[:limit]
    return unique(same, SAME_CATEGORY_CONTEXT), unique(related, RELATED_CONTEXT)


def _norm_answer(answer: str) -> str:
    return re.sub(r"^(the|a|an)\s+", "", re.sub(r"[^a-z0-9 ]", "", (answer or "").lower())).strip()


def repeats(questions: list, channel_key: str, among: list = None) -> list:
    """Indices of questions that repeat one already asked or written on
    this channel (or in `among`), in any category: the same answer to much
    the same question, or much the same question. A picture question
    repeats one of the same kind showing the same thing ("Whose flag is
    this?" is asked of every flag). Local and free, so it covers the whole
    bank however large it grows."""
    source = among if among is not None else [q for _, q in _all_questions(channel_key)]
    pictured = {(q["kind"], _norm_answer(q.get("subject") or q.get("answer", "")))
                for q in source if q.get("kind")}
    past = [(_norm_answer(q.get("answer", "")), _keywords(q["question"]))
            for q in source if not q.get("kind")]
    found = []
    for i, q in enumerate(questions):
        if q.get("kind"):
            if (q["kind"], _norm_answer(q.get("subject") or q["answer"])) in pictured:
                found.append(i)
            continue
        answer, words = _norm_answer(q["answer"]), _keywords(q["question"])
        for old_answer, old_words in past:
            overlap = len(words & old_words) / max(1, len(words | old_words))
            enough = len(words | old_words) >= 4     # two short questions share words by chance
            if (answer and answer == old_answer and overlap >= 0.3) or (enough and overlap >= 0.6):
                found.append(i)
                break
    return found


def asked_before(channel_key: str, category: str) -> list:
    """The questions the writer is told not to repeat, this category's
    first (see context_questions)."""
    same, related = context_questions(channel_key, category)
    return [q["question"] for q in same + related]


# --- the difficulty ladder -------------------------------------------------------
#
# A category's rounds (Easy up to Impossible) are written easiest first,
# each seeing the others' questions, so the steps between them are real:
# written independently, "Hard" and "Medium" came out much the same. The
# videos are still made in whatever order the channel's ordering picks.

def _round_number(title: str) -> int:
    match = re.search(r"\(round (\d+)\)", title or "")
    return int(match.group(1)) if match else 1


def ladder(channel, entry: dict) -> list:
    """This round's category at every difficulty, in the same round,
    easiest first (by level, so a level added later sorts into place)."""
    rungs = [s for s in curriculum.subtopics(channel.key, topic_id=entry["topic"])
             if _round_number(s["title"]) == _round_number(entry["title"])]
    return sorted(rungs, key=lambda s: level_of(channel, s.get("angle") or ""))


def _questions_of(channel_key: str, entry: dict) -> list:
    """[{question, answer}] for one rung, whether it was written ahead or
    already made."""
    stored = (entry.get("script") or {}).get("quiz")
    if stored:
        return stored.get("questions") or []
    if entry.get("video_stem"):
        for stem, quiz in _made(channel_key):
            if stem == entry["video_stem"]:
                return quiz.get("questions") or []
    return []


def _listed(questions: list) -> str:
    return "\n".join(f"- {q.get('question')}" + (f" ({q['answer']})" if q.get("answer") else "")
                     for q in questions)


def ladder_note(channel, entry: dict) -> str:
    """The same category's other rungs, so this round's difficulty sits
    between them, and the same level from the round before, so rounds
    don't drift."""
    rungs = ladder(channel, entry)
    here = next((i for i, s in enumerate(rungs) if s["id"] == entry["id"]), 0)
    parts = []
    for i, rung in enumerate(rungs):
        questions = _questions_of(channel.key, rung) if i != here else []
        if not questions:
            continue
        side = "easier" if i < here else "harder"
        level = level_of(channel, rung.get("angle"))
        parts.append(f"The {rung.get('angle')} round, level {level:g} (must be {side} than "
                     f"this one):\n{_listed(questions)}")
    this_round = _round_number(entry["title"])
    if this_round > 1:
        for earlier in curriculum.subtopics(channel.key, topic_id=entry["topic"]):
            if (_round_number(earlier["title"]) == this_round - 1
                    and (earlier.get("angle") or "").lower() == (entry.get("angle") or "").lower()):
                questions = _questions_of(channel.key, earlier)
                if questions:
                    parts.append(f"The same level in the previous round (match its difficulty; "
                                 f"don't repeat it):\n{_listed(questions)}")
    if not parts:
        return ""
    return ("This category's other rounds, for calibration. Pitch this one at its own level: "
            "a step harder than every easier round, a step easier than every harder one. "
            "Don't repeat their questions.\n\n" + "\n\n".join(parts))


def write_ladder_below(channel, entry: dict) -> int:
    """Write and store every easier rung of this round's ladder that has
    neither a script nor a video yet, easiest first. Returns how many."""
    written = 0
    for rung in ladder(channel, entry):
        if rung["id"] == entry["id"]:
            break
        rung = curriculum.find(channel.key, rung["id"])
        if rung["status"] != curriculum.PENDING or _questions_of(channel.key, rung):
            continue
        log.info(f"  [quiz] writing the {rung.get('angle')} round of this category first, "
                 f"so this one builds on it")
        script = write_round(channel, rung)
        curriculum.set_script(channel.key, rung["id"], script.to_jsonable())
        written += 1
    return written


# --- writing ---------------------------------------------------------------

def _clean_round(data: dict, count: int, kind: str = None) -> dict:
    questions = []
    for q in data.get("questions") or []:
        question = " ".join((q.get("question") or "").split())
        answer = " ".join((q.get("answer") or "").split())
        spoken = " ".join((q.get("spoken_answer") or "").split()) or answer
        if not question or not answer:
            continue
        row = {"lead_in": " ".join((q.get("lead_in") or "").split()),
               "question": question[:QUESTION_CHARS * 2],
               "answer": answer, "spoken_answer": spoken}
        if kind:
            row["kind"] = kind
            row["subject"] = (q.get("subject") or "").strip()
            if kind == "dingbats":
                row["layout"] = [i for i in q.get("layout") or [] if (i.get("text") or "").strip()]
                row["subject"] = " / ".join(i["text"] for i in row["layout"])
        questions.append(row)
    if len(questions) < count:
        raise PipelineError(f"quiz came back with {len(questions)} of {count} questions",
                            user_message="The quiz came back short of questions. Try again.")
    data["questions"] = questions[:count]
    data["questions"][0]["lead_in"] = ""
    data["pronunciations"] = {p["written"].strip(): p["say"].strip()
                              for p in data.get("pronunciations") or []
                              if (p.get("written") or "").strip() and (p.get("say") or "").strip()}
    # Chemical symbols by rule, whatever the writer listed: they come up
    # often and the voice gets them wrong ("Au" read as "ow").
    data["pronunciations"].update(element_respellings(data["questions"]))
    return data


WORDS_PER_SECOND = 2.5          # as pipeline.script_gen
PICTURE_REWRITES = 3


def word_budget(channel) -> int:
    """Spoken words the round can have and still fit the channel's length:
    the countdowns and pauses are fixed, the talk is what's left."""
    quiz = channel.quiz
    silent = quiz.questions * (quiz.countdown_seconds + quiz.answer_pause) + 2.5
    talk = max(30.0, channel.pacing.target_seconds - silent)
    return int(talk * WORDS_PER_SECOND * (channel.speed or 1.0))


def _user(category: str, difficulty: str, count: int, channel, context: tuple, extra: str) -> str:
    same, related = context
    words = word_budget(channel)
    text = (f"Category: {category}\n"
            f"Difficulty: {difficulty}, level {level_of(channel, difficulty):g} on the 1-10 scale\n"
            f"Questions: exactly {count}\n"
            f"Length: the whole round as spoken (intro, lead-ins, questions, answers, "
            f"sign-off) is at most {words} words, about {max(12, (words - 60) // count)} per "
            f"question with its answer. The clock time is extra and fixed, so this is what "
            f"keeps the video under three minutes; count as you write.\n\n")
    if same:
        text += (f"Already asked in {category} on this channel. Don't ask these again, or the "
                 f"same fact another way:\n{_listed(same)}\n\n")
    if related:
        text += (f"Asked in other categories and touching on {category}. Don't repeat these "
                 f"either:\n{_listed(related)}\n\n")
    return text + extra


PICTURE_GUIDE = {
    "flags": """This is a picture round: each question shows a national flag.
- subject: the country, written exactly as in the list below.
- question: short (under 10 words) and varied ("Whose flag is this?",
  "Which country flies this one?"); never name or describe the country.
- Harder levels choose less familiar flags, not trickier wording.""",
    "outlines": """This is a picture round: each question shows a country's outline.
- subject: the country, written exactly as in the list below.
- question: short (under 10 words) and varied ("Which country has this
  shape?"); never name or describe the country.
- Harder levels choose less familiar shapes, not trickier wording.""",
    "faces": """This is a picture round: each question shows a photograph of a famous
person.
- subject: the exact title of their English Wikipedia article.
- Choose people whose faces fit the level: at Easy, faces almost everyone
  knows; at the hardest levels, people whose names are well known but
  whose faces far fewer could place. Adults only; no one whose picture
  would be sensitive or cruel to show.
- question: "Who is this?" or a close variation, nothing more: the face is
  the question. Only at the two hardest levels may it add a small clue,
  and a clue must never be enough to answer without the picture ("a
  scientist" is fine; "the physicist behind relativity" is not). Never
  their name.""",
    "landmarks": """This is a picture round: each question shows a photograph of a famous
landmark, building or natural wonder.
- subject: the exact title of its English Wikipedia article.
- question: "Name this landmark", or "In which city is this?" (then the
  answer is the city). Never name it in the question.""",
    "paintings": """This is a picture round: each question shows a famous painting.
- subject: "Title by Artist", for a work made before 1900 (public domain,
  and likely to be in the Art Institute of Chicago's or the Met's open
  collections, where it's fetched from).
- question: "Who painted this?" or "What is this painting called?".""",
    "dingbats": """This is a picture round of dingbats: each question shows words arranged
so that their layout stands for a common phrase or saying.
- layout: the words to draw. Each has x and y (0-100, the word's centre),
  size (0.4-3, 1 is normal), rotate (degrees), flip, strike (crossed out)
  and color ("ink" normally; a real colour only when the colour is part
  of the clue, "blue" for a blue moon).
- The arrangement must carry part of the answer: at least one of its
  words comes from where, how big, how often, which way round or what
  colour the words are, never from reading them (HEAD above HEELS for
  "head over heels"; ROAD crossed with ROAD for "crossroads"). Words
  simply stacked (TOUCH above WOOD for "touch wood") are not a dingbat.
  Classic, fair puzzles a player can reason out, using a mix of devices
  across the round.
- question: "What phrase is this?" and variations.
- answer: the phrase.""",
}


def _write(category, difficulty, channel, context, extra="", kind: str = None) -> dict:
    count = channel.quiz.questions
    system = [SystemBlock(SYSTEM, cacheable=True),
              SystemBlock(f"This channel's own brief for its host and its rounds:\n\n"
                          f"{channel.style_prompt}")]
    if kind:
        from pipeline import pictures
        guide = PICTURE_GUIDE[kind]
        allowed = pictures.choices(kind)
        if allowed:
            guide += "\n\nThe list:\n" + ", ".join(allowed)
        system.append(SystemBlock(guide, cacheable=True))
    data = call_json(system, _user(category, difficulty, count, channel, context, extra), _schema(kind),
                     operation="quiz_write", max_tokens=WRITE_MAX_TOKENS, effort=WRITE_EFFORT)
    return _clean_round(data, count, kind)


def verify(category: str, difficulty: str, questions: list) -> list:
    """[verdict per question] from an independent check: "ok", "wrong",
    "ambiguous" or "dated". A check that can't run returns "unchecked"
    for every question, which holds the video rather than passing it."""
    listed = "\n".join(f"{i + 1}. Q: {q['question']}\n   Proposed answer: {q['answer']}\n"
                       f"   The host says: {q['spoken_answer']}"
                       for i, q in enumerate(questions))
    try:
        data = call_json(VERIFY_SYSTEM, f"Category: {category}. Difficulty: {difficulty}.\n\n{listed}",
                         VERIFY_SCHEMA, operation="quiz_verify",
                         max_tokens=VERIFY_MAX_TOKENS, effort=VERIFY_EFFORT)
    except PipelineError as exc:
        log.warning(f"  [quiz] the fact check couldn't run ({exc})")
        return ["unchecked"] * len(questions)
    verdicts = ["unchecked"] * len(questions)
    for row in data.get("results") or []:
        n = row.get("number")
        if isinstance(n, int) and 1 <= n <= len(questions):
            verdicts[n - 1] = row.get("verdict") or "unchecked"
            if verdicts[n - 1] != "ok":
                log.info(f"  [quiz] Q{n} {verdicts[n - 1]}: {row.get('note', '')} "
                         f"(correct: {', '.join(row.get('correct_answers') or [])})")
    return verdicts


ELEMENT_SYMBOLS = frozenset("""
H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br
Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho
Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es
Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og""".split())
# Symbols that are also everyday words or single letters: respelling
# every "In" or "No" in a round would wreck it, and a lone capital letter
# is read as its name anyway.
_WORDLIKE = frozenset({"He", "In", "As", "At", "Be", "No", "Am", "Es"})
LETTER_NAMES = {"A": "ay", "B": "bee", "C": "see", "D": "dee", "E": "ee", "F": "eff", "G": "jee",
                "H": "aitch", "I": "eye", "J": "jay", "K": "kay", "L": "el", "M": "em", "N": "en",
                "O": "oh", "P": "pee", "Q": "cue", "R": "ar", "S": "ess", "T": "tee", "U": "you",
                "V": "vee", "W": "double you", "X": "ex", "Y": "why", "Z": "zed"}


def element_respellings(questions: list) -> dict:
    """{symbol: its letters' names} for every two-letter chemical symbol a
    round gives as an answer or asks about ("the symbol Fe"), so the voice
    says "ay you" for Au rather than "ow". By rule, not left to the writer
    to notice."""
    found = set()
    for q in questions:
        candidates = re.findall(r"\b[A-Z][a-z]\b", q.get("answer", ""))
        candidates += re.findall(r"symbols?\s+(?:is\s+|of\s+)?([A-Z][a-z])\b", q.get("question", ""))
        found.update(c for c in candidates if c in ELEMENT_SYMBOLS and c not in _WORDLIKE)
    return {s: " ".join(LETTER_NAMES[ch.upper()] for ch in s) for s in sorted(found)}


def round_clashes(questions: list) -> list:
    """Indices of questions that sit badly with an earlier one in the same
    round: the same answer, an earlier answer given away in its wording
    (or its answer in an earlier question's), or much the same question."""
    found = []
    for i, q in enumerate(questions):
        for p in questions[:i]:
            same = _norm_answer(q["answer"]) and _norm_answer(q["answer"]) == _norm_answer(p["answer"])
            given = ((len(_norm_answer(p["answer"])) > 3 and _mentions(q["question"], p["answer"]))
                     or (len(_norm_answer(q["answer"])) > 3 and _mentions(p["question"], q["answer"])))
            a, b = _keywords(q["question"]), _keywords(p["question"])
            # Only questions with enough words to judge: two short ones
            # share most of their few words by chance. Picture questions
            # share their wording by design; what's pictured is what counts.
            alike = (len(a | b) >= 4 and len(a & b) / len(a | b) >= 0.6 and not q.get("kind")
                     or bool(q.get("kind")) and q.get("subject") == p.get("subject"))
            if same or given or alike:
                found.append(i)
                break
    return found


def _mentions(text: str, answer: str) -> bool:
    """Whether `answer` appears in `text` as whole words ("Au" is not in
    "Australia"), ignoring case and a leading "the"."""
    answer = re.sub(r"^the\s+", "", (answer or "").strip(), flags=re.I)
    return bool(answer) and re.search(rf"\b{re.escape(answer)}\b", text or "", re.I) is not None


def write_script(seed, channel, avoid: str = "") -> Script:
    """The round as a Script, fact-checked. `avoid` is the originality
    gate's note when a first attempt read too much like an earlier one.

    On a topic plan, the category's easier rounds are written first
    (write_ladder_below) and this one is pitched above them."""
    entry = (curriculum.find(channel.key, seed.topic_id)
             if seed.topic_id and curriculum.exists(channel.key) else None)
    if entry is None:
        category, difficulty = round_of(seed, channel)
        return _write_checked(channel, category, difficulty, avoid)
    write_ladder_below(channel, entry)
    return write_round(channel, curriculum.find(channel.key, entry["id"]), avoid)


def write_round(channel, entry: dict, avoid: str = "") -> Script:
    """One rung of a category's ladder, written knowing the others."""
    topic = curriculum.find_topic(channel.key, entry["topic"]) or {}
    category = base_category(topic.get("title") or entry["title"].split(":")[0])
    difficulty = entry.get("angle") or round_of(SimpleNamespace(
        topic_id="", topic=entry["title"], title=entry["title"]), channel)[1]
    extra = "\n\n".join(p for p in (ladder_note(channel, entry), avoid) if p)
    return _write_checked(channel, category, difficulty, extra, topic.get("picture"))


def _check(channel, category: str, difficulty: str, questions: list, kind: str = None) -> list:
    """A verdict per question: "ok", or why not. A text question is fact
    checked. A picture question has its picture fetched and looked at
    (pipeline.pictures); faces, landmarks and paintings are fact checked
    too, since their questions may carry a clue."""
    if not kind:
        return verify(category, difficulty, questions)
    from pipeline import pictures
    from pipeline.scenes import art
    verdicts = ["ok"] * len(questions)
    if kind in ("faces", "landmarks", "paintings"):
        shown = [{**q, "question": f"{q['question']} [The picture shows: {q['subject']}]"}
                 for q in questions]
        verdicts = verify(category, difficulty, shown)
    style = art.resolve(channel.scenes.art)
    for i, q in enumerate(questions):
        if verdicts[i] != "ok":
            continue
        try:
            if kind == "dingbats" and pictures.dingbat_trivial(q.get("layout"), q["answer"]):
                raise pictures.PictureError("just spells its answer out", user_message="")
            found = pictures.fetch(kind, q.get("layout") if kind == "dingbats" else q["subject"], style)
            problem = pictures.check(kind, found["path"], q["question"], q["answer"])
        except PipelineError as exc:
            problem = str(exc)
        if problem:
            log.info(f"  [quiz] Q{i + 1} picture: {problem}")
            verdicts[i] = "picture"
        else:
            q["picture"] = {"kind": kind, **found}
    return verdicts


def _write_checked(channel, category: str, difficulty: str, extra: str = "",
                   kind: str = None) -> Script:
    """Write a round, fact-check it (and look at its pictures), and check
    it against every question the channel has asked (see the module
    docstring)."""
    context = context_questions(channel.key, category)
    data = _write(category, difficulty, channel, context, extra, kind)
    questions = data["questions"]
    verdicts = _check(channel, category, difficulty, questions, kind)
    for i in repeats(questions, channel.key):
        log.info(f"  [quiz] Q{i + 1} repeats a question already asked on this channel")
        verdicts[i] = "repeat"
    for i in round_clashes(questions):
        log.info(f"  [quiz] Q{i + 1} clashes with an earlier question in this round")
        verdicts[i] = "clash"

    # Replace what didn't pass from a fresh set of candidates, keeping those
    # that pass. Once for a text round; up to three times for a picture
    # round, where more candidates fall (dingbats especially).
    failed = []
    for _ in range(PICTURE_REWRITES if kind else 1):
        bad = [i for i, v in enumerate(verdicts) if v != "ok"]
        if not bad:
            break
        log.info(f"  [quiz] replacing {len(bad)} question(s) the checks didn't pass")
        kept = [q for i, q in enumerate(questions) if i not in bad]
        keep = [q["question"] for q in kept]
        failed += [questions[i] for i in bad]
        instead = (f"Only the questions are needed this time; the intro and sign-off "
                   f"will be discarded. These stay in the round, so no question may "
                   f"share an answer or a subject with them:\n{_listed(kept)}\n\n"
                   f"These didn't work and mustn't come back:\n{_listed(failed)}")
        rewritten = _write(category, difficulty, channel,
                           (context[0] + [{"question": q} for q in keep], context[1]),
                           "\n\n".join(p for p in (extra, instead) if p), kind)
        replacement = rewritten["questions"]
        data["pronunciations"] = {**rewritten.get("pronunciations", {}),
                                  **data.get("pronunciations", {})}
        # Nothing that repeats or gives away an answer already in the round
        # (a replacement "capital of Italy" beside "which country is shaped
        # like a boot"), nor anything asked before or already refused.
        taken = " ".join(f"{q['question']} {q['answer']}" for q in kept)
        again = (set(repeats(replacement, channel.key)) | set(repeats(replacement, channel.key, kept))
                 | set(repeats(replacement, channel.key, failed)))
        fresh = [q for i, q in enumerate(replacement)
                 if i not in again and (kind or q["question"] not in keep)
                 and not _mentions(taken, q["answer"])
                 and not any(_mentions(f"{q['question']} {q['answer']}", q2["answer"])
                             for q2 in kept)][:len(bad) * 2]
        fresh_verdicts = _check(channel, category, difficulty, fresh, kind) if fresh else []
        passing = [q for q, v in zip(fresh, fresh_verdicts) if v == "ok"]
        failed += [q for q, v in zip(fresh, fresh_verdicts) if v != "ok"]
        for slot in bad:
            if not passing:
                break
            questions[slot] = {**passing.pop(0), "lead_in": questions[slot]["lead_in"]}
            verdicts[slot] = "ok"
        questions[0]["lead_in"] = ""

    unverified = [i + 1 for i, v in enumerate(verdicts) if v != "ok"]
    if unverified:
        log.warning(f"  [quiz] question(s) {unverified} still didn't pass the checks; "
                    f"this video will wait for a person.")
    return to_script(data, channel, category, difficulty, unverified)


def to_script(data: dict, channel, category: str, difficulty: str,
              unverified: list = ()) -> Script:
    """Spoken segments: intro, then question and answer for each, then
    the sign-off. The silence after each question is its countdown."""
    quiz = channel.quiz
    segments = [Segment(text=data["intro"].strip())]
    rows = []
    for q in data["questions"]:
        ask = len(segments)
        segments.append(Segment(text=f"{q['lead_in']} {q['question']}".strip(),
                                pause_after=float(quiz.countdown_seconds)))
        segments.append(Segment(text=q["spoken_answer"], pause_after=float(quiz.answer_pause)))
        row = {"question": q["question"], "answer": q["answer"],
               "spoken_answer": q["spoken_answer"], "ask": ask, "reveal": ask + 1}
        for key in ("kind", "subject", "layout", "picture"):
            if q.get(key):
                row[key] = q[key]
        rows.append(row)
    segments.append(Segment(text=data["outro"].strip()))
    titles = [t.strip() for t in data.get("title_options") or [] if t.strip()]
    return Script(segments=segments,
                  title_options=titles or [f"{category} quiz: {difficulty}"],
                  description_body=(data.get("description_body") or "").strip(),
                  quiz={"category": category, "difficulty": difficulty, "questions": rows,
                        "countdown": float(quiz.countdown_seconds),
                        "unverified": list(unverified),
                        # Respellings for the voice only (pipeline.tts.speakable).
                        "pronunciations": dict(data.get("pronunciations") or {}),
                        "credits": sorted({q["picture"]["credit"] for q in data["questions"]
                                           if (q.get("picture") or {}).get("credit")})})


# --- the board -------------------------------------------------------------

BOARD_FPS = 30
KICKER_Y, CARD_TOP, CARD_H = 120, 200, 440
LIST_TOP, LIST_BOTTOM = 690, 1560          # clear of the Shorts UI along the bottom
LIST_W, TIMER_X, TIMER_Y, TIMER_R = 680, 790, 720, 105
RING = 2 * math.pi * TIMER_R

BOARD_CSS = f"""
.board {{ position: absolute; inset: 0; }}
.kicker {{ position: absolute; left: 60px; right: 60px; top: {KICKER_Y}px; display: flex;
  justify-content: center; gap: 22px; align-items: center; }}
.kicker .cat {{ font-family: var(--display); font-weight: var(--dw); font-size: 46px;
  letter-spacing: .08em; text-transform: uppercase; color: var(--ink);
  white-space: nowrap; overflow: hidden; min-width: 0; max-width: 690px; }}
.kicker .lvl {{ padding: 8px 26px; font-size: 36px; flex: none; white-space: nowrap; }}
.qcard {{ position: absolute; left: 60px; width: 960px; top: {CARD_TOP}px; height: {CARD_H}px; }}
.qcard > div {{ position: absolute; inset: 0; display: flex; flex-direction: column;
  justify-content: center; align-items: center; padding: 40px 56px; text-align: center; }}
.qnum {{ font-family: var(--display); font-weight: var(--dw); font-size: 36px; color: var(--soft);
  letter-spacing: .1em; margin-bottom: 18px; }}
.qtext {{ font-family: var(--display); font-weight: var(--dw); font-size: 66px; line-height: 1.15;
  color: var(--on-card); width: 100%; max-height: 300px; overflow: hidden; }}
.qtext.small {{ font-size: 44px; max-height: 60px; white-space: nowrap; }}
.pic {{ width: 100%; height: 270px; display: flex; align-items: center; justify-content: center;
  margin-bottom: 14px; }}
.pic img {{ max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 12px; }}
.intro-cat {{ font-family: var(--display); font-weight: var(--dw); font-size: 96px; line-height: 1.05;
  color: var(--on-card); width: 100%; max-height: 220px; overflow: hidden; }}
.intro-sub {{ font-size: 44px; color: var(--soft); margin-top: 20px; }}
.rows {{ position: absolute; left: 60px; top: {LIST_TOP}px; width: {LIST_W}px;
  height: {LIST_BOTTOM - LIST_TOP}px; display: flex; flex-direction: column; justify-content: space-between; }}
.row {{ position: relative; display: flex; align-items: center; gap: 22px; }}
.row .n {{ width: 86px; flex: none; font-family: var(--display); font-weight: var(--dw);
  font-size: 50px; color: var(--a1); text-align: right; }}
.row .a {{ flex: 1; height: 100%; display: flex; align-items: center; font-family: var(--display);
  font-weight: var(--dw); font-size: 48px; color: var(--ink); white-space: nowrap; overflow: hidden; }}
.row .line {{ position: absolute; left: 108px; right: 0; bottom: 10px; height: 4px;
  background: var(--soft); opacity: .35; border-radius: 2px; }}
.row .now {{ position: absolute; left: -14px; right: -14px; top: 2px; bottom: 2px; border-radius: 18px;
  border: 5px solid var(--a2); }}
.timer {{ position: absolute; left: {TIMER_X}px; top: {TIMER_Y}px; width: {2 * TIMER_R + 40}px;
  height: {2 * TIMER_R + 40}px; }}
.timer svg {{ position: absolute; inset: 0; }}
.timer .track {{ fill: none; stroke: var(--soft); stroke-opacity: .25; stroke-width: 18px; }}
.timer .fill {{ fill: none; stroke: var(--a2); stroke-width: 18px; stroke-linecap: round;
  stroke-dasharray: {RING:.1f}px {RING:.1f}px; stroke-dashoffset: calc(var(--p, 0) * {RING:.1f}px);
  transform: rotate(-90deg); transform-origin: 50% 50%; }}
.timer .digit {{ position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  font-family: var(--display); font-weight: var(--dw); font-size: 110px; color: var(--ink); }}
.end-big {{ font-family: var(--display); font-weight: var(--dw); font-size: 82px; line-height: 1.1;
  color: var(--on-card); }}
"""


def picture_uri(q: dict, style: dict = None) -> str:
    """A picture question's picture for a board page, fetched again if
    its cached file has gone; "" for a question with none."""
    from pipeline import pictures
    kind = q.get("kind")
    if not kind:
        return ""
    path = (q.get("picture") or {}).get("path", "")
    if not path or not Path(path).exists():
        subject = q.get("layout") if kind == "dingbats" else q.get("subject")
        path = pictures.fetch(kind, subject, style)["path"]
    return pictures.data_uri(path)


PICTURE_CARD_H, PICTURE_LIST_TOP = 700, 950
PICTURE_CSS = f"""
.qcard {{ height: {PICTURE_CARD_H}px; }}
.qcard .pic {{ height: {PICTURE_CARD_H - 240}px; }}
.rows {{ top: {PICTURE_LIST_TOP}px; height: {LIST_BOTTOM - PICTURE_LIST_TOP}px; }}
.row .n {{ font-size: 40px; }} .row .a {{ font-size: 40px; }}
.timer {{ top: {PICTURE_LIST_TOP + 40}px; }}
"""


def _words_between(word_timings: list, start: float, end: float) -> list:
    return [w for w in word_timings if start <= w.start < end]


def timeline(script: Script, word_timings: list) -> dict:
    """When each part of the board happens, in narration seconds, from
    the real voiceover."""
    segments, quiz = script.segments, script.quiz
    rows = []
    for q in quiz["questions"]:
        ask, reveal = segments[q["ask"]], segments[q["reveal"]]
        spoken = _words_between(word_timings, ask.start, ask.end)
        spoken_end = spoken[-1].end if spoken else ask.start
        countdown_end = reveal.start
        countdown_start = max(spoken_end, countdown_end - quiz["countdown"])
        rows.append({"ask": ask.start, "countdown": countdown_start, "reveal": countdown_end,
                     "done": reveal.end})
    return {"questions": rows, "outro": segments[-1].start, "end": segments[-1].end}


def _in(t, anim="fade", dur=0.35, out=None) -> str:
    attrs = f"data-in='{max(0.0, t):.3f}' data-anim='{anim}' data-dur='{dur}'"
    return attrs + (f" data-out='{out:.3f}'" if out is not None else "")


def board_html(script: Script, times: dict, style: dict, duration: float) -> str:
    """The whole video's board as one seekable page."""
    from pipeline.templates import page, theme

    esc = html.escape
    quiz = script.quiz
    questions, rows_t = quiz["questions"], times["questions"]
    first_ask = rows_t[0]["ask"] if rows_t else duration
    n = len(questions)
    # A picture round needs the picture big: a taller card, and the answer
    # list (answers only) tighter underneath.
    pictured = bool(questions) and all(q.get("kind") for q in questions)
    list_top = PICTURE_LIST_TOP if pictured else LIST_TOP

    card = [f"<div {_in(0, 'fade', 0.3, first_ask - 0.35)}>"
            f"<div class='intro-cat' data-fit='54'>{esc(quiz['category'])}</div>"
            f"<div class='intro-sub'>{n} questions &middot; keep score</div></div>"]
    for i, (q, t) in enumerate(zip(questions, rows_t)):
        leaves = rows_t[i + 1]["ask"] - 0.3 if i + 1 < n else times["outro"] - 0.3
        pic = picture_uri(q)
        if pic:
            card.append(f"<div {_in(t['ask'], 'rise', 0.45, leaves)}>"
                        f"<div class='qnum'>QUESTION {i + 1}</div>"
                        f"<div class='pic'><img src='{pic}'></div>"
                        f"<div class='qtext small' data-fit='28'>{esc(q['question'])}</div></div>")
            continue
        card.append(f"<div {_in(t['ask'], 'rise', 0.45, leaves)}>"
                    f"<div class='qnum'>QUESTION {i + 1}</div>"
                    f"<div class='qtext' data-fit='34'>{esc(q['question'])}</div></div>")
    card.append(f"<div {_in(times['outro'], 'pop', 0.5)}>"
                f"<div class='end-big'>How many did you get?</div>"
                f"<div class='intro-sub'>Out of {n}</div></div>")

    row_html = []
    for i, (q, t) in enumerate(zip(questions, rows_t)):
        row_html.append(
            f"<div class='row' style='height:{(LIST_BOTTOM - list_top) / n - 6:.0f}px' "
            f"{_in(0.25 + 0.07 * i, 'slide-left', 0.4)}>"
            f"<div class='now' {_in(t['ask'], 'fade', 0.25, t['done'])}></div>"
            f"<div class='n'>{i + 1}.</div>"
            f"<div class='a' data-fit='26' {_in(t['reveal'], 'wipe', 0.45)}>{esc(q['answer'])}</div>"
            f"<div class='line'></div></div>")

    timers = []
    for t in rows_t:
        span = max(0.5, t["reveal"] - t["countdown"])
        seconds = max(1, math.ceil(span - 0.05))
        digits = "".join(
            f"<div class='digit' {_in(t['countdown'] + k * span / seconds, 'pop', 0.25, t['countdown'] + (k + 1) * span / seconds - 0.1)}>"
            f"{seconds - k}</div>" for k in range(seconds))
        size = 2 * TIMER_R + 40
        timers.append(
            f"<div class='timer' {_in(t['countdown'] - 0.2, 'pop', 0.3, t['reveal'])}>"
            f"<svg width='{size}' height='{size}'><circle class='track' cx='{size / 2}' cy='{size / 2}' r='{TIMER_R}'/>"
            f"<circle class='fill' cx='{size / 2}' cy='{size / 2}' r='{TIMER_R}' "
            f"data-in='{t['countdown']:.3f}' data-anim='none' data-dur='{span:.3f}' "
            f"data-steps='{max(10, round(span * 10))}'/></svg>{digits}</div>")

    stage = (f"<div class='board'>"
             f"<div class='kicker' {_in(0, 'fade', 0.3)}><span class='cat' data-fit='24'>{esc(quiz['category'])} quiz</span>"
             f"<span class='chip filled a2 lvl'>{esc(quiz['difficulty'])}</span></div>"
             f"<div class='card qcard'>{''.join(card)}</div>"
             f"<div class='rows'>{''.join(row_html)}</div>{''.join(timers)}</div>")
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        f"{theme.css(style)}{BOARD_CSS}{PICTURE_CSS if pictured else ''}"
        f".bg-grain {{ background-image: url({page.GRAIN}); }}"
        # The ring drains linearly; the engine's default entrance styles
        # would fade and move it.
        "[data-anim='none'] { opacity: 1; transform: none; }"
        ".bg-pattern { transform: none; }"
        "</style></head><body>"
        "<div class='bg'><div class='bg-pattern'></div><div class='bg-grain'></div>"
        "<div class='bg-vignette'></div></div>"
        f"{stage}"
        f"<script>window.TEMPLATE_DURATION = {json.dumps(duration)};"
        # Still between moments, so unchanged frames are reused (render.encode).
        "window.STATIC_BACKGROUND = true;</script>"
        f"<script>{page.RUNTIME.read_text(encoding='utf-8')}</script>"
        "</body></html>")


def timer_cues(times: dict) -> list:
    """[(narration seconds, effect, gain)]: a tick each second of every
    countdown and a chime as the answer lands. Exempt from the sparse
    limits other effects keep to (pipeline.sound): the clock is the
    point here."""
    cues = []
    for t in times["questions"]:
        span = max(0.5, t["reveal"] - t["countdown"])
        seconds = max(1, math.ceil(span - 0.05))
        cues += [(t["countdown"] + k * span / seconds, "tock", 0.8) for k in range(seconds)]
        cues.append((t["reveal"], "chime", 0.55))
    return cues


def board(plan):
    """Pipeline stage (in place of pipeline.visuals for a quiz): film the
    board for the whole narration and hand it to assembly as one scene
    spanning every segment."""
    from core import job_context
    from pipeline.scenes import art, render

    job_context.report_stage(3)
    script = plan.script
    duration = len(plan.voiceover.samples) / plan.voiceover.fps
    times = timeline(script, plan.voiceover.word_timings)
    style = art.resolve(plan.channel.scenes.art)
    page_html = board_html(script, times, style, duration)

    # In the render's working folder, removed once the video is finished
    # (pipeline.assemble.remove_working_files).
    clip = Path(plan.out_dir) / f"{plan.stem}_scenes" / "board.mp4"
    log.info(f"[3/5] Filming the quiz board ({duration:.0f} seconds)...")
    render.render_page(page_html, duration, clip, fps=BOARD_FPS)
    clip.with_suffix(".json").write_text(json.dumps({"timer_cues": timer_cues(times)}),
                                         encoding="utf-8")
    plan.scene_clips = [{"first": 0, "last": len(script.segments) - 1, "clip": str(clip),
                         "kind": "quiz"}]
    # A picture round's credits go in the description (run._finish).
    plan.art_credits = list(script.quiz.get("credits") or [])
    plan.visual_plan = [{"index": 0, "medium": "quiz board", "template": "quiz",
                         "reason": "the quiz format"}]
    return plan


# --- a still for the settings page -------------------------------------------

SAMPLE_ROUND = [("What is the capital of Australia?", "Canberra"),
                ("How many sides does a hexagon have?", "Six"),
                ("Which planet is known as the Red Planet?", "Mars"),
                ("What is the chemical symbol for gold?", "Au")]


def sample_still(style: dict, cache_dir: Path, questions: int = 10) -> Path:
    """The board mid-countdown on question 3 of a sample round, in this
    look: what the settings page shows for a quiz channel's look. Cached
    by content, so each look is drawn once."""
    import hashlib
    from core.channels import ChannelConfig
    from pipeline.plan import WordTiming
    from pipeline.scenes import render

    digest = hashlib.sha1(json.dumps([style, questions, page_version()], sort_keys=True)
                          .encode()).hexdigest()[:16]
    out = Path(cache_dir) / f"quiz_{digest}.jpg"
    if out.exists():
        return out
    channel = ChannelConfig(key="sample", format="quiz")
    channel.quiz.questions = questions
    rows = [SAMPLE_ROUND[i % len(SAMPLE_ROUND)] for i in range(questions)]
    script = to_script({"intro": "Intro.", "outro": "Outro.",
                        "questions": [{"lead_in": "", "question": q, "answer": a,
                                       "spoken_answer": a} for q, a in rows]},
                       channel, "General knowledge", "Medium")
    t, words = 0.0, []
    for seg in script.segments:
        seg.start = t
        words.append(WordTiming("w", t, t + 2.0))
        t += 2.2 + (seg.pause_after or 0.3)
        seg.end = t
    times = timeline(script, words)
    out.parent.mkdir(parents=True, exist_ok=True)
    render.page_frame(board_html(script, times, style, t), times["questions"][2]["countdown"] + 1.4, out)
    return out


def page_version() -> float:
    """Changes when the board's code does, so cached stills are redrawn."""
    return Path(__file__).stat().st_mtime


# --- a round's sidecar, for long quizzes -------------------------------------------

def round_sidecar(video_path) -> Path:
    video_path = Path(video_path)
    return video_path.with_name(f"{video_path.stem}_quiz.json")


def save_round(plan) -> Path:
    """Where each question and answer sits in this short's voice track,
    beside the video: a long quiz (pipeline.longform) cuts them from it
    rather than paying to voice them again."""
    quiz = plan.script.quiz
    segments = plan.script.segments

    def spoken(segment) -> list:
        # A segment runs to the next one's start, its pause included.
        return [round(segment.start, 3), round(segment.end - float(segment.pause_after or 0), 3)]

    data = {
        "version": 1,
        "category": quiz.get("category", ""),
        "difficulty": quiz.get("difficulty", ""),
        "level": level_of(plan.channel, quiz.get("difficulty", "")),
        "audio": Path(plan.audio_path).name,
        "unverified": list(quiz.get("unverified") or []),
        "credits": list(quiz.get("credits") or []),
        "questions": [{"question": q["question"], "answer": q["answer"],
                       "spoken_answer": q.get("spoken_answer", ""),
                       **{k: q[k] for k in ("kind", "subject", "layout", "picture") if q.get(k)},
                       "ask_audio": spoken(segments[q["ask"]]),
                       "answer_audio": spoken(segments[q["reveal"]])}
                      for q in quiz.get("questions") or []],
    }
    path = round_sidecar(plan.video_path)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return path
