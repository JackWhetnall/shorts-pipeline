"""
Storyboards: a channel's next few videos written ahead, to look at
before they're made (decision 073).

A storyboard is the entry's stored script, the same one the video is made
from (`pipeline.script_gen._stored_script`): for a narrated channel each
line with its shot brief, the footage or picture it asks for; for a quiz,
the round's questions. Writing it ahead costs nothing extra, since the
video would write it anyway.

Looking is optional. An approved storyboard and one never looked at are
both made; only one being rewritten waits for its new words. The finished
video still goes to review as before. So this adds a chance to catch a
bad script before it's voiced and filmed, never a step in the way.

The next entries are pinned (`coming_up` on the plan) so that a channel
choosing at random shows the same three each time it's looked at, and
makes them in that order.
"""

from __future__ import annotations

import copy
import threading
import time

from core import curriculum
from core.errors import PipelineError
from core.logging_setup import get_logger

log = get_logger(__name__)

COMING_UP = 3
EVERY = 3600            # the background writer looks at most hourly

_lock = threading.Lock()
_writing = {}           # channel key -> when a write started, while it runs
_last_auto = 0.0


# --- what comes next ---------------------------------------------------------

def upcoming(channel, count: int = COMING_UP) -> list:
    """The next `count` plan entries in the order they'll be made, pinned
    on the plan so they stay put. [] for a channel without a topic plan."""
    if getattr(channel, "content_mode", "") != "topic" or not curriculum.exists(channel.key):
        return []
    from core import ordering
    data = curriculum.load(channel.key)
    pending = {s["id"]: s for s in data["subtopics"] if s["status"] == curriculum.PENDING}
    order = [i for i in data.get("coming_up") or [] if i in pending]
    # "Make next" goes first, whatever was pinned.
    if data.get("up_next") in pending:
        order = [data["up_next"]] + [i for i in order if i != data["up_next"]]
    order = order[:count]

    sim = copy.deepcopy(data)
    sim["coming_up"] = []

    def made(subtopic_id: str, n: int) -> None:
        for row in sim["subtopics"]:
            if row["id"] == subtopic_id:
                # After any real date, so it's the last made (ordering).
                row["status"], row["used_at"] = curriculum.USED, f"9999-{n:04d}"
    for n, subtopic_id in enumerate(order):
        made(subtopic_id, n)
    while len(order) < count:
        entry = ordering.choose_next_subtopic(channel, sim)
        if entry is not None and channel.format == "quiz" and not _makeable(channel, entry):
            entry = next((s for s in sim["subtopics"] if s["status"] == curriculum.PENDING
                          and _makeable(channel, s)), None)
        if entry is None:
            break
        order.append(entry["id"])
        made(entry["id"], len(order))

    if order != (data.get("coming_up") or [])[:len(order)]:
        fresh = curriculum.load(channel.key)
        fresh["coming_up"] = order
        curriculum.save(fresh)
    return [pending[i] for i in order]


def _makeable(channel, entry: dict) -> bool:
    from pipeline import run
    try:
        return run._round_ready(channel, entry)
    except Exception as exc:  # noqa: BLE001 - the plan still shows; it's checked again when made
        log.warning(f"Couldn't tell whether {entry.get('title')} has a round ready ({exc})")
        return True


# --- one storyboard -------------------------------------------------------------

def approved(row: dict) -> bool:
    """Looked at and passed: marked so, or for a quiz every question fine."""
    if row.get("storyboard_approved_at"):
        return True
    questions = ((row.get("script") or {}).get("quiz") or {}).get("questions") or []
    return bool(questions) and all(q.get("approved") for q in questions)


def view(channel, row: dict) -> dict:
    """An entry's storyboard for the page."""
    script = row.get("script") or {}
    topic = curriculum.find_topic(channel.key, row["topic"]) or {}
    out = {"id": row["id"], "title": row["title"], "angle": row.get("angle", ""),
           "topic": topic.get("title", ""), "written": bool(script.get("segments")),
           "approved": approved(row), "quiz": bool(script.get("quiz")) or channel.format == "quiz",
           "segments": [], "questions": [], "titles": script.get("title_options") or []}
    if script.get("quiz"):
        out["questions"] = [{"question": q["question"], "answer": q["answer"],
                             "approved": bool(q.get("approved")), "picture": q.get("subject", "")}
                            for q in script["quiz"].get("questions") or []]
    elif script.get("segments"):
        out["segments"] = [{"text": s.get("text", ""), "shot_brief": s.get("shot_brief", "")}
                           for s in script["segments"]]
    return out


def write(channel, row: dict, note: str = "") -> dict:
    """Write (or with `note`, rewrite) one entry's storyboard and store it
    as its script. Returns the script."""
    if channel.format == "quiz":
        from pipeline import quiz
        # Its ready round, with the host's lines; a picture round is
        # written and its pictures checked. Written again, the old round's
        # questions go back to the bank, never having been asked.
        old = ((row.get("script") or {}).get("quiz") or {}).get("questions") or []
        if old:
            from pipeline.facts import bank, store
            bank.unuse(store.connect(), channel.key, [q["bank_id"] for q in old if q.get("bank_id")])
        curriculum.set_script(channel.key, row["id"], None)
        script = quiz.write_round(channel, curriculum.find(channel.key, row["id"]),
                                  f"The owner asks: {note}" if note else "").to_jsonable()
    else:
        from pipeline import script_gen
        topic = curriculum.find_topic(channel.key, row["topic"])
        if topic is None:
            raise PipelineError(f"no topic {row['topic']}", user_message="That topic is no longer in the plan.")
        if note or row.get("script"):
            siblings = [s for s in curriculum.subtopics(channel.key, topic_id=topic["id"])
                        if s["id"] != row["id"] and s.get("script")]
            script = script_gen.regenerate_script(channel, topic, row, siblings, note)
        else:
            written = script_gen.write_scripts(channel, topic, [row])
            if not written:
                raise PipelineError("no script came back", user_message="The script didn't come back. "
                                                                         "Try again.")
            script = written[0]["script"]
    curriculum.set_script(channel.key, row["id"], script)
    curriculum.mark_storyboard(channel.key, row["id"], approved=False)
    return script


def edit(channel, subtopic_id: str, texts: list, briefs: list) -> None:
    """The owner's own changes to a narrated storyboard's lines and shot
    briefs, kept with everything else the script had. Counts as approved."""
    row = curriculum.find(channel.key, subtopic_id)
    script = (row or {}).get("script")
    if not script or not script.get("segments"):
        raise PipelineError("no storyboard", user_message="That storyboard hasn't been written yet.")
    segments = script["segments"]
    if len(texts) != len(segments) or len(briefs) != len(segments):
        raise PipelineError("segment count changed", user_message="The storyboard changed while you were "
                                                                  "editing it. Reload and try again.")
    for segment, text, brief in zip(segments, texts, briefs):
        text, brief = " ".join(text.split()), " ".join(brief.split())
        if not text:
            raise PipelineError("empty line", user_message="Every line needs some words.")
        if brief != segment.get("shot_brief", ""):
            # The search terms came from the old brief.
            segment["keywords"] = []
        segment["text"], segment["shot_brief"] = text, brief
    curriculum.set_script(channel.key, subtopic_id, script)
    curriculum.mark_storyboard(channel.key, subtopic_id, approved=True)


# --- written ahead -------------------------------------------------------------

def missing(channel) -> list:
    """Upcoming entries with no storyboard yet, leaving out one a video is
    being made from right now."""
    from core import jobs
    making = {(j.get("seed") or {}).get("topic_id") for j in jobs.active_in_order()
              if j.get("channel_key") == channel.key}
    return [row for row in upcoming(channel) if not row.get("script") and row["id"] not in making]


def prepare(channel) -> int:
    """Write the upcoming storyboards that are missing. Returns how many."""
    written = 0
    for row in missing(channel):
        try:
            write(channel, row)
            written += 1
        except PipelineError as exc:
            # A quiz category dry at a level, say: it's skipped when made too.
            log.warning(f"  [storyboard] {channel.key}: {row['title']}: {exc}")
    if written:
        log.info(f"  [storyboard] {channel.key}: {written} storyboard(s) written ahead")
    return written


def writing(channel_key: str) -> bool:
    with _lock:
        return channel_key in _writing


def start(channels: list, batch: bool = True) -> bool:
    """Write missing storyboards for these channels on a thread. At batch
    prices unless asked for now (`batch` off). False if already writing."""
    keys = [c.key for c in channels]
    with _lock:
        if any(k in _writing for k in keys):
            return False
        for k in keys:
            _writing[k] = time.time()

    def run():
        from pipeline import llm
        try:
            for channel in channels:
                try:
                    if batch:
                        with llm.batched():
                            prepare(channel)
                    else:
                        prepare(channel)
                except Exception as exc:  # noqa: BLE001 - one channel mustn't stop the rest
                    log.warning(f"  [storyboard] {channel.key}: couldn't write ahead ({exc})")
                finally:
                    with _lock:
                        _writing.pop(channel.key, None)
        finally:
            with _lock:
                for k in keys:
                    _writing.pop(k, None)

    threading.Thread(target=run, daemon=True, name="storyboards").start()
    return True


def keep_up(channels: dict) -> bool:
    """The scheduler's duty: at most hourly, the next storyboards of every
    channel that publishes, written at batch prices."""
    global _last_auto
    if time.time() - _last_auto < EVERY:
        return False
    wanted = [c for c in channels.values()
              if not c.archived and c.publishing.enabled and getattr(c, "content_mode", "") == "topic"]
    _last_auto = time.time()
    # A newsroom channel's angles are its scout's (decision 127).
    outlined = sum(outline_ahead(c) for c in wanted if c.format == "documentary"
                   and not getattr(c.documentary, "newsroom", False))
    wanted = [c for c in wanted if c.format != "documentary" and missing(c)]
    return bool(wanted) and start(wanted) or bool(outlined)


def outline_ahead(channel) -> int:
    """A documentary channel's next videos with no production yet get
    their angles pitched, at batch prices, to choose when the owner's
    ready (decisions 074, 086): the first stage only, since each later one
    waits for the one before to be approved. Returns how many were started."""
    from core import jobs, production
    queued = {(j.get("seed") or {}).get("subtopic_id") for j in jobs.active_in_order()
              if j.get("channel_key") == channel.key}
    started = 0
    for row in upcoming(channel):
        if production.exists(channel.key, row["id"]) or row["id"] in queued:
            continue
        try:
            jobs.start_job(channel.key, {"type": "production", "subtopic_id": row["id"], "stage": "pitch",
                                         "topic": f"{row['title']}: angle"}, behind=True)
            started += 1
        except Exception as exc:  # noqa: BLE001 - one entry mustn't stop the rest
            log.warning(f"  [productions] couldn't pitch {row['title']}: {exc}")
    return started
