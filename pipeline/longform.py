"""
Long quizzes: several finished quiz shorts, recut into one widescreen video.

A long quiz is made from rounds that already exist as shorts. Each short
kept its voice track and where every question and spoken answer sits in
it (pipeline.quiz.save_round), so the long video cuts those out rather
than voicing them again. The only new voice is the host's joining lines:
a welcome, a line into each round, "pens down" before each set of answers,
and a sign-off. That is about a thousand characters for twenty minutes of
video, where six new rounds would have cost about seven thousand.

Two variants from the same machinery:

- "after_each": question, clock, answer, as in the shorts;
- "at_end": a round's ten questions with their clocks, then each question
  read again and its row turning smoothly into the answer as it's given.

The board is widescreen: the numbers 1-10 down the left, each question
appearing in its row as it's read, and a large panel on the right with
the question, the clock and the answer. Rounds are one difficulty, or
"rising" (each round harder than the last). A round is used in one long
video only, so two long videos never repeat questions. See decision 044.
"""

from __future__ import annotations

import html
import json
import math
import random
import re
import shutil
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from core import curriculum, gallery, job_context
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import PROJECT_ROOT, slugify, unique_stem
from pipeline import quiz
from pipeline.llm import SystemBlock, call_json

log = get_logger(__name__)

W, H = 1920, 1080
THUMB = (1280, 720)
FPS = 30
VARIANTS = ("after_each", "at_end")
RISING = "rising"

LINK_PAUSE = 0.5          # after a joining line
ROUND_GAP = 1.0           # between rounds
CLOCK_LEAD = 1.0          # between a question and its clock starting
CLOCK_TAIL = 1.0          # between a clock ending and what comes next
REASK_GAP = 1.1           # at_end: between the question read again and its answer
TICKS = 5                 # the clock ticks audibly for its last few seconds only
FINISH_TEXT = ("Finish your answers", "Last chance for this round", "Pens ready: final answers",
               "Fill in the gaps", "Any last answers?")
FADE = 0.012              # seconds of fade on every cut, so none of them clicks
LINKS_MAX_TOKENS = 6000


class LongformError(PipelineError):
    pass


# --- the rounds available ----------------------------------------------------------

def _out_root(channel) -> Path:
    return gallery.resolve_output_dir(channel.output_dir)


def _round_info(channel, video: Path) -> dict:
    """Category, difficulty and level for a finished quiz short, from its
    sidecar or, for one made before sidecars, the topic plan and bank."""
    sidecar = quiz.round_sidecar(video)
    if sidecar.exists():
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return {"stem": video.stem, "video": video, "category": quiz.base_category(data["category"]),
                "difficulty": data["difficulty"], "level": float(data.get("level") or 5),
                "ready": True}
    if not curriculum.exists(channel.key):
        return None
    entry = next((s for s in curriculum.subtopics(channel.key) if s.get("video_stem") == video.stem), None)
    if entry is None or not (video.with_name(f"{video.stem}_audio.mp3")).exists():
        return None
    topic = curriculum.find_topic(channel.key, entry["topic"]) or {}
    difficulty = entry.get("angle") or ""
    return {"stem": video.stem, "video": video, "category": quiz.base_category(topic.get("title", "")),
            "difficulty": difficulty, "level": quiz.level_of(channel, difficulty), "ready": False}


def used_rounds(channel) -> dict:
    """{round stem: how many long videos it's in} (a discarded long video
    frees its rounds)."""
    used = {}
    for video in gallery.videos_in(_out_root(channel), long=True):
        if gallery.load_publish_info(video)["discarded"]:
            continue
        sidecar = quiz.round_sidecar(video)
        if sidecar.exists():
            for stem in json.loads(sidecar.read_text(encoding="utf-8")).get("rounds") or []:
                used[stem] = used.get(stem, 0) + 1
    return used


def available_rounds(channel) -> list:
    """Every finished, undiscarded quiz short that hasn't reached the
    channel's limit of long videos (`quiz.longform_round_reuse`), least
    reused first, then published ones, then oldest."""
    root = _out_root(channel)
    if not root.exists():
        return []
    used = used_rounds(channel)
    limit = max(1, int(channel.quiz.longform_round_reuse or 1))
    rows = []
    for video in gallery.videos_in(root, long=False):
        info = gallery.load_publish_info(video)
        if info["discarded"] or used.get(video.stem, 0) >= limit:
            continue
        row = _round_info(channel, video)
        if row:
            row["reused"] = used.get(video.stem, 0)
            row["rank"] = (row["reused"], 0 if gallery.is_out(info) else 1 if gallery.is_queued(info) else 2,
                           video.stat().st_mtime)
            rows.append(row)
    return sorted(rows, key=lambda r: r["rank"])


CATEGORY_PREFIX = "category:"


def availability(channel) -> dict:
    """{difficulty label: rounds ready, "rising": categories ready,
    "category:<name>": difficulty levels ready in that category}."""
    rows = available_rounds(channel)
    counts = {}
    for label in quiz.labels(channel):
        counts[label] = len({r["category"].lower() for r in rows
                             if r["difficulty"].lower() == label.lower()})
    counts[RISING] = len({r["category"].lower() for r in rows})
    for category in sorted({r["category"] for r in rows}):
        counts[CATEGORY_PREFIX + category] = len({r["level"] for r in rows if r["category"] == category})
    return counts


def _questions(row: dict, channel) -> list:
    """A round's questions and answers, for the clash check."""
    if "questions" not in row:
        sidecar = quiz.round_sidecar(row["video"])
        if sidecar.exists():
            row["questions"] = json.loads(sidecar.read_text(encoding="utf-8")).get("questions") or []
        else:
            found = next((r for r in quiz.bank(channel.key) if r.get("video") == row["stem"]), {})
            row["questions"] = found.get("questions") or []
    return row["questions"]


def clashes(a: list, b: list) -> bool:
    """Whether two rounds would sit badly in one video: the same answer
    twice ("What is the capital of France?" and "What is the most
    populous city in France?"), one round's answer given away in the
    other's question, or much the same question."""
    answers_a = {quiz._norm_answer(q.get("answer", "")) for q in a} - {""}
    answers_b = {quiz._norm_answer(q.get("answer", "")) for q in b} - {""}
    if answers_a & answers_b:
        return True
    for first, second in ((a, b), (b, a)):
        text = " ".join(q.get("question", "") for q in second)
        if any(len(quiz._norm_answer(q.get("answer", ""))) > 3 and quiz._mentions(text, q.get("answer", ""))
               for q in first):
            return True
    for q in a:
        words = quiz._keywords(q.get("question", ""))
        for r in b:
            other = quiz._keywords(r.get("question", ""))
            if len(words | other) >= 4 and len(words & other) / len(words | other) >= 0.6:
                return True
    return False


def choose_rounds(channel, difficulty: str, count: int) -> list:
    """`count` rounds that don't clash: all at one difficulty in different
    categories; "rising", as spread across the levels as possible in
    different categories; or "category:<name>", one category from its
    easiest level up. Easiest first."""
    rows = available_rounds(channel)
    picked = []

    def fits(r) -> bool:
        return all(not clashes(_questions(r, channel), _questions(p, channel)) for p in picked)

    if difficulty.startswith(CATEGORY_PREFIX):
        category = difficulty[len(CATEGORY_PREFIX):].lower()
        mine = sorted((r for r in rows if r["category"].lower() == category),
                      key=lambda r: (r["level"], r["rank"]))
        levels_done = set()
        for pass_ in (0, 1):            # one per level first, then more of the same levels
            for r in mine:
                if len(picked) >= count:
                    break
                if r in picked or (pass_ == 0 and r["level"] in levels_done) or not fits(r):
                    continue
                picked.append(r)
                levels_done.add(r["level"])
        return sorted(picked, key=lambda r: r["level"])

    seen = set()
    if difficulty != RISING:
        for r in rows:
            if (r["difficulty"].lower() == difficulty.lower() and r["category"].lower() not in seen
                    and fits(r)):
                picked.append(r)
                seen.add(r["category"].lower())
            if len(picked) >= count:
                break
        return picked
    by_level = {}
    for r in rows:
        by_level.setdefault(r["level"], []).append(r)
    levels = sorted(by_level)
    while len(picked) < count and any(by_level.values()):
        for level in levels:
            for r in list(by_level[level]):
                by_level[level].remove(r)
                if r["category"].lower() not in seen and fits(r):
                    picked.append(r)
                    seen.add(r["category"].lower())
                    break
            if len(picked) >= count:
                break
    return sorted(picked[:count], key=lambda r: r["level"])


# --- a round's audio -------------------------------------------------------------

def load_round(channel, row: dict) -> dict:
    """The round's sidecar, rebuilt (and saved) for a short made before
    sidecars existed."""
    sidecar = quiz.round_sidecar(row["video"])
    if sidecar.exists():
        return json.loads(sidecar.read_text(encoding="utf-8"))
    data = rebuild_round(channel, row)
    sidecar.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return data


def _silences(samples: np.ndarray, fps: int, shortest: float) -> list:
    """[(start, end)] seconds of digital silence at least `shortest` long:
    the pauses the voiceover stage inserted, which are exact zeros."""
    mono = np.abs(samples).max(axis=1) if samples.ndim == 2 else np.abs(samples)
    step = int(fps * 0.01)
    quiet = np.array([mono[i:i + step].max() < 2e-3 for i in range(0, len(mono), step)])
    runs, start = [], None
    for i, q in enumerate(quiet):
        if q and start is None:
            start = i
        elif not q and start is not None:
            if (i - start) * 0.01 >= shortest:
                runs.append((start * 0.01, i * 0.01))
            start = None
    return runs


def _spoken_answers(video: Path) -> list:
    """The host's answer lines from a short's meta file: segments 2, 4, ...
    (after the intro, question and answer alternate)."""
    meta = video.with_name(f"{video.stem}_meta.txt")
    if not meta.exists():
        return []
    text = meta.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    segments = [block.strip().split("\n")[0].strip()
                for block in re.findall(r"\[segment \d+\]\n(.*?)(?=\n\[segment|\Z)", text, re.S)]
    return segments[2::2]          # intro, then question and answer in turn; the outro is odd


def rebuild_round(channel, row: dict) -> dict:
    """Question and answer timings for a short made before sidecars: the
    ten clocks are the only silences of their length in its voice track,
    each answer ends at the pause after it, and the first question's start
    is found by Whisper. Local and free."""
    from pipeline import tts
    from pipeline.audio import decode_audio_file

    video = row["video"]
    audio = video.with_name(f"{video.stem}_audio.mp3")
    bank_round = next((r for r in quiz.bank(channel.key) if r.get("video") == video.stem), None)
    if bank_round is None:
        raise LongformError(f"no questions for {video.stem}", user_message=(
            f"The questions for {video.stem} couldn't be found, so it can't join a long quiz."))
    questions = bank_round["questions"]
    fps = tts.SAMPLE_RATE
    samples = decode_audio_file(str(audio), fps=fps)
    clock = channel.quiz.countdown_seconds
    clocks = _silences(samples, fps, clock * 0.8)
    pauses = _silences(samples, fps, 0.9)
    if len(clocks) != len(questions):
        raise LongformError(f"{video.stem}: {len(clocks)} clocks for {len(questions)} questions",
                            user_message=f"{video.stem}'s timings couldn't be recovered.")
    model = tts._get_whisper()
    first_start = None
    if model is not None:
        parts, _ = model.transcribe(str(audio), word_timestamps=True, language="en")
        words = [w for p in parts for w in p.words if w.start < clocks[0][0]]
        wanted = [w for w in re.findall(r"[a-z0-9']+", questions[0]["question"].lower())][:3]
        heard = [re.sub(r"[^a-z0-9']", "", w.word.lower()) for w in words]
        for i in range(len(heard) - len(wanted) + 1):
            if heard[i:i + len(wanted)] == wanted:
                first_start = max(0.0, words[i].start - 0.08)
                break
    if first_start is None:
        raise LongformError(f"{video.stem}: first question not found", user_message=(
            f"{video.stem}'s first question couldn't be found in its audio."))
    spoken = _spoken_answers(video)
    rows, ask_start = [], first_start
    total = len(samples) / fps
    for i, (q, (clock_start, clock_end)) in enumerate(zip(questions, clocks)):
        # The answer ends at the pause inserted after it, which is the
        # longest silence before the next question's clock: the host's own
        # pauses ("A nova. ... Not to be confused") can pass a second too.
        until = clocks[i + 1][0] if i + 1 < len(clocks) else total
        between = [p for p in pauses if clock_end + 0.3 <= p[0] < until]
        after = max(between, key=lambda p: p[1] - p[0]) if between else (total, 0)
        said = spoken[i] if i < len(spoken) else ""
        # The earliest shorts' bank kept questions only: the answer is what
        # the host said first ("Hubble. The Hubble...", "Mars, it's the...").
        answer = q.get("answer") or re.split(r"[.,!?;:]\s", said, maxsplit=1)[0].rstrip(".!? ")
        rows.append({"question": q["question"], "answer": answer[:60], "spoken_answer": said,
                     "ask_audio": [round(ask_start, 3), round(clock_start, 3)],
                     "answer_audio": [round(clock_end, 3), round(after[0], 3)]})
        ask_start = after[1] if after[1] else after[0]
    return {"version": 1, "category": row["category"], "difficulty": row["difficulty"],
            "level": row["level"], "audio": audio.name, "unverified": [], "questions": rows,
            "rebuilt": True}


# --- the host's joining lines -------------------------------------------------------

LINKS_SYSTEM = """
You are the host of a pub-quiz channel, joining several rounds into one
long widescreen video. The rounds' questions and answers are already
recorded; you write only the lines between them, in the channel's voice
(its brief follows). Spoken aloud, so write the way a person talks. Vary
the phrasing: no two lines should start or end the same way. Never explain
the format or how it works (how or when answers are given, what is read
again, how long they have): just host it. No dashes; commas and full
stops only.

- welcome (under 45 words): welcome them to the quiz, say how many rounds
  and questions and the difficulty, invite them to keep score, and lead
  straight into round one by naming its category and ending on "question
  one" (the first question follows immediately).
- round_intros: one for each round after the first (under 25 words): a
  touch of banter, the round number and its category, ending on "question
  one".
- finish_lines (answers at the end only): one per round (under 15 words):
  that's the round's questions done, a nudge to get their last answers
  down. Different every round.
- answers_intros (answers at the end only): one per round (under 20
  words): pens down, here come this round's answers, ending on "question
  one".
- signoff (under 40 words): the total out of the number of questions, ask
  for their score and a category for next time in the comments, and to
  subscribe for more. Warm, not salesy.
- title_options: three titles under 70 characters for a long quiz video:
  the question count, the difficulty, the categories or the variety.
  Inviting, never false.
- description: two or three plain sentences about the quiz. No hashtags.
- thumbnail_line: two to five words for the thumbnail, a friendly
  challenge. No false claims ("only 1% get this" is out).
""".strip()


def _links_schema() -> dict:
    strings = {"type": "array", "items": {"type": "string"}}
    return {"type": "object", "properties": {
        "welcome": {"type": "string"}, "round_intros": strings, "finish_lines": strings,
        "answers_intros": strings,
        "signoff": {"type": "string"}, "title_options": strings, "description": {"type": "string"},
        "thumbnail_line": {"type": "string"}},
        "required": ["welcome", "round_intros", "finish_lines", "answers_intros", "signoff",
                     "title_options", "description", "thumbnail_line"],
        "additionalProperties": False}


def difficulty_words(rounds: list, difficulty: str) -> str:
    if difficulty == RISING or difficulty.startswith(CATEGORY_PREFIX):
        return f"getting harder each round, from {rounds[0]['difficulty']} to {rounds[-1]['difficulty']}"
    return rounds[0]["difficulty"]


def write_links(channel, rounds: list, variant: str, difficulty: str) -> dict:
    listed = "\n".join(f"Round {i + 1}: {r['category']} ({r['difficulty']})" for i, r in enumerate(rounds))
    if difficulty.startswith(CATEGORY_PREFIX):
        listed += ("\n\nEvery round is the same category, one difficulty level harder each "
                   "time: name the level in each round's intro rather than the category.")
    per = channel.quiz.questions
    fmt = ("answers after each question" if variant == "after_each"
           else "answers at the end of each round")
    user = (f"{len(rounds)} rounds of {per} questions, {len(rounds) * per} in total. Difficulty: "
            f"{difficulty_words(rounds, difficulty)}. Format: {fmt}.\n\n{listed}\n\n"
            f"Write {len(rounds) - 1} round_intros"
            + (f", {len(rounds)} finish_lines and {len(rounds)} answers_intros." if variant == "at_end"
               else "; finish_lines and answers_intros empty."))
    data = call_json([SystemBlock(LINKS_SYSTEM, cacheable=True),
                      SystemBlock(f"The channel's brief for its host:\n\n{channel.style_prompt}")],
                     user, _links_schema(), operation="longform_links",
                     max_tokens=LINKS_MAX_TOKENS, effort="low")
    intros = [s.strip() for s in data.get("round_intros") or [] if s.strip()]
    answers = [s.strip() for s in data.get("answers_intros") or [] if s.strip()]
    finishes = [s.strip() for s in data.get("finish_lines") or [] if s.strip()]
    if len(intros) < len(rounds) - 1 or (variant == "at_end" and (
            len(answers) < len(rounds) or len(finishes) < len(rounds))):
        raise LongformError("links came back short", user_message=(
            "The joining lines came back incomplete. Try again."))
    return {"welcome": data["welcome"].strip(), "round_intros": intros[:len(rounds) - 1],
            "finish_lines": finishes[:len(rounds)] if variant == "at_end" else [],
            "answers_intros": answers[:len(rounds)] if variant == "at_end" else [],
            "signoff": data["signoff"].strip(),
            "title_options": [t.strip() for t in data.get("title_options") or [] if t.strip()],
            "description": (data.get("description") or "").strip(),
            "thumbnail_line": (data.get("thumbnail_line") or "").strip()}


def link_lines(links: dict) -> list:
    """Every joining line, in the order they're voiced (and indexed)."""
    return [links["welcome"], *links["round_intros"], *links.get("finish_lines", []),
            *links["answers_intros"], links["signoff"]]


def voice_links(channel, links: dict, work: Path) -> list:
    """Each joining line as its own stretch of audio."""
    from core import voice_quota
    from pipeline import tts
    from pipeline.plan import Segment

    lines = link_lines(links)
    segments = [Segment(text=line, pause_after=0.0) for line in lines]
    voice_quota.require_room(tts.narration_characters(segments, None, channel.pacing))
    voiceover = tts.generate_voiceover(segments, None, channel.voice, str(work / "links.mp3"),
                                       channel.pacing, speed=channel.speed,
                                       say_as=channel.pronunciations)
    fps = voiceover.fps
    return [voiceover.samples[int(s.start * fps):int(s.end * fps)] for s in segments]


# --- the timeline -------------------------------------------------------------------

class _Track:
    """The soundtrack as it's laid down, and when everything in it happens."""

    def __init__(self, fps: int):
        self.fps, self.parts, self.t = fps, [], 0.0

    def add(self, samples: np.ndarray) -> tuple:
        from pipeline.audio import apply_fade, match_channels
        start = self.t
        piece = apply_fade(match_channels(samples, 2), self.fps, FADE, FADE).astype(np.float32)
        self.parts.append(piece)
        self.t += len(piece) / self.fps
        return (round(start, 3), round(self.t, 3))

    def gap(self, seconds: float) -> tuple:
        start = self.t
        n = int(seconds * self.fps)
        self.parts.append(np.zeros((n, 2), dtype=np.float32))
        self.t += n / self.fps
        return (round(start, 3), round(self.t, 3))

    def samples(self) -> np.ndarray:
        return np.concatenate(self.parts, axis=0)


def build_timeline(channel, rounds: list, sidecars: list, audios: list, links: list,
                   variant: str, fps: int) -> tuple:
    """(track, timeline): the soundtrack laid down in order, and when every
    question is asked, counted down, re-asked and answered."""
    clock = float(channel.quiz.longform_clock_seconds)
    finish = float(channel.quiz.longform_finish_seconds)
    pause = float(channel.quiz.answer_pause)
    track = _Track(fps)
    n = len(rounds)
    welcome, intros = links[0], links[1:n]
    finish_lines = links[n:2 * n] if variant == "at_end" else []
    answers_intros = links[2 * n:3 * n] if variant == "at_end" else []
    signoff = links[-1]

    def cut(audio, span):
        return audio[int(span[0] * fps):int(span[1] * fps)]

    timeline = {"welcome": track.add(welcome), "rounds": []}
    track.gap(LINK_PAUSE)
    for r, (row, side, audio) in enumerate(zip(rounds, sidecars, audios)):
        info = {"number": r + 1, "category": row["category"], "difficulty": row["difficulty"],
                "questions": [], "intro": None, "answers_intro": None, "finish": None}
        if r:
            track.gap(ROUND_GAP)
            info["intro"] = track.add(intros[r - 1])
            track.gap(LINK_PAUSE)
        info["start"] = info["intro"][0] if info["intro"] else timeline["welcome"][1]
        for q in side["questions"]:
            item = {"question": q["question"], "answer": q["answer"]}
            item["ask"] = track.add(cut(audio, q["ask_audio"]))
            track.gap(CLOCK_LEAD)
            item["countdown"] = track.gap(clock)
            if variant == "after_each":
                item["reveal"] = track.add(cut(audio, q["answer_audio"]))
                track.gap(pause)
            else:
                track.gap(CLOCK_TAIL)
            info["questions"].append(item)
        if variant == "at_end":
            # Time to finish off, then pens down.
            finish_line = track.add(finish_lines[r])
            track.gap(LINK_PAUSE)
            info["finish"] = {"line": finish_line, "clock": track.gap(finish),
                              "text": FINISH_TEXT[r % len(FINISH_TEXT)]}
            track.gap(CLOCK_TAIL)
            info["answers_intro"] = track.add(answers_intros[r])
            track.gap(LINK_PAUSE)
            for q, item in zip(side["questions"], info["questions"]):
                item["reask"] = track.add(cut(audio, q["ask_audio"]))
                track.gap(REASK_GAP)
                item["reveal"] = track.add(cut(audio, q["answer_audio"]))
                track.gap(pause)
        timeline["rounds"].append(info)
    track.gap(ROUND_GAP)
    timeline["signoff"] = track.add(signoff)
    track.gap(1.5)
    for i, info in enumerate(timeline["rounds"]):
        info["end"] = (timeline["rounds"][i + 1]["start"] if i + 1 < n else timeline["signoff"][0])
    timeline["end"] = round(track.t, 3)
    timeline["variant"] = variant
    return track, timeline


def _ticks(start: float, end: float) -> list:
    """A tick each of a clock's last few seconds: ten seconds of ticking,
    sixty times a video, would wear."""
    seconds = max(1, math.ceil(end - start - 0.05))
    step = (end - start) / seconds
    return [(start + k * step, "tock", 0.8) for k in range(max(0, seconds - TICKS), seconds)]


def cues(timeline: dict) -> list:
    """Each clock's last seconds ticking, and a chime as each answer lands."""
    out = []
    for info in timeline["rounds"]:
        for item in info["questions"]:
            out += _ticks(*item["countdown"])
            out.append((item["reveal"][0], "chime", 0.55))
        if info.get("finish"):
            out += _ticks(*info["finish"]["clock"])
    return sorted(out)


def chapters(timeline: dict) -> list:
    """[(seconds, label)] for YouTube's chapters."""
    out = [(0.0, "Welcome")]
    for info in timeline["rounds"]:
        out.append((info["start"], f"Round {info['number']}: {info['category']}"))
        if info.get("answers_intro"):
            out.append((info["answers_intro"][0], f"Round {info['number']} answers"))
    out.append((timeline["signoff"][0], "Scores"))
    return out


def _stamp(seconds: float) -> str:
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{rest // 60}:{rest % 60:02d}"


# --- the board --------------------------------------------------------------------

LIST_X, LIST_W, TOP, BOTTOM = 70, 1000, 170, 1030
PANEL_X, PANEL_W = 1130, 720
TIMER_R = 92
RING = 2 * math.pi * TIMER_R

BOARD_CSS = f"""
html, body {{ width: {W}px; height: {H}px; }}
.board {{ position: absolute; inset: 0; }}
.head {{ position: absolute; left: {LIST_X}px; right: 70px; top: 52px; height: 80px; display: flex;
  align-items: center; gap: 24px; }}
.head .rnd {{ font-family: var(--display); font-weight: var(--dw); font-size: 40px; letter-spacing: .1em;
  text-transform: uppercase; color: var(--soft); white-space: nowrap; }}
.head .cat {{ font-family: var(--display); font-weight: var(--dw); font-size: 52px; color: var(--ink);
  white-space: nowrap; overflow: hidden; min-width: 0; flex: 1; }}
.head .lvl {{ padding: 8px 26px; font-size: 32px; flex: none; white-space: nowrap; }}
.rows {{ position: absolute; left: {LIST_X}px; width: {LIST_W}px; top: {TOP}px; height: {BOTTOM - TOP}px;
  display: flex; flex-direction: column; justify-content: space-between; }}
.row {{ position: relative; display: flex; align-items: center; gap: 20px; }}
.row .n {{ width: 64px; flex: none; text-align: right; font-family: var(--display); font-weight: var(--dw);
  font-size: 40px; color: var(--a1); }}
.row .cell {{ position: relative; flex: 1; height: 100%; }}
.row .q, .row .a {{ position: absolute; inset: 0; display: flex; align-items: center; overflow: hidden; }}
.row .q {{ font-size: 31px; line-height: 1.15; color: var(--ink); }}
.row .a {{ font-family: var(--display); font-weight: var(--dw); font-size: 38px; color: var(--a2); }}
.row .line {{ position: absolute; left: 84px; right: 0; bottom: 4px; height: 3px; background: var(--soft);
  opacity: .3; border-radius: 2px; }}
.row .now {{ position: absolute; left: -14px; right: -14px; top: 0; bottom: 0; border-radius: 16px;
  border: 4px solid var(--a2); }}
.panel {{ position: absolute; left: {PANEL_X}px; width: {PANEL_W}px; top: {TOP}px; height: {BOTTOM - TOP}px; }}
.panel > .view {{ position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
  justify-content: center; text-align: center; padding: 40px 50px; gap: 22px; }}
.panel > .view.with-timer {{ bottom: {2 * TIMER_R + 90}px; }}
.view.with-timer .big {{ max-height: 400px; }}
.label {{ font-family: var(--display); font-weight: var(--dw); font-size: 30px; letter-spacing: .12em;
  text-transform: uppercase; color: var(--soft); }}
.big {{ font-family: var(--display); font-weight: var(--dw); font-size: 58px; line-height: 1.15;
  color: var(--on-card); width: 100%; max-height: 420px; overflow: hidden; }}
.answer {{ font-family: var(--display); font-weight: var(--dw); font-size: 76px; line-height: 1.1;
  color: var(--a2); width: 100%; max-height: 360px; overflow: hidden; }}
.timer {{ position: absolute; left: 50%; bottom: 40px; width: {2 * TIMER_R + 36}px; height: {2 * TIMER_R + 36}px;
  margin-left: -{TIMER_R + 18}px; }}
.timer svg {{ position: absolute; inset: 0; }}
.timer .track {{ fill: none; stroke: var(--soft); stroke-opacity: .25; stroke-width: 16px; }}
.timer .fill {{ fill: none; stroke: var(--a2); stroke-width: 16px; stroke-linecap: round;
  stroke-dasharray: {RING:.1f}px {RING:.1f}px; stroke-dashoffset: calc(var(--p, 0) * {RING:.1f}px);
  transform: rotate(-90deg); transform-origin: 50% 50%; }}
.timer .digit {{ position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  font-family: var(--display); font-weight: var(--dw); font-size: 92px; color: var(--ink); }}
.cover {{ position: absolute; inset: 60px 70px; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 30px; text-align: center; }}
.cover .title {{ font-size: 124px; line-height: 1.05; width: 100%; }}
.cover .sub {{ font-size: 48px; color: var(--soft); }}
.cover .chips {{ display: flex; flex-wrap: wrap; gap: 18px; justify-content: center; max-width: 1500px; }}
.cover .chips .chip {{ padding: 12px 30px; font-size: 36px; }}
.question-box {{ position: relative; flex: 1; width: 100%; display: flex; align-items: center; }}
"""


def _in(t, anim="fade", dur=0.35, out=None) -> str:
    attrs = f"data-in='{max(0.0, t):.3f}' data-anim='{anim}' data-dur='{dur}'"
    return attrs + (f" data-out='{out:.3f}'" if out is not None else "")


def _timer(start: float, end: float) -> str:
    span = max(0.5, end - start)
    seconds = max(1, math.ceil(span - 0.05))
    size = 2 * TIMER_R + 36
    digits = "".join(
        f"<div class='digit' {_in(start + k * span / seconds, 'pop', 0.25, start + (k + 1) * span / seconds - 0.1)}>"
        f"{seconds - k}</div>" for k in range(seconds))
    return (f"<div class='timer' {_in(start - 0.2, 'pop', 0.3, end)}>"
            f"<svg width='{size}' height='{size}'><circle class='track' cx='{size / 2}' cy='{size / 2}' r='{TIMER_R}'/>"
            f"<circle class='fill' cx='{size / 2}' cy='{size / 2}' r='{TIMER_R}' data-in='{start:.3f}' "
            f"data-anim='none' data-dur='{span:.3f}' data-steps='{max(10, round(span * 10))}'/>"
            f"</svg>{digits}</div>")


def board_html(timeline: dict, style: dict, title: str, subtitle: str) -> str:
    from pipeline.templates import page, theme

    esc = html.escape
    variant = timeline["variant"]
    rounds = timeline["rounds"]
    parts = []
    # The cover while the welcome is read, and the scores at the end.
    chips = "".join(f"<span class='chip filled a{(i % 5) + 1}'>{esc(r['category'])}</span>"
                    for i, r in enumerate(rounds))
    parts.append(f"<div class='cover' {_in(0, 'fade', 0.4, timeline['welcome'][1] + 0.2)}>"
                 f"<div class='title hero'>{esc(title)}</div>"
                 f"<div class='sub'>{esc(subtitle)}</div><div class='chips'>{chips}</div></div>")
    total = sum(len(r["questions"]) for r in rounds)
    parts.append(f"<div class='cover' {_in(timeline['signoff'][0], 'pop', 0.5)}>"
                 f"<div class='title hero'>How many did you get?</div>"
                 f"<div class='sub'>Out of {total}</div></div>")
    for info in rounds:
        start, end = info["start"], info["end"]
        n = len(info["questions"])
        parts.append(
            f"<div class='head' {_in(start, 'fade', 0.4, end)}><span class='rnd'>Round {info['number']} "
            f"of {len(rounds)}</span><span class='cat' data-fit='30'>{esc(info['category'])}</span>"
            f"<span class='chip filled a2 lvl'>{esc(info['difficulty'])}</span></div>")
        rows, views = [], []
        row_h = (BOTTOM - TOP) / n - 6
        if info["intro"]:
            views.append(f"<div class='view' {_in(info['intro'][0], 'pop', 0.4, info['intro'][1] + 0.1)}>"
                         f"<div class='label'>Round {info['number']}</div>"
                         f"<div class='big' data-fit='34'>{esc(info['category'])}</div></div>")
        if info.get("finish"):
            f0 = info["finish"]["line"][0]
            c0, c1 = info["finish"]["clock"]
            views.append(f"<div class='view with-timer' {_in(f0, 'pop', 0.4, c1 + 0.3)}>"
                         f"<div class='label'>Round {info['number']}</div>"
                         f"<div class='big'>{esc(info['finish']['text'])}</div></div>")
            views.append(_timer(c0, c1))
        if info.get("answers_intro"):
            a0, a1 = info["answers_intro"]
            views.append(f"<div class='view' {_in(a0, 'pop', 0.4, a1 + 0.1)}>"
                         f"<div class='label'>Round {info['number']}</div>"
                         f"<div class='big'>Answers</div></div>")
        for i, item in enumerate(info["questions"]):
            ask0 = item["ask"][0]
            reveal0, reveal1 = item["reveal"]
            cd0, cd1 = item["countdown"]
            highlights = [f"<div class='now' {_in(ask0, 'fade', 0.25, cd1 + 0.3 if variant == 'at_end' else reveal1)}></div>"]
            if variant == "at_end":
                highlights.append(f"<div class='now' {_in(item['reask'][0], 'fade', 0.25, reveal1 + 0.4)}></div>")
            rows.append(
                f"<div class='row' style='height:{row_h:.0f}px' {_in(start + 0.1 + 0.05 * i, 'slide-left', 0.4, end - 0.2)}>"
                + "".join(highlights) +
                f"<div class='n'>{i + 1}.</div><div class='cell'>"
                f"<div class='q' data-fit='18' {_in(ask0, 'wipe', 0.6, reveal0)}>{esc(item['question'])}</div>"
                f"<div class='a' data-fit='22' {_in(reveal0, 'fade', 0.5)}>{esc(item['answer'])}</div>"
                f"</div><div class='line'></div></div>")
            # The panel: the question and its clock; then, as it's given, the answer.
            nxt = info["questions"][i + 1]["ask"][0] if i + 1 < n else None
            if variant == "after_each":
                q_out, a_out = reveal0, (nxt - 0.3 if nxt else end)
                views.append(f"<div class='view with-timer' {_in(ask0, 'rise', 0.45, q_out)}>"
                             f"<div class='label'>Question {i + 1}</div>"
                             f"<div class='big' data-fit='30'>{esc(item['question'])}</div></div>")
            else:
                # Gone before the next question arrives (the clock's tail
                # is a second), so the two never overlap.
                views.append(f"<div class='view with-timer' {_in(ask0, 'rise', 0.45, cd1 + 0.3)}>"
                             f"<div class='label'>Question {i + 1}</div>"
                             f"<div class='big' data-fit='30'>{esc(item['question'])}</div></div>")
                re0 = item["reask"][0]
                views.append(f"<div class='view' {_in(re0, 'fade', 0.4, reveal0)}>"
                             f"<div class='label'>Question {i + 1}</div>"
                             f"<div class='big' data-fit='30'>{esc(item['question'])}</div></div>")
                later = [q["reask"][0] for q in info["questions"][i + 1:]]
                a_out = later[0] - 0.3 if later else end
            views.append(f"<div class='view' {_in(reveal0, 'fade', 0.5, a_out)}>"
                         f"<div class='label'>Question {i + 1} · Answer</div>"
                         f"<div class='answer' data-fit='36'>{esc(item['answer'])}</div></div>")
            views.append(_timer(cd0, cd1))
        parts.append(f"<div class='rows'>{''.join(rows)}</div>")
        parts.append(f"<div class='card panel' {_in(start, 'fade', 0.4, end)}>{''.join(views)}</div>")
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        f"{theme.css(style)}{BOARD_CSS}"
        f".bg-grain {{ background-image: url({page.GRAIN}); }}"
        "[data-anim='none'] { opacity: 1; transform: none; }"
        ".bg-pattern { transform: none; }"
        "</style></head><body>"
        "<div class='bg'><div class='bg-pattern'></div><div class='bg-grain'></div>"
        "<div class='bg-vignette'></div></div>"
        f"<div class='board'>{''.join(parts)}</div>"
        f"<script>window.TEMPLATE_DURATION = {json.dumps(timeline['end'])};"
        "window.STATIC_BACKGROUND = true;</script>"
        f"<script>{page.RUNTIME.read_text(encoding='utf-8')}</script>"
        "</body></html>")


def thumbnail_html(style: dict, headline: str, subtitle: str, line: str, categories: list,
                   badge: str) -> str:
    from pipeline.templates import page, theme

    esc = html.escape
    chips = "".join(f"<span class='chip filled a{(i % 5) + 1}'>{esc(c)}</span>"
                    for i, c in enumerate(categories))
    css = f"""
    html, body {{ width: {THUMB[0]}px; height: {THUMB[1]}px; }}
    .t {{ position: absolute; inset: 40px 56px; display: flex; flex-direction: column; justify-content: center; gap: 22px; }}
    .t {{ right: 380px; }}
    .t .head {{ font-family: var(--display); font-weight: var(--dw); font-size: 150px; line-height: .95; color: var(--ink); }}
    .t .sub {{ font-family: var(--display); font-weight: var(--dw); font-size: 60px; line-height: 1.05; color: var(--a2); }}
    .mark {{ position: absolute; right: 60px; bottom: 30px; font-family: var(--display); font-weight: var(--dw);
      font-size: 520px; line-height: 1; color: var(--a1); opacity: .9; }}
    .t .line {{ font-size: 40px; color: var(--soft); }}
    .t .chips {{ display: flex; flex-wrap: wrap; gap: 12px; max-width: 1100px; }}
    .t .chips .chip {{ padding: 8px 22px; font-size: 28px; }}
    .badge {{ position: absolute; right: 48px; top: 40px; padding: 14px 30px; font-size: 32px; }}
    """
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        f"{theme.css(style)}{css}.bg-grain {{ background-image: url({page.GRAIN}); }}"
        "</style></head><body><div class='bg'><div class='bg-pattern'></div><div class='bg-grain'></div>"
        "<div class='bg-vignette'></div></div>"
        f"<div class='mark'>?</div><span class='chip filled a1 badge'>{esc(badge)}</span>"
        f"<div class='t'><div class='head' data-fit='70'>{esc(headline)}</div>"
        f"<div class='sub'>{esc(subtitle)}</div>"
        + (f"<div class='line'>{esc(line)}</div>" if line else "") +
        f"<div class='chips'>{chips}</div></div>"
        "<script>window.TEMPLATE_DURATION = 1;</script>"
        f"<script>{page.RUNTIME.read_text(encoding='utf-8')}</script></body></html>")


# --- making one --------------------------------------------------------------------

def plan_request(channel, seed: dict) -> dict:
    """The request with its choices resolved: difficulty, variant, rounds."""
    variant = seed.get("variant") or channel.quiz.longform_variant
    if variant not in VARIANTS:
        # "alternate": whichever this channel made less recently.
        made = sorted(((v.stat().st_mtime, json.loads(quiz.round_sidecar(v).read_text(encoding="utf-8")).get("variant"))
                       for v in gallery.videos_in(_out_root(channel), long=True)
                       if quiz.round_sidecar(v).exists()), reverse=True)
        variant = "at_end" if made and made[0][1] == "after_each" else "after_each"
    count = max(2, min(12, int(seed.get("rounds") or channel.quiz.longform_rounds)))
    difficulty = seed.get("difficulty") or ""
    if not difficulty or difficulty == "best":
        counts = availability(channel)
        ready = [label for label in quiz.labels(channel) if counts.get(label, 0) >= count]
        difficulty = ready[0] if ready else RISING
    return {"variant": variant, "rounds": count, "difficulty": difficulty}


def make(channel, seed: dict, out_dir: Path = None):
    """Make a long quiz. `seed`: {"type": "longform", "difficulty": a label
    or "rising", "variant", "rounds"}. Returns an object with video_path.
    `out_dir` is for trying one out without it reaching the review queue."""
    from core import costs
    from pipeline import sound, tts
    from pipeline.audio import decode_audio_file
    from pipeline.scenes import art, render

    started = time.time()
    request = plan_request(channel, seed)
    variant, count, difficulty = request["variant"], request["rounds"], request["difficulty"]

    job_context.report_stage(1)
    saved = job_context.load_json_checkpoint("longform") or {}
    if saved.get("rounds"):
        wanted = set(saved["rounds"])
        rounds = [r for r in available_rounds(channel) if r["stem"] in wanted]
        rounds = sorted(rounds, key=lambda r: saved["rounds"].index(r["stem"]))
    else:
        rounds = choose_rounds(channel, difficulty, count)
    if len(rounds) < count:
        raise LongformError(f"{len(rounds)} of {count} rounds", user_message=(
            f"A long quiz of {count} rounds at {difficulty} needs {count} finished quiz shorts "
            f"in different categories; {len(rounds)} are ready. Make more shorts at that "
            f"difficulty, choose fewer rounds, or choose \"rising\"."))
    log.info(f"[1/5] Long quiz: {count} rounds, {variant.replace('_', ' ')}, "
             f"{difficulty}: {', '.join(r['category'] for r in rounds)}")
    sidecars = [load_round(channel, r) for r in rounds]
    links = saved.get("links") or write_links(channel, rounds, variant, difficulty)

    out_dir = Path(out_dir or _out_root(channel) / gallery.LONGFORM_DIR / date.today().isoformat())
    out_dir.mkdir(parents=True, exist_ok=True)
    single = difficulty.startswith(CATEGORY_PREFIX)
    kind = (rounds[0]["category"] if single else "rising" if difficulty == RISING else difficulty)
    stem = saved.get("stem") or unique_stem(out_dir, slugify(
        f"{kind} quiz {count * channel.quiz.questions} "
        f"questions {'answers at end' if variant == 'at_end' else ''}", fallback="long_quiz"))
    work = out_dir / f"{stem}_scenes"
    work.mkdir(parents=True, exist_ok=True)
    try:
        job_context.save_json_checkpoint("longform", {"rounds": [r["stem"] for r in rounds],
                                                      "links": links, "stem": stem})
    except Exception:  # noqa: BLE001 - checkpointing is best-effort
        pass

    job_context.report_stage(2)
    log.info("[2/5] Voicing the joining lines...")
    cached = job_context.checkpoint_artifact_path("longform_links.npy")
    if cached is not None and cached.exists() and saved.get("links"):
        pieces = list(np.load(cached, allow_pickle=True))
    else:
        pieces = voice_links(channel, links, work)
        try:
            if cached is not None:
                np.save(cached, np.array(pieces, dtype=object), allow_pickle=True)
        except Exception:  # noqa: BLE001 - checkpointing is best-effort
            pass

    fps = tts.SAMPLE_RATE
    audios = [decode_audio_file(str(r["video"].with_name(s["audio"])), fps=fps)
              for r, s in zip(rounds, sidecars)]
    track, timeline = build_timeline(channel, rounds, sidecars, audios, pieces, variant, fps)
    log.info(f"      {timeline['end'] / 60:.1f} minutes")

    job_context.report_stage(3)
    style = art.resolve(channel.scenes.art)
    per = channel.quiz.questions
    title_line = f"{count * per} Questions"
    level_words = difficulty_words(rounds, difficulty)
    subtitle = f"{count} rounds · {level_words[0].upper() + level_words[1:]}"
    cover = f"{rounds[0]['category']} Quiz: {title_line}" if single else f"The Pub Quiz: {title_line}"
    log.info(f"[3/5] Filming the board ({timeline['end'] / 60:.1f} minutes)...")
    board = render.render_page(board_html(timeline, style, cover, subtitle),
                               timeline["end"], work / "board.mp4", fps=FPS, size=(W, H))

    job_context.report_stage(4)
    log.info("[4/5] Mixing the sound and assembling...")
    voice = track.samples()
    audio = voice.copy()
    if channel.sound.effects:
        audio = sound.add_effects(audio, fps, cues(timeline), channel.sound.effects_level)
    credits = []
    if channel.sound.music:
        audio += music_bed(channel, voice, fps, stem, credits)
    peak = float(np.abs(audio).max() or 1.0)
    if peak > 0.98:
        audio *= 0.98 / peak
    video_path = out_dir / f"{stem}.mp4"
    _mux(board, audio, fps, video_path, work)

    job_context.report_stage(5)
    log.info("[5/5] Thumbnail, title, chapters...")
    badge = "Answers at the end" if variant == "at_end" else "Answers as you go"
    thumb = video_path.with_name(f"{video_path.stem}_thumb.jpg")
    rising_words = f"{rounds[0]['difficulty']} to {rounds[-1]['difficulty']}"
    if single:
        sub, chips = f"{rounds[0]['category']}: {rising_words}", [r["difficulty"] for r in rounds]
    else:
        sub = f"{rising_words if difficulty == RISING else difficulty} pub quiz"
        chips = [r["category"] for r in rounds]
    render.page_frame(thumbnail_html(style, title_line, sub, links.get("thumbnail_line", ""),
                                     chips, badge), 0.0, thumb, size=THUMB)
    marks = "\n".join(f"{_stamp(t)} {label}" for t, label in chapters(timeline))
    description = f"{links['description']}\n\nChapters\n{marks}"
    if credits:
        description += "\n\n" + "\n".join(credits)
    title = (links["title_options"] or [f"Pub Quiz: {title_line}"])[0]
    gallery.save_title_and_description(video_path, title, description)
    video_path.with_name(f"{stem}_meta.txt").write_text(
        "Title options:\n" + "\n".join(f"  - {t}" for t in links["title_options"]) +
        "\n\nRounds:\n" + "\n".join(f"  - {r['category']} ({r['difficulty']}): {r['stem']}" for r in rounds) +
        "\n\nJoining lines:\n" + "\n".join(f"  - {line}" for line in link_lines(links)) + "\n",
        encoding="utf-8")
    quiz.round_sidecar(video_path).write_text(json.dumps({
        "longform": True, "variant": variant, "difficulty": difficulty,
        "rounds": [r["stem"] for r in rounds], "chapters": chapters(timeline)}, indent=1), encoding="utf-8")
    unverified = [f"{r['category']} question {n}" for r, s in zip(rounds, sidecars)
                  for n in s.get("unverified") or []]
    reasons = ["A long video always waits for a look before it goes out."]
    if unverified:
        reasons.append("Answers the fact check couldn't confirm: " + ", ".join(unverified) + ".")
    gallery.save_report(video_path, {
        "longform": True, "variant": variant, "difficulty": difficulty,
        "rounds": [r["stem"] for r in rounds], "video_seconds": round(timeline["end"], 1),
        "quiz_unverified": unverified, "title_options": links["title_options"],
        "gate": {"passed": False, "reasons": reasons}})
    job_id = job_context.get_job_id()
    summary = (costs.summary_for_job(job_id) if job_id
               else costs.summary_between(started, time.time(), channel.key))
    gallery.save_cost_summary(video_path, summary)
    shutil.rmtree(work, ignore_errors=True)
    log.info(f"Done: {video_path} ({costs.format_usd(summary['total_usd'])})")
    return SimpleNamespace(video_path=video_path, warnings=[], similarity=None)


def music_bed(channel, voice: np.ndarray, fps: int, stem: str, credits: list) -> np.ndarray:
    """The channel's tracks one after another, crossfaded, ducked under
    the voice: one track looped for twenty minutes would wear thin. In
    float32 throughout, since a long video's soundtrack is tens of
    millions of samples."""
    from core import music_library
    from pipeline import sound
    from pipeline.audio import decode_audio_file

    tracks = sound.music_tracks(channel.key)
    if not tracks:
        music_library.auto_fill(channel)
        tracks = sound.music_tracks(channel.key)
    length = len(voice)
    if not tracks:
        log.info("  [sound] no music available for this channel")
        return np.zeros_like(voice)
    order = list(tracks)
    random.Random(stem).shuffle(order)
    join = int(2.0 * fps)
    pieces, have, tried = [], 0, 0
    while have < length + join and tried < len(order) * 50:
        path = order[tried % len(order)]
        tried += 1
        music = decode_audio_file(str(path), fps=fps, nchannels=2)
        if len(music) < join * 3:
            continue
        music = (music / (np.abs(music).max() or 1.0)).astype(np.float32)
        ramp = np.linspace(0, 1, join, dtype=np.float32)[:, None]
        music[:join] *= ramp
        music[-join:] *= ramp[::-1]
        if pieces:
            # Each track's fade-in overlaps the last one's fade-out.
            pieces[-1][-join:] += music[:join]
            music = music[join:]
        pieces.append(music)
        have += len(music)
        line = music_library.credit_for(path)
        if line and line not in credits:
            credits.append(line)
    if not pieces:
        return np.zeros_like(voice)
    bed = np.concatenate(pieces, axis=0)[:length]
    if len(bed) < length:
        bed = np.pad(bed, ((0, length - len(bed)), (0, 0)))
    t = np.arange(length, dtype=np.float32) / fps
    total = length / fps
    fade = np.minimum(1.0, t / sound.MUSIC_FADE_IN) * np.clip((total - t) / sound.MUSIC_FADE_OUT, 0, 1)
    duck = 1.0 - (1.0 - sound.DUCK_UNDER_SPEECH) * sound.speech_envelope(voice, fps).astype(np.float32)
    return bed * (channel.sound.music_level * fade * duck).astype(np.float32)[:, None]


def _mux(board: Path, audio: np.ndarray, fps: int, out: Path, work: Path) -> None:
    from moviepy.audio.AudioClip import AudioArrayClip
    from moviepy.video.io.ffmpeg_tools import ffmpeg_merge_video_audio

    temp_audio = work / "audio.m4a"
    clip = AudioArrayClip(audio, fps=fps)
    clip.write_audiofile(str(temp_audio), codec="aac", fps=fps, logger=None)
    clip.close()
    ffmpeg_merge_video_audio(str(board), str(temp_audio), str(out), vcodec="copy", acodec="copy",
                             logger=None)
