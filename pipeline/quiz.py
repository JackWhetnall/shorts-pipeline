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
from pathlib import Path

from core import curriculum
from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline.llm import SystemBlock, call_json
from pipeline.plan import Script, Segment

log = get_logger(__name__)

WRITE_MAX_TOKENS = 10000
WRITE_EFFORT = "medium"
VERIFY_MAX_TOKENS = 8000
VERIFY_EFFORT = "medium"
# Earlier questions shown to the writer so it doesn't ask them again:
# this category's first, then the channel's others.
HISTORY_QUESTIONS = 250
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
- `spoken_answer`: how the host gives it, under 20 words. When the
  answer is short, the host usually says it twice, sometimes with the
  question's context the second time ("Beijing. Beijing is the capital
  of China."), sometimes with a quick interesting fact, sometimes just
  plainly. Mix these across the round; not the same shape every time.
- `lead_in`: for every question after the first, the host's short move
  to it, which says its number: "Question two.", "Number three." and so
  on, with the odd bit of colour ("halfway there", "last one"). Under 7
  words. Empty for the first question.

Difficulty, for the whole round:
- Easy: most adults would know it.
- Medium: a regular at the pub quiz would.
- Hard: a keen quizzer would; most people wouldn't.
- Very hard: specialist knowledge, or a detail most enthusiasts miss.
- Impossible: only an expert, or someone who happens to know an obscure
  but real and checkable fact. Still fair: never a trick, never
  something unknowable.
Within the round, ease in: the first question or two a touch gentler.

Cover the category broadly, not one narrow corner of it, and never ask
two questions whose answers give each other away.

The sign-off (under 30 words): ask how many they got, and either for
their score and next category in the comments or to send it to a friend
to see how they do. Vary it.

Titles: short (under 60 characters), naming the category and the
difficulty, inviting the viewer to test themselves. The description body:
one or two plain sentences about the round, no hashtags.
""".strip()


def _schema() -> dict:
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
    return {
        "type": "object",
        "properties": {
            "intro": {"type": "string"},
            "questions": {"type": "array", "items": question},
            "outro": {"type": "string"},
            "title_options": {"type": "array", "items": {"type": "string"}},
            "description_body": {"type": "string"},
        },
        "required": ["intro", "questions", "outro", "title_options", "description_body"],
        "additionalProperties": False,
    }


VERIFY_SYSTEM = """
You are the fact checker for a quiz video before it is published. For
each question, first work out the answer yourself, then compare it with
the proposed answer. Judge each one:

- "ok": the proposed answer is right, and it is the only reasonable
  answer to the question as worded.
- "wrong": the proposed answer is incorrect.
- "ambiguous": more than one answer is defensible, or the wording is
  unclear enough that a fair player could answer differently and be
  right.
- "dated": the answer depends on when it's asked (a current holder,
  record, population or price) and could be out of date.

Be strict about "wrong" and "ambiguous": a published wrong answer is
what ruins a quiz channel. Don't flag a question for being easy or hard.
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
                    "your_answer": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["ok", "wrong", "ambiguous", "dated"]},
                    "note": {"type": "string"},
                },
                "required": ["number", "your_answer", "verdict", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


# --- what this round is --------------------------------------------------

def round_of(seed, channel) -> tuple:
    """(category, difficulty) for a seed. The topic plan knows exactly;
    a bare seed title of the form "Science: Hard" is split instead."""
    if seed.topic_id and curriculum.exists(channel.key):
        entry = curriculum.find(channel.key, seed.topic_id)
        if entry:
            topic = curriculum.find_topic(channel.key, entry["topic"]) or {}
            difficulty = entry.get("angle") or ""
            if topic.get("title") and difficulty:
                return topic["title"], difficulty
    title = seed.topic or seed.title or "General knowledge"
    for sep in (":", " — ", " - "):
        if sep in title:
            category, difficulty = title.split(sep, 1)
            return category.strip(), difficulty.split("(")[0].strip()
    return title.strip(), (channel.quiz.difficulties or ["Medium"])[0]


def subtopic_rows(category: str, difficulties: list, round_number: int = 1) -> list:
    """One topic's subtopics for a quiz channel: one per difficulty.
    Written by rule rather than by a model: free, and exactly what the
    format needs. Titles carry the category and, after the first, the
    round, because the plan drops any title it already has."""
    suffix = f" (round {round_number})" if round_number > 1 else ""
    return [{"title": f"{category}: {d}{suffix}", "angle": d}
            for d in difficulties if str(d).strip()]


def top_up(channel) -> int:
    """Another round for every category when the plan runs low. Returns
    how many quizzes were added (0 when it isn't low)."""
    if not curriculum.exists(channel.key):
        return 0
    data = curriculum.load(channel.key)
    pending = sum(1 for s in data["subtopics"] if s["status"] == curriculum.PENDING)
    if pending >= curriculum.LOW_WATER_MARK or not data["topics"]:
        return 0
    added = 0
    for topic in data["topics"]:
        rounds = 1 + sum(1 for s in data["subtopics"] if s["topic"] == topic["id"]) // max(
            1, len(channel.quiz.difficulties))
        before = len(curriculum.load(channel.key)["subtopics"])
        curriculum.add_subtopics(channel.key, topic["id"],
                                 subtopic_rows(topic["title"], channel.quiz.difficulties, rounds))
        added += len(curriculum.load(channel.key)["subtopics"]) - before
    log.info(f"{channel.key}: added {added} quizzes, another round of every category")
    return added


def asked_before(channel_key: str, category: str) -> list:
    """Questions this channel has already asked, this category's first.
    From the originality history, which records every video's script."""
    from pipeline import similarity

    history = similarity._load().get(channel_key) or []
    same, other = [], []
    for entry in reversed(history):
        text = entry.get("quiz") or {}
        for q in text.get("questions") or []:
            (same if text.get("category", "").lower() == category.lower() else other).append(
                q.get("question", ""))
    return [q for q in same + other if q][:HISTORY_QUESTIONS]


# --- writing ---------------------------------------------------------------

def _clean_round(data: dict, count: int) -> dict:
    questions = []
    for q in data.get("questions") or []:
        question = " ".join((q.get("question") or "").split())
        answer = " ".join((q.get("answer") or "").split())
        spoken = " ".join((q.get("spoken_answer") or "").split()) or answer
        if not question or not answer:
            continue
        questions.append({"lead_in": " ".join((q.get("lead_in") or "").split()),
                          "question": question[:QUESTION_CHARS * 2],
                          "answer": answer, "spoken_answer": spoken})
    if len(questions) < count:
        raise PipelineError(f"quiz came back with {len(questions)} of {count} questions",
                            user_message="The quiz came back short of questions. Try again.")
    data["questions"] = questions[:count]
    data["questions"][0]["lead_in"] = ""
    return data


def _user(category: str, difficulty: str, count: int, channel, avoid: list, extra: str) -> str:
    listed = "\n".join(f"- {q}" for q in avoid)
    return (f"Category: {category}\nDifficulty: {difficulty}\nQuestions: exactly {count}\n\n"
            + (f"Already asked on this channel; don't ask these again or anything that "
               f"gives the same answer to the same fact:\n{listed}\n\n" if listed else "")
            + extra)


def _write(category, difficulty, channel, avoid, extra="") -> dict:
    count = channel.quiz.questions
    system = [SystemBlock(SYSTEM, cacheable=True),
              SystemBlock(f"This channel's own brief for its host and its rounds:\n\n"
                          f"{channel.style_prompt}")]
    data = call_json(system, _user(category, difficulty, count, channel, avoid, extra), _schema(),
                     operation="quiz_write", max_tokens=WRITE_MAX_TOKENS, effort=WRITE_EFFORT)
    return _clean_round(data, count)


def verify(category: str, difficulty: str, questions: list) -> list:
    """[verdict per question] from an independent check: "ok", "wrong",
    "ambiguous" or "dated". A check that can't run returns "unchecked"
    for every question, which holds the video rather than passing it."""
    listed = "\n".join(f"{i + 1}. Q: {q['question']}\n   Proposed answer: {q['answer']}"
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
                         f"(checker says {row.get('your_answer', '')!r})")
    return verdicts


def write_script(seed, channel, avoid: str = "") -> Script:
    """The round as a Script, fact-checked. `avoid` is the originality
    gate's note when a first attempt read too much like an earlier one."""
    category, difficulty = round_of(seed, channel)
    asked = asked_before(channel.key, category)
    data = _write(category, difficulty, channel, asked, avoid)
    questions = data["questions"]
    verdicts = verify(category, difficulty, questions)

    bad = [i for i, v in enumerate(verdicts) if v != "ok"]
    if bad:
        log.info(f"  [quiz] replacing {len(bad)} question(s) the fact check didn't pass")
        keep = [q["question"] for i, q in enumerate(questions) if i not in bad]
        replacement = _write(category, difficulty, channel, asked + keep,
                             "Only the questions are needed this time; the intro and sign-off "
                             "will be discarded.")["questions"]
        fresh = [q for q in replacement if q["question"] not in keep][:len(bad)]
        fresh_verdicts = verify(category, difficulty, fresh) if fresh else []
        for slot, q, v in zip(bad, fresh, fresh_verdicts):
            questions[slot] = {**q, "lead_in": questions[slot]["lead_in"]}
            verdicts[slot] = v
        questions[0]["lead_in"] = ""

    unverified = [i + 1 for i, v in enumerate(verdicts) if v != "ok"]
    if unverified:
        log.warning(f"  [quiz] question(s) {unverified} still didn't pass the fact check; "
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
        rows.append({"question": q["question"], "answer": q["answer"],
                     "spoken_answer": q["spoken_answer"], "ask": ask, "reveal": ask + 1})
    segments.append(Segment(text=data["outro"].strip()))
    titles = [t.strip() for t in data.get("title_options") or [] if t.strip()]
    return Script(segments=segments,
                  title_options=titles or [f"{category} quiz: {difficulty}"],
                  description_body=(data.get("description_body") or "").strip(),
                  quiz={"category": category, "difficulty": difficulty, "questions": rows,
                        "countdown": float(quiz.countdown_seconds),
                        "unverified": list(unverified)})


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
  letter-spacing: .08em; text-transform: uppercase; color: var(--ink); }}
.kicker .lvl {{ padding: 8px 26px; font-size: 36px; }}
.qcard {{ position: absolute; left: 60px; width: 960px; top: {CARD_TOP}px; height: {CARD_H}px; }}
.qcard > div {{ position: absolute; inset: 0; display: flex; flex-direction: column;
  justify-content: center; align-items: center; padding: 40px 56px; text-align: center; }}
.qnum {{ font-family: var(--display); font-weight: var(--dw); font-size: 36px; color: var(--soft);
  letter-spacing: .1em; margin-bottom: 18px; }}
.qtext {{ font-family: var(--display); font-weight: var(--dw); font-size: 66px; line-height: 1.15;
  color: var(--on-card); width: 100%; max-height: 300px; overflow: hidden; }}
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

    card = [f"<div {_in(0, 'fade', 0.3, first_ask - 0.35)}>"
            f"<div class='intro-cat' data-fit='54'>{esc(quiz['category'])}</div>"
            f"<div class='intro-sub'>{n} questions &middot; keep score</div></div>"]
    for i, (q, t) in enumerate(zip(questions, rows_t)):
        leaves = rows_t[i + 1]["ask"] - 0.3 if i + 1 < n else times["outro"] - 0.3
        card.append(f"<div {_in(t['ask'], 'rise', 0.45, leaves)}>"
                    f"<div class='qnum'>QUESTION {i + 1}</div>"
                    f"<div class='qtext' data-fit='34'>{esc(q['question'])}</div></div>")
    card.append(f"<div {_in(times['outro'], 'pop', 0.5)}>"
                f"<div class='end-big'>How many did you get?</div>"
                f"<div class='intro-sub'>Out of {n}</div></div>")

    row_html = []
    for i, (q, t) in enumerate(zip(questions, rows_t)):
        row_html.append(
            f"<div class='row' style='height:{(LIST_BOTTOM - LIST_TOP) / n - 6:.0f}px' "
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
            f"data-in='{t['countdown']:.3f}' data-anim='none' data-dur='{span:.3f}'/></svg>{digits}</div>")

    stage = (f"<div class='board'>"
             f"<div class='kicker' {_in(0, 'fade', 0.3)}><span class='cat'>{esc(quiz['category'])} quiz</span>"
             f"<span class='chip filled a2 lvl'>{esc(quiz['difficulty'])}</span></div>"
             f"<div class='card qcard'>{''.join(card)}</div>"
             f"<div class='rows'>{''.join(row_html)}</div>{''.join(timers)}</div>")
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        f"{theme.css(style)}{BOARD_CSS}"
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

    clip = Path(plan.out_dir) / f"{plan.stem}_TEMP_board.mp4"
    log.info(f"[3/5] Filming the quiz board ({duration:.0f} seconds)...")
    render.render_page(page_html, duration, clip, fps=BOARD_FPS)
    clip.with_suffix(".json").write_text(json.dumps({"timer_cues": timer_cues(times)}),
                                         encoding="utf-8")
    plan.scene_clips = [{"first": 0, "last": len(script.segments) - 1, "clip": str(clip),
                         "kind": "quiz"}]
    plan.visual_plan = [{"index": 0, "medium": "quiz board", "template": "quiz",
                         "reason": "the quiz format"}]
    return plan
