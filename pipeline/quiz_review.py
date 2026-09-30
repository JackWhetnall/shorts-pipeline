"""
Reviewing a quiz round question by question (decision 055).

The owner: rather than read a whole script to check a quiz, see its
questions and answers laid out and say of each that it's fine, too easy,
too hard, or wrong (and why). A bad question is swapped for another
without writing the round again, and isn't lost: one too easy for its
round moves down in the bank to the channel's next easier level (too hard,
up), where re-rating won't move it back (`owner_level`), and a round at
that level can ask it. Only a question called wrong leaves the bank, kept
as rejected so it's never written again.

It works on a script dict wherever that lives: stored on a subtopic ahead
of its video (changed in place), or a made short's (changed as a draft
beside it, and the short remade from the draft with only the changed lines
voiced again; web.blueprints.quiz_review).
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from core.errors import PipelineError
from core.logging_setup import get_logger

log = get_logger(__name__)

VERDICTS = {"ok": "Fine", "easy": "Too easy", "hard": "Too hard", "invalid": "Wrong"}
SWAP_LOOK = 8           # bank questions looked at for a replacement
PICTURE_TRIES = 4       # picture candidates checked for one replacement

HOST_SYSTEM = """
You are the host of a quiz video. One question in a written round has been
replaced with another, and you write the two lines of yours that go with
the new one:
- `lead_in`: what you say just before reading the question, in the same
  manner and about the same length as your lead-in it replaces. It
  mustn't refer to the question that was replaced, nor give away the
  answer. Empty if the replaced lead-in was empty.
- `spoken_answer`: how you reveal the answer. Say the answer as written;
  you may add the note given with it, and nothing else of your own. Keep it
  about as long as your other reveals.
British English. The channel's brief for its host follows.
""".strip()

HOST_SCHEMA = {"type": "object", "properties": {"lead_in": {"type": "string"},
                                                "spoken_answer": {"type": "string"}},
               "required": ["lead_in", "spoken_answer"], "additionalProperties": False}


# --- reading a round ----------------------------------------------------------

def lead_in_of(script: dict, q: dict) -> str:
    text = script["segments"][q["ask"]]["text"]
    return text[:-len(q["question"])].strip() if text.endswith(q["question"]) else ""


def rows(channel, script: dict) -> list:
    """The round's questions for the review page: each with what's known
    of it in the bank, and whether it's been looked at."""
    quiz = script.get("quiz") or {}
    unverified = set(quiz.get("unverified") or [])
    bank_rows = {}
    try:
        from pipeline.facts import store
        conn = store.connect()
        ids = [q["bank_id"] for q in quiz.get("questions") or [] if q.get("bank_id")]
        if ids:
            marks = ",".join("?" * len(ids))
            bank_rows = {r["id"]: dict(r) for r in conn.execute(
                f"SELECT id, level, known_pct, note, area, owner_level FROM questions WHERE id IN ({marks})", ids)}
    except Exception as exc:  # noqa: BLE001 - the round still shows without the bank's figures
        log.warning(f"The question bank couldn't be read for the review page ({exc})")
    out = []
    for i, q in enumerate(quiz.get("questions") or []):
        known = bank_rows.get(q.get("bank_id")) or {}
        out.append({"index": i, "number": i + 1, "question": q["question"], "answer": q["answer"],
                    "spoken_answer": q.get("spoken_answer", ""), "kind": q.get("kind", ""),
                    "subject": q.get("subject", ""), "approved": bool(q.get("approved")),
                    "flagged": q.get("flagged", ""), "unverified": i + 1 in unverified,
                    "source": "bank" if q.get("bank_id") else "fact" if q.get("fact_id") else "written",
                    "level": known.get("level"), "known_pct": known.get("known_pct"),
                    "area": known.get("area", ""), "note": known.get("note", "")})
    return out


def neighbour_level(channel, level: float, direction: int) -> float:
    """The channel's next level easier (-1) or harder (+1) than this one,
    or a step and a half beyond its easiest or hardest."""
    from pipeline import quiz
    ladder = sorted({lv for _, lv in quiz.levels(channel.quiz.difficulties)})
    beyond = [lv for lv in ladder if (lv < level if direction < 0 else lv > level)]
    if beyond:
        return max(beyond) if direction < 0 else min(beyond)
    return max(1.0, min(10.0, level + 1.5 * direction))


# --- a verdict ----------------------------------------------------------------

def judge(channel, script: dict, index: int, verdict: str, reason: str = "",
          swap: bool = True) -> dict:
    """Apply the owner's verdict on one question, changing `script` in
    place. Returns {"message", "swapped", "moved_to"}. With `swap` off
    (a made short with no script kept), only the bank learns from it."""
    from pipeline import quiz as quiz_mod
    from pipeline.facts import bank, store
    if verdict not in VERDICTS:
        raise PipelineError(f"unknown verdict {verdict!r}", user_message="That isn't a verdict this page knows.")
    quiz = script.get("quiz") or {}
    questions = quiz.get("questions") or []
    if not 0 <= index < len(questions):
        raise PipelineError(f"no question {index}", user_message="That question isn't in this round any more.")
    q = questions[index]
    conn = store.connect()
    category, difficulty = quiz.get("category", ""), quiz.get("difficulty", "")
    level = quiz_mod.level_of(channel, difficulty)
    bank_id = q.get("bank_id") or (None if q.get("kind") else bank.find_id(conn, q["question"], q["answer"]))

    if verdict == "ok":
        q["approved"] = True
        q.pop("flagged", None)
        quiz["unverified"] = [n for n in quiz.get("unverified") or [] if n != index + 1]
        if bank_id:
            bank.confirm(conn, bank_id)
        return {"message": "Kept.", "swapped": False, "moved_to": None}

    moved_to = None
    if verdict in ("easy", "hard"):
        moved_to = neighbour_level(channel, level, -1 if verdict == "easy" else 1)
        if bank_id:
            bank.set_owner_level(conn, bank_id, moved_to)
        elif not q.get("kind"):
            bank_id = bank.adopt(conn, {"question": q["question"], "answer": q["answer"]},
                                 quiz_mod.base_category(category), moved_to)
        # Free for a round it suits; the channel's own record of what it
        # has asked still keeps it out while a made short asks it.
        bank.unuse(conn, channel.key, [bank_id])
    elif bank_id:
        bank.reject(conn, bank_id, reason)
    _history(quiz, q, verdict, reason)
    what = {"easy": "Moved to an easier level in the bank", "hard": "Moved to a harder level in the bank",
            "invalid": "Taken out of the bank" if bank_id else "Dropped"}[verdict]
    if not swap:
        return {"message": what + ".", "swapped": False, "moved_to": moved_to}

    new = replacement(channel, script, index, exclude={bank_id})
    if new is None:
        q["flagged"] = verdict
        return {"message": what + ", but there's no replacement for it yet, so it's still in the round.",
                "swapped": False, "moved_to": moved_to}
    put(channel, script, index, new)
    return {"message": f"{what}, and replaced.", "swapped": True, "moved_to": moved_to}


def _history(quiz: dict, q: dict, verdict: str, reason: str) -> None:
    quiz.setdefault("review", []).append({
        "question": q["question"], "answer": q["answer"], "verdict": verdict, "reason": reason.strip(),
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})


# --- a replacement ------------------------------------------------------------

def replacement(channel, script: dict, index: int, exclude=frozenset()) -> dict:
    """A question to take this one's place: from the bank for a text round
    (writing a small batch for it if the bank has none), written and
    checked for a picture round. None if nothing fits."""
    quiz = script["quiz"]
    removed = quiz["questions"][index]
    others = [x for i, x in enumerate(quiz["questions"]) if i != index]
    if removed.get("kind"):
        return _picture_replacement(channel, quiz, removed, others)
    from pipeline import quiz as quiz_mod
    from pipeline.facts import bank, keep, store
    conn = store.connect()
    category = quiz_mod.base_category(quiz.get("category", ""))
    level = quiz_mod.level_of(channel, quiz.get("difficulty", ""))
    taken = {x.get("bank_id") for x in quiz["questions"]} | set(exclude)
    refused = [removed] + [{"question": r["question"], "answer": r["answer"]} for r in quiz.get("review") or []]
    for attempt in range(2):
        for borrow in (False, True):
            for r in bank.for_round(conn, channel.key, category, level, SWAP_LOOK, exclude=taken, borrow=borrow):
                candidate = {"question": r["question"], "answer": r["answer"], "note": r["note"],
                             "bank_id": r["id"]}
                if fits(channel, candidate, others, refused):
                    return candidate
                taken.add(r["id"])
        if attempt == 0:
            log.info(f"  [quiz] no replacement in the bank for {category} near {level:g}; writing some")
            try:
                bank.write_batch(conn, category, level, keep.quiz_categories(channel) or [category],
                                 quiz_mod.BANK_TOP_UP_SIZE)
            except PipelineError as exc:
                log.warning(f"  [quiz] couldn't write replacements ({exc})")
                return None
    return None


def fits(channel, candidate: dict, others: list, refused: list) -> bool:
    """Not asked on this channel before, not one the owner turned down, and
    not clashing with the rest of the round."""
    from pipeline import quiz as quiz_mod
    return (not quiz_mod.repeats([candidate], channel.key)
            and not quiz_mod.repeats([candidate], channel.key, among=refused)
            and len(others) not in quiz_mod.round_clashes(others + [candidate]))


def _picture_replacement(channel, quiz: dict, removed: dict, others: list) -> dict:
    from pipeline import quiz as quiz_mod
    category, difficulty, kind = quiz.get("category", ""), quiz.get("difficulty", ""), removed["kind"]
    refused = [removed] + [{"question": r["question"], "answer": r["answer"]} for r in quiz.get("review") or []]
    instead = (f"Only the questions are needed this time; the intro and sign-off will be discarded. "
               f"These stay in the round, so no question may share an answer or a subject with "
               f"them:\n{quiz_mod._listed(others)}\n\n"
               f"These didn't work and mustn't come back:\n{quiz_mod._listed(refused)}")
    try:
        data = quiz_mod._write(category, difficulty, channel,
                               quiz_mod.context_questions(channel.key, category), instead, kind)
    except PipelineError as exc:
        log.warning(f"  [quiz] couldn't write a replacement picture question ({exc})")
        return None
    candidates = [c for c in data["questions"] if fits(channel, c, others, refused)][:PICTURE_TRIES]
    for candidate in candidates:
        if quiz_mod._check(channel, category, difficulty, [candidate], kind) == ["ok"]:
            return candidate
    return None


def put(channel, script: dict, index: int, new: dict) -> None:
    """Put `new` in question `index`'s place, with the host's lines for it."""
    from pipeline import quiz as quiz_mod
    quiz = script["quiz"]
    old = quiz["questions"][index]
    lead_in, spoken = host_lines(channel, script, index, new)
    lead_in = "" if index == 0 else lead_in      # the intro leads into the first question
    row = {"question": new["question"], "answer": new["answer"], "spoken_answer": spoken,
           "ask": old["ask"], "reveal": old["reveal"]}
    for key in ("kind", "subject", "picture", "fact_id", "bank_id"):
        if new.get(key):
            row[key] = new[key]
    quiz["questions"][index] = row
    script["segments"][old["ask"]]["text"] = f"{lead_in} {new['question']}".strip()
    script["segments"][old["reveal"]]["text"] = spoken
    quiz["unverified"] = [n for n in quiz.get("unverified") or [] if n != index + 1]
    quiz["pronunciations"] = quiz_mod.element_respellings(quiz["questions"])
    quiz["credits"] = sorted({q["picture"]["credit"] for q in quiz["questions"]
                              if (q.get("picture") or {}).get("credit")})
    if new.get("bank_id"):
        try:
            from pipeline.facts import bank, store
            bank.mark_used(store.connect(), channel.key, [new["bank_id"]],
                           f"{quiz.get('category', '')}: {quiz.get('difficulty', '')}")
        except Exception as exc:  # noqa: BLE001 - the swap stands; only its bookkeeping is lost
            log.warning(f"  [quiz] couldn't record the replacement as used ({exc})")


def host_lines(channel, script: dict, index: int, new: dict) -> tuple:
    """(lead_in, spoken_answer) for a replacement, in the host's voice:
    under a cent. The old lead-in and the plain answer if the call fails."""
    quiz = script["quiz"]
    old = quiz["questions"][index]
    old_lead = "" if index == 0 else lead_in_of(script, old)
    fallback = (old_lead, " ".join(p for p in (new["answer"] + ".", new.get("note") or "") if p).strip())
    around = []
    if index > 0:
        before = quiz["questions"][index - 1]
        around.append(f"Your reveal before it: {before.get('spoken_answer', '')}")
    if index + 1 < len(quiz["questions"]):
        after = quiz["questions"][index + 1]
        around.append(f"Your lead-in after it: {lead_in_of(script, after)}")
    user = "\n".join([f"The lead-in it replaces: {old_lead or '(empty)'}",
                      f"The reveal it replaces: {old.get('spoken_answer', '')}", *around, "",
                      f"The new question: {new['question']}", f"Its answer: {new['answer']}",
                      f"Note that may go with the answer: {new.get('note') or '(none)'}"])
    try:
        from pipeline.llm import SystemBlock, call_json
        data = call_json([SystemBlock(HOST_SYSTEM),
                          SystemBlock(f"The channel's brief:\n\n{channel.style_prompt}")],
                         user, HOST_SCHEMA, operation="quiz_swap", max_tokens=2000, effort="low")
    except PipelineError as exc:
        log.warning(f"  [quiz] couldn't write the host's lines for a replacement ({exc})")
        return fallback
    lead_in = " ".join((data.get("lead_in") or "").split())
    spoken = " ".join((data.get("spoken_answer") or "").split()) or fallback[1]
    return lead_in, spoken


# --- a made short's round -----------------------------------------------------

def draft_path(video_path) -> Path:
    video_path = Path(video_path)
    return video_path.with_name(f"{video_path.stem}_script_draft.json")


def made_script(channel, video_path) -> dict:
    """The script a made short came from, or None: kept beside it since
    question review arrived; before that, its subtopic's written-ahead
    script when that's what it asked, or else rebuilt from the lines its
    _meta.txt records."""
    from pipeline import quiz as quiz_mod
    video_path = Path(video_path)
    path = quiz_mod.script_sidecar(video_path)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    asked = [q.get("question") for q in (round_of_video(video_path) or {}).get("questions") or []]
    from core import curriculum
    if asked and curriculum.exists(channel.key):
        for row in curriculum.subtopics(channel.key):
            stored = row.get("script") or {}
            if row.get("video_stem") == video_path.stem and \
                    [q.get("question") for q in (stored.get("quiz") or {}).get("questions") or []] == asked:
                return copy.deepcopy(stored)
    return rebuilt_script(channel, video_path)


SEGMENT_RE = re.compile(r"^\[segment (\d+)\]\n(.*?)(?=^\[segment \d+\]|\Z)", re.S | re.M)


def rebuilt_script(channel, video_path) -> dict:
    """A made short's script put back together from what's kept beside it:
    every spoken line (_meta.txt), the round (_quiz.json) and the
    description. None if any of it is missing or doesn't line up."""
    from pipeline import quiz as quiz_mod
    video_path = Path(video_path)
    kept = round_of_video(video_path)
    meta = video_path.with_name(f"{video_path.stem}_meta.txt")
    if not kept or not kept.get("questions") or not meta.exists():
        return None
    from core.gallery import read_text_tolerantly
    text = read_text_tolerantly(meta).replace("\r\n", "\n")
    titles = [line[4:].strip() for line in text.split("\n") if line.startswith("  - ")]
    lines = [body.split("\n  shot:")[0].split("\n  keywords:")[0].strip() for _, body in SEGMENT_RE.findall(text)]
    conn = None
    try:
        from pipeline.facts import store
        conn = store.connect()
    except Exception as exc:  # noqa: BLE001 - the round rebuilds without its bank ids
        log.warning(f"The question bank couldn't be read ({exc})")
    rows, at = [], 0
    for q in kept["questions"]:
        ask = next((i for i in range(at, len(lines) - 1) if lines[i].endswith(q["question"])), None)
        if ask is None:
            return None
        row = {"question": q["question"], "answer": q["answer"], "spoken_answer": lines[ask + 1],
               "ask": ask, "reveal": ask + 1,
               **{k: q[k] for k in ("kind", "subject", "picture", "bank_id", "fact_id") if q.get(k)}}
        if conn is not None and not row.get("bank_id") and not row.get("kind"):
            from pipeline.facts import bank
            found = bank.find_id(conn, q["question"], q["answer"])
            if found:
                row["bank_id"] = found
        rows.append(row)
        at = ask + 2
    segments = [{"text": line} for line in lines]
    for row in rows:
        segments[row["ask"]]["pause_after"] = float(channel.quiz.countdown_seconds)
        segments[row["reveal"]]["pause_after"] = float(channel.quiz.answer_pause)
    described = video_path.with_name(f"{video_path.stem}_description.txt")
    body = read_text_tolerantly(described).strip().split("\n\n")[0] if described.exists() else ""
    return {"segments": segments, "title_options": titles, "description_body": body,
            "quiz": {"category": kept.get("category", ""), "difficulty": kept.get("difficulty", ""),
                     "questions": rows, "hook": lines[0] if rows[0]["ask"] == 2 else "",
                     "countdown": float(channel.quiz.countdown_seconds),
                     "unverified": list(kept.get("unverified") or []),
                     "pronunciations": quiz_mod.element_respellings(rows),
                     "credits": list(kept.get("credits") or [])}}


def round_of_video(video_path) -> dict:
    """The questions a made short asked (its _quiz.json), or None."""
    from pipeline import quiz as quiz_mod
    path = quiz_mod.round_sidecar(video_path)
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, ValueError):
        return None


def draft(channel, video_path) -> dict:
    """The script being edited for a made short: its draft, else a copy of
    the script it was made from. None if neither can be had."""
    path = draft_path(video_path)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return made_script(channel, video_path)


def save_draft(video_path, script: dict) -> None:
    draft_path(video_path).write_text(json.dumps(script, indent=1, ensure_ascii=False), encoding="utf-8")


def swapped(channel, video_path) -> list:
    """Numbers of the questions a made short's draft has changed."""
    path = draft_path(video_path)
    made = made_script(channel, video_path)
    if not path.exists() or not made:
        return []
    now = json.loads(path.read_text(encoding="utf-8"))["quiz"]["questions"]
    was = made["quiz"]["questions"]
    return [i + 1 for i, (a, b) in enumerate(zip(now, was)) if a["question"] != b["question"]]


def read_only_script(video_path) -> dict:
    """A made short whose script can't be had: its questions alone, enough
    to judge (the bank learns) but not to swap."""
    kept = round_of_video(video_path) or {}
    return {"segments": [], "quiz": {"category": kept.get("category", ""),
                                     "difficulty": kept.get("difficulty", ""),
                                     "questions": [dict(q) for q in kept.get("questions") or []],
                                     "unverified": list(kept.get("unverified") or [])}}
