"""
The newsroom (decision 127): a film's angle, outline and script made by
agents on the owner's Claude subscription, each a role that can send the
work back or scrap it, before any money is spent on its pictures and voice.

The owner, on 21 Oct: "at no point is there any verification that topic X
will actually result in a good script, each part of the process assumes
that the previous or next part is going to deal with whatever is made."
So a topic is pitched with evidence, commissioned or scrapped, proved by
writing its outline and first minute before anyone writes the rest, and
the script is edited, fact-checked, given its pictures and its packaging
by editors who didn't write it, with a last read before it's drawn:

    pitch        the scout: the question, the answer, why people want to
                 know (what the YouTube search shows), the beats
    commission   the commissioning editor: commission, rework or scrap
    proof        the writer: the outline and the whole first chapter
    proof_review the script editor: go, rework or scrap, on the proof
    draft        the writer: the whole script
    edit         the script editor: lines edited; pass, rework or scrap
    facts        the fact checker: every claim and card
    pictures     the picture editor: every picture planned together
    packaging    the packaging editor: title, thumbnail, description
    final        the managing editor: pass (it's drawn), back or scrap

and, once it's drawn and made, the overseer's checkpoints as two more
roles: `storyboard` (the picture editor) and `teasers`; and `bank`, the
scout keeping the topic plan stocked.

Each role is a subagent (.claude/agents/newsroom-*.md) that a scheduled
session sends in one at a time, overnight (docs/newsroom.md). This module
is their desk: it hands out what's due, briefs each role with the same
instructions and checks the API stages use (so nothing learnt in earlier
decisions is lost), takes the work back, holds it to the rules a model
can't argue with, and moves the film on. The work is on the
subscription: a newsroom film's writing costs no API money.

The subscription has a five-hour and a weekly limit, shared with the
owner's own use, so the work is counted in points (a draft is the
heaviest), with a cap a session and a cap a week.

    python -m core.newsroom status <channel>
    python -m core.newsroom next <channel>
    python -m core.newsroom brief <channel> <assignment>
    python -m core.newsroom submit <channel> <assignment>
    python -m core.newsroom demand <channel> "search words"
    python -m core.newsroom performance <channel>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone

from core import curriculum, production
from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import CHANNELS_DIR

log = get_logger(__name__)

# role: (the agent that does it, its points)
ROLES = {
    "pitch": ("newsroom-scout", 1),
    "commission": ("newsroom-commissioning-editor", 1),
    "proof": ("newsroom-writer", 2),
    "proof_review": ("newsroom-script-editor", 1),
    "draft": ("newsroom-writer", 3),
    "edit": ("newsroom-script-editor", 2),
    "facts": ("newsroom-fact-checker", 1),
    "pictures": ("newsroom-picture-editor", 1),
    "packaging": ("newsroom-packaging-editor", 1),
    "final": ("newsroom-managing-editor", 1),
    "storyboard": ("newsroom-picture-editor", 1),
    "teasers": ("newsroom-teaser-editor", 1),
    "bank": ("newsroom-scout", 1),
    "analysis": ("newsroom-analyst", 1),
}
# The order work is handed out in: a film nearest done first, so films
# finish rather than all starting.
PRIORITY = ("analysis", "teasers", "storyboard", "final", "packaging", "pictures", "facts", "edit", "draft",
            "proof_review", "proof", "commission", "pitch", "bank")
# A film's state: the role due next.
DUE = {"": "pitch", "rework_pitch": "pitch", "pitched": "commission", "commissioned": "proof",
       "rework_proof": "proof", "proofed": "proof_review", "drafting": "draft", "rework_draft": "draft",
       "drafted": "edit", "edited": "facts", "checked": "pictures", "pictured": "packaging",
       "packaged": "final"}
IN_WRITING = {"rework_proof", "proofed", "drafting", "rework_draft", "drafted", "edited", "checked",
              "pictured", "packaged"}
DONE = {"passed", "scrapped"}

# About 15 points a film, reworks included, plus its storyboard and
# teasers. A point is about 22,000 subscription tokens, measured over the
# first night (a scout's pitches with their searches, about 40,000 a
# film). The owner's usage page put the newsroom at about 1% of a day's
# use (22 Oct): the caps are only a backstop; the bank (BANK_FILMS) is
# what slows it once films are waiting.
WEEK_POINTS = 240
SESSION_POINTS = 48
SESSION_HOURS = 4               # work issued within this long counts as one session's
STALE_HOURS = 4                 # an assignment not handed in by then is handed out again
FILMS_WRITING = 3               # films between their proof and their pass, at once
FILMS_PASSED_WAITING = 3        # films passed and not yet drawn
# Newsroom films passed and not yet out: three weeks of films at two a
# week. With this many in hand no new film is started, so the newsroom
# slows by itself (the owner, 22 Oct).
BANK_FILMS = 6
PITCHED_AHEAD = 3               # films pitched or commissioned, waiting to be written
PITCH_BATCH = 3
ROUNDS = {"pitch": 1, "proof": 2, "draft": 2, "final": 1}
SUBMITS = 4                     # tries at handing in one assignment
LOWEST_PASS = 6                 # no score under this goes on
DEMAND_PER_DAY = 25             # YouTube searches: 101 quota units each, of 10,000 a day
KEEP_DONE = 300


def _now() -> float:
    return time.time()


def _stamp(at: float = None) -> str:
    return datetime.fromtimestamp(at or _now(), timezone.utc).isoformat(timespec="seconds")


# --- the ledger: what's been handed out and done ------------------------------------------

def _ledger_path(key: str):
    return CHANNELS_DIR / key / "newsroom.json"


def work_dir(key: str):
    """Where the roles write what they hand in (under the channel's folder,
    so a rename carries it, decision 057)."""
    return CHANNELS_DIR / key / "newsroom"


def load_ledger(key: str) -> dict:
    try:
        data = json.loads(_ledger_path(key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("open", {})
    data.setdefault("done", [])
    data.setdefault("demand", [])
    return data


def save_ledger(key: str, data: dict) -> None:
    path = _ledger_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["done"] = data["done"][-KEEP_DONE:]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def points_used(ledger: dict, hours: float, now: float = None) -> int:
    """Points handed out in the last `hours`, done or still open."""
    now = now or _now()
    rows = list(ledger["open"].values()) + ledger["done"]
    return sum(r["points"] for r in rows if now - r["issued_at"] < hours * 3600)


def tokens_used(ledger: dict, hours: float, now: float = None) -> int:
    """Subscription tokens the roles used in the last `hours`, as the
    session recorded them (`spent`): the measure the points stand for."""
    now = now or _now()
    return sum(r.get("tokens") or 0 for r in ledger["done"] if now - r["issued_at"] < hours * 3600)


def spent(key: str, aid: str, tokens: int) -> bool:
    """Record what an assignment's role used of the subscription."""
    ledger = load_ledger(key)
    for row in reversed(ledger["done"]):
        if row["id"] == aid:
            row["tokens"] = int(tokens)
            save_ledger(key, ledger)
            return True
    if aid in ledger["open"]:
        ledger["open"][aid]["tokens"] = int(tokens)
        save_ledger(key, ledger)
        return True
    return False


def _prune(ledger: dict, now: float) -> None:
    """An assignment not handed in within STALE_HOURS is given up: its film
    hasn't moved, so it's due again."""
    for aid, row in list(ledger["open"].items()):
        if now - row["issued_at"] > STALE_HOURS * 3600:
            ledger["done"].append({**ledger["open"].pop(aid), "verdict": "not handed in", "done_at": now})


# --- the films ----------------------------------------------------------------------------

def newsroom_of(data: dict) -> dict:
    return data.get("newsroom") or {}


def state_of(data: dict) -> str:
    return newsroom_of(data).get("state", "")


def candidates(channel, count: int = 12) -> list:
    """[(plan entry, production)] the newsroom may take on, in plan order:
    not yet outlined, and not passed or scrapped."""
    from core import storyboard
    out = []
    for row in storyboard.upcoming(channel, count=count):
        data = production.load(channel.key, row["id"], row["title"])
        if production.state(data, "outline") == "todo" and state_of(data) not in DONE:
            out.append((row, data))
    return out


def _films(channel) -> list:
    """[(plan entry or None, production)] of the channel's films in the newsroom."""
    out = []
    for data in production.all_for(channel.key):
        if newsroom_of(data):
            out.append((curriculum.find(channel.key, data["subtopic_id"]), data))
    return out


def _in_hand(channel) -> int:
    """Newsroom films passed and not yet published, being written included."""
    out = 0
    for row, d in _films(channel):
        if state_of(d) in IN_WRITING or (state_of(d) == "passed" and (row or {}).get("status") != curriculum.PUBLISHED):
            out += 1
    return out


def _passed_waiting(channel) -> int:
    return sum(1 for _, d in _films(channel)
               if state_of(d) == "passed" and production.state(d, "stills") in ("todo", "stale"))


def due(channel, ledger: dict = None) -> list:
    """[{role, films}] in PRIORITY order: the work that can be done now."""
    from core import overseer
    ledger = ledger or load_ledger(channel.key)
    taken = {s for row in ledger["open"].values() for s in row["films"]}
    found = []
    for f in overseer.status():
        if f["channel"] != channel.key or f["id"] in taken:
            continue
        if "teasers" in f["waiting"]:
            found.append({"role": "teasers", "films": [f["id"]]})
        if "stills" in f["waiting"]:
            found.append({"role": "storyboard", "films": [f["id"]]})
    films = [(row, d) for row, d in _films(channel) if d["subtopic_id"] not in taken and row is not None]
    writing = sum(1 for _, d in films if state_of(d) in IN_WRITING)
    room = writing < FILMS_WRITING and _passed_waiting(channel) < FILMS_PASSED_WAITING \
        and _in_hand(channel) < BANK_FILMS
    pitched = [d["subtopic_id"] for _, d in films if state_of(d) == "pitched"]
    if pitched:
        found.append({"role": "commission", "films": pitched})
    for _, d in films:
        state = state_of(d)
        role = DUE.get(state)
        if role in (None, "pitch", "commission"):
            continue
        if state == "commissioned" and not room:
            continue
        if state == "commissioned":
            writing += 1
            room = writing < FILMS_WRITING
        found.append({"role": role, "films": [d["subtopic_id"]]})
    waiting = sum(1 for _, d in films if state_of(d) in ("pitched", "commissioned"))
    rework = [d["subtopic_id"] for _, d in films if state_of(d) == "rework_pitch"]
    fresh = [row["id"] for row, d in candidates(channel) if not state_of(d) and row["id"] not in taken]
    wanted = rework + (fresh[:max(0, PITCHED_AHEAD - waiting - len(rework))]
                       if _in_hand(channel) < BANK_FILMS else [])
    if wanted:
        found.append({"role": "pitch", "films": wanted[:PITCH_BATCH]})
    if curriculum.exists(channel.key) and curriculum.progress(channel.key)["running_low"] \
            and not any(r["role"] == "bank" and _now() - r["issued_at"] < 86400
                        for r in list(ledger["open"].values()) + ledger["done"]):
        found.append({"role": "bank", "films": []})
    if analysis_due(channel) and not any(r["role"] == "analysis" for r in ledger["open"].values()):
        found.append({"role": "analysis", "films": []})
    return sorted(found, key=lambda a: PRIORITY.index(a["role"]))


def next_assignment(channel, now: float = None) -> tuple:
    """(assignment, "") for the next piece of work, handed out; or (None,
    why there's none)."""
    now = now or _now()
    ledger = load_ledger(channel.key)
    _prune(ledger, now)
    week, session = points_used(ledger, 7 * 24, now), points_used(ledger, SESSION_HOURS, now)
    for item in due(channel, ledger):
        agent, points = ROLES[item["role"]]
        if week + points > WEEK_POINTS:
            save_ledger(channel.key, ledger)
            return None, f"this week's {WEEK_POINTS} points are used ({week})"
        if session + points > SESSION_POINTS:
            save_ledger(channel.key, ledger)
            return None, f"this session's {SESSION_POINTS} points are used ({session}); the next session goes on"
        aid = f"{item['role']}-{'-'.join(item['films']) or 'plan'}-{int(now) % 100000:05d}"
        row = {"id": aid, "role": item["role"], "agent": agent, "points": points, "films": item["films"],
               "issued_at": now, "tries": 0}
        ledger["open"][aid] = row
        save_ledger(channel.key, ledger)
        return row, ""
    save_ledger(channel.key, ledger)
    return None, "nothing is due"


# --- what each role is given --------------------------------------------------------------

SHAPES = {
    "pitch": """{"pitches": [{"film": "<film id>",
   "question": "the viewer's question, in their words",
   "answer": "the true, surprising answer in two or three sentences",
   "why_care": "why a stranger scrolling past wants to know",
   "demand": [{"query": "what you searched", "found": "what the YouTube search showed: views, channels, gaps"}],
   "beats": [{"beat": "what this part of the film does", "reveal": "the new thing the viewer learns"}],
   "angle": {"title": "...", "thumbnail": {"subject": "...", "words": "..."}, "promise": "...",
             "hook": "the first spoken line or two", "open_loop": "..."},
   "risks": "what could make this film weak"}]}""",
    "commission": """{"verdicts": [{"film": "<film id>", "verdict": "commission" | "rework" | "scrap",
   "scores": {"curiosity": 1-10, "demand": 1-10, "material": 1-10, "pictures": 1-10},
   "notes": ["what the scout or the writer must do or keep"], "reason": "why, in a sentence"}]}""",
    "proof": """{"outline": {the outline, exactly in the outline shape below},
 "scenes": [every scene of chapter 1, exactly in the scene shape below],
 "answered": "how you dealt with each note you were given"}""",
    "proof_review": """{"verdict": "go" | "rework" | "scrap",
 "scores": {"opening": 1-10, "momentum": 1-10, "clarity": 1-10, "material": 1-10},
 "notes": ["what the writer must change, each specific"], "reason": "why, in a sentence"}""",
    "draft": """{"scenes": [every scene of the whole film, chapter 1 included, in the scene shape below],
 "description": "the YouTube description",
 "answered": "how you dealt with each note you were given"}""",
    "edit": """{"verdict": "pass" | "rework" | "scrap",
 "chapters": [{"chapter": 1, "momentum": 1-10, "specificity": 1-10, "voice": 1-10, "clarity": 1-10}],
 "edits": [{"scene": <number>, "narration": "the line as it should be", "why": "..."}],
 "notes": ["for the writer, if it goes back"], "reason": "why, in a sentence"}""",
    "facts": """{"verdict": "ok" | "scrap",
 "facts": {"fixes": [{"scene": <number>, "problem": "...", "narration": "the fixed line, or empty",
                      "card": "or empty", "card_heading": "or empty", "card_caption": "or empty"}],
           "description": "or empty", "title": "or empty", "thumbnail_words": "or empty"},
 "cards": {"fixes": [{"scene": <number>, "problem": "...", "picture": false, "kind": "number",
                      "heading": "...", "value": "...", "caption": "...", "items": []}]},
 "checked": ["each central claim you checked, and where"], "reason": "for a scrap: why"}""",
    "pictures": """{"subjects": [{"scene": <number>, "subject": "its main subject, two to four words"}],
 "changes": [{"scene": <number>, "action": "reuse" | "redirect", "same_as": <scene or -1>,
              "direction": "...", "setting": "...", "cast": ["..."], "why": "..."}]}""",
    "packaging": """{"title": "...", "thumbnail": {"subject": "...", "words": "at most four words, or empty"},
 "description": "the YouTube description", "why": "why this will win the click and keep its promise"}""",
    "final": """{"verdict": "pass" | "back" | "scrap", "back_to": "draft" | "edit" | "pictures" | "packaging" | "",
 "notes": ["what must change, if it goes back"], "summary": "two sentences for the owner"}""",
    "storyboard": """{"summary": "what you redrew and approved, or why you held it"}""",
    "teasers": """{"summary": "what you changed and approved"}""",
    "bank": """{"summary": "the topic added, its subtopics, anything skipped"}""",
    "analysis": """{"findings": {"scout": [{"text": "what to do differently", "evidence": "which films, which figures",
                        "confidence": "strong" | "suggestive" | "hunch"}],
              "writer": [...], "script_editor": [...], "packaging": [...], "pictures": [...]},
 "summary": "two sentences for the owner"}""",
}

LABELS = {"pitch": "Pitch these films", "commission": "Commission, rework or scrap these pitches",
          "proof": "Write the proof: the outline and the whole first chapter",
          "proof_review": "Review the proof", "draft": "Write the whole script", "edit": "Edit the script",
          "facts": "Check the facts and the cards", "pictures": "Plan every picture",
          "packaging": "Package the film", "final": "The last read before it's drawn",
          "storyboard": "Review the storyboard", "teasers": "Review the teasers", "bank": "Stock the topic plan",
          "analysis": "Read the published films and tell each role what they teach"}


def _channel(key: str):
    from core.channels import load_channels
    return load_channels()[key]


def performance(channel) -> str:
    """The channel's published films as the editors judge by them: views,
    click-through, how much was watched, how many were still there at 30
    seconds, where the most left and what was said there, and how each
    opened."""
    from core import gallery, reach, retention
    from core.audience import video_id
    lines = []
    for data in production.all_for(channel.key):
        path = production.video_file(channel, data)
        if path is None or not path.exists():
            continue
        info = gallery.load_publish_info(path)
        if not gallery.is_out(info):
            continue
        stats = gallery.load_stats(path) or {}
        vid = video_id(info.get("youtube_url") or "")
        days = reach.days(channel.key, vid) if vid else {}
        shown = sum(d[0] for d in days.values())
        clicks = sum(d[0] * (d[1] / 100 if d[1] > 1 else d[1]) for d in days.values())
        scenes = (data.get("script") or {}).get("scenes") or []
        curve = retention.for_video(path)
        bits = [f"{stats.get('views', '?')} views"]
        if shown:
            bits.append(f"{shown:,} impressions, {100 * clicks / shown:.1f}% clicked")
        if stats.get("avg_view_percent") is not None:
            bits.append(f"{stats['avg_view_percent']:.0f}% watched on average")
        if curve.get("kept_30s") is not None:
            bits.append(f"{curve['kept_30s']}% still there at 30 seconds")
        lines.append(f"- {production.packaging(data).get('title') or data.get('title')}: " + "; ".join(bits))
        lines.append(f"    Opened: {' '.join(s['narration'] for s in scenes[:2])[:300]}")
        for drop in (curve.get("drops") or [])[:2]:
            said = scenes[drop["scene"]]["narration"] if drop["scene"] < len(scenes) else ""
            lines.append(f"    Lost {drop['lost']:.0f}% of viewers at {drop['at']}s, over: {said[:200]}")
    if not lines:
        return "No film is out yet."
    return ("Published films (a film's first week is a small sample; typical for this length is about 30% "
            "watched and 60-70% still there at 30 seconds):\n" + "\n".join(lines))


def _channel_text(channel) -> str:
    from pipeline.documentary import kinds, script
    doc = channel.documentary
    rate = script.words_per_second(channel)
    parts = [f"THE CHANNEL: {channel.channel_display_name or channel.key}",
             f"Films run about {float(doc.minutes):g} minutes; the narrator reads about {rate * 60:.0f} words a "
             f"minute, so a film is about {round(float(doc.minutes) * 60 * rate)} words.",
             f"Its brief for its writers:\n{channel.style_prompt}"]
    if channel.hook_style:
        parts.append(f"How it opens a video: {channel.hook_style}")
    parts.append("What it can make well:\n" + kinds.TOPIC_FIT[kinds.of(channel)])
    if channel.avoid_imagery:
        parts.append("Never shown: " + ", ".join(channel.avoid_imagery))
    return "\n\n".join(parts)


def _learnt(channel) -> str:
    from core import lessons
    return "\n\n".join(x for x in (performance(channel), lessons.for_prompt(channel.key)) if x)


def _sheet(outline: dict, scenes: list, pictures: bool = True) -> str:
    """A script as an editor reads it: chapter by chapter, every scene
    numbered, with its picture or card."""
    lines, chapter = [], 0
    chapters = outline.get("chapters") or []
    for i, s in enumerate(scenes):
        if s["chapter"] != chapter:
            chapter = s["chapter"]
            title = chapters[chapter - 1]["title"] if chapter - 1 < len(chapters) else ""
            lines.append(f"\n== Chapter {chapter}: {title}")
        if not pictures:
            lines.append(f"[{i}] {s['narration']}")
            continue
        if s.get("medium") == "card":
            card = s.get("card") or {}
            lines.append(f"[{i}] CARD {card.get('kind')}: heading \"{card.get('heading', '')}\" value "
                         f"\"{card.get('value', '')}\" caption \"{card.get('caption', '')}\" items "
                         f"\"{'; '.join(card.get('items') or [])}\"")
        else:
            again = f" (shows scene {s['same_as']}'s picture again)" if isinstance(s.get("same_as"), int) else ""
            lines.append(f"[{i}] picture in {s.get('setting') or '?'}{again}: {s.get('direction', '')}")
        lines.append(f"     SAYS: {s['narration']}")
    return "\n".join(lines).strip()


def _pitch_text(pitch: dict) -> str:
    angle = pitch.get("angle") or {}
    thumb = angle.get("thumbnail") or {}
    beats = "\n".join(f"  {n}. {b.get('beat', '')} -> {b.get('reveal', '')}"
                      for n, b in enumerate(pitch.get("beats") or [], start=1))
    demand = "\n".join(f"  - {d.get('query', '')}: {d.get('found', '')}" for d in pitch.get("demand") or [])
    return (f"Question: {pitch.get('question', '')}\nAnswer: {pitch.get('answer', '')}\n"
            f"Why people care: {pitch.get('why_care', '')}\nDemand:\n{demand}\nBeats:\n{beats}\n"
            f"Title: {angle.get('title', '')}\nThumbnail: {thumb.get('subject', '')} / words "
            f"\"{thumb.get('words', '')}\"\nPromise: {angle.get('promise', '')}\nHook: {angle.get('hook', '')}\n"
            f"Open loop: {angle.get('open_loop', '')}\nRisks: {pitch.get('risks', '')}")


def _notes_text(nr: dict) -> str:
    """The notes the film's last verdict left for whoever works on it next."""
    notes = nr.get("notes") or []
    if not notes:
        return ""
    return "NOTES YOU MUST DEAL WITH (from the last verdict):\n" + "\n".join(f"- {n}" for n in notes)


def _verdicts_text(nr: dict) -> str:
    rows = nr.get("log") or []
    return "\n".join(f"- {r['role']}: {r['verdict']}" + (f": {r['reason']}" if r.get("reason") else "")
                     for r in rows) or "(none yet)"


def brief(key: str, aid: str) -> str:
    """Everything a role needs for one assignment, and how to hand it in."""
    ledger = load_ledger(key)
    row = ledger["open"].get(aid)
    if row is None:
        raise PipelineError(f"no open assignment {aid}", user_message=f"There's no open assignment {aid}.")
    channel = _channel(key)
    role = row["role"]
    out = work_dir(key) / f"{aid}.json"
    head = [f"ASSIGNMENT {aid}: {LABELS[role]}.", "",
            f"Hand in: write your work as JSON to {out}, in exactly this shape:", SHAPES[role], "",
            f"Then run: python -m core.newsroom submit {key} {aid}",
            "If it lists problems, fix them in the file and submit again. Everything you hand in is kept, "
            "with your verdict, for the owner to read.", ""]
    learnt = findings_text(key, role)
    return "\n".join(head) + "\n" + (learnt + "\n\n" if learnt else "") + _BRIEFS[role](channel, row)


def _brief_pitch(channel, row) -> str:
    from pipeline.documentary import pitch
    parts = [_channel_text(channel), _learnt(channel)]
    rules = False
    for sid in row["films"]:
        entry = curriculum.find(channel.key, sid) or {}
        data = production.load(channel.key, sid, entry.get("title", ""))
        system, user = pitch.prompt(channel, entry, angles=1)
        if not rules:
            parts.append("HOW A PITCH'S ANGLE IS WRITTEN (the rules every title and hook must follow; in the "
                         "newsroom you write one angle a film, in the shape above, with no `scores` or `why`):\n"
                         + "\n\n".join(b.text for b in system))
            rules = True
        film = [f"FILM {sid}", user]
        old = production.chosen_angle(data)
        if old:
            film.append(f"An earlier, unchecked angle for it (improve on it or replace it): {old.get('title')} / "
                        f"hook: {old.get('hook')}")
        nr = newsroom_of(data)
        if nr.get("pitch"):
            film += ["Your last pitch for it:", _pitch_text(nr["pitch"])]
        if nr.get("notes"):
            film.append(_notes_text(nr))
        parts.append("\n".join(film))
    parts.append(f"Search demand with: python -m core.newsroom demand {channel.key} \"search words\" "
                 f"(at most {DEMAND_PER_DAY} a day across the newsroom; a few per film is plenty).")
    return "\n\n".join(parts)


def _brief_commission(channel, row) -> str:
    from pipeline.documentary import pitch
    parts = [_channel_text(channel), _learnt(channel)]
    titles = pitch.earlier_titles(channel.key, "")
    if titles:
        parts.append("The channel's other films:\n" + "\n".join(f"- {t}" for t in titles))
    for sid in row["films"]:
        nr = newsroom_of(production.load(channel.key, sid))
        used = nr.get("rounds", {}).get("pitch", 0)
        parts.append(f"PITCH {sid} (reworks left: {ROUNDS['pitch'] - used})\n" + _pitch_text(nr.get("pitch") or {}))
    return "\n\n".join(parts)


def _film(channel, row) -> tuple:
    sid = row["films"][0]
    entry = curriculum.find(channel.key, sid) or {"id": sid, "title": sid, "topic": ""}
    data = production.load(channel.key, sid, entry.get("title", ""))
    return entry, data, newsroom_of(data)


def _angle(nr: dict) -> dict:
    return (nr.get("pitch") or {}).get("angle") or {}


def _brief_proof(channel, row) -> str:
    from pipeline.documentary import outline, script
    entry, data, nr = _film(channel, row)
    system, user = outline.prompt(channel, entry, angle=_angle(nr))
    parts = [_channel_text(channel),
             "THE COMMISSIONED PITCH:\n" + _pitch_text(nr.get("pitch") or {}),
             _notes_text(nr),
             "HOW THE OUTLINE IS WRITTEN:\n" + "\n\n".join(b.text for b in system) + "\n\n" + user,
             "THE OUTLINE SHAPE:\n" + json.dumps(outline.schema(), indent=1),
             "HOW THE SCRIPT IS WRITTEN:\n" + script.instructions(channel),
             "THE SCENE SHAPE:\n" + json.dumps(script.schema()["properties"]["scenes"]["items"], indent=1)]
    if nr.get("proof"):
        parts.append("YOUR LAST PROOF (rework it to the notes):\n"
                     + _sheet(nr["proof"]["outline"], nr["proof"]["scenes"]))
    parts.append("Write the outline, then chapter 1 in full (the cold open). Chapter 1's length is set by its "
                 "minutes in your outline at the narrator's rate; the desk checks it.")
    return "\n\n".join(p for p in parts if p)


def _brief_proof_review(channel, row) -> str:
    from pipeline.documentary import editor, kinds, script
    entry, data, nr = _film(channel, row)
    proof = nr.get("proof") or {}
    used = nr.get("rounds", {}).get("proof", 0)
    found = []
    if kinds.family(kinds.of(channel)) == "explainer":
        found = [p for ps in editor.explainer_checks(proof.get("scenes") or []).values() for p in ps]
    return "\n\n".join(p for p in [
        _channel_text(channel), _learnt(channel),
        "THE COMMISSIONED PITCH:\n" + _pitch_text(nr.get("pitch") or {}),
        "THE VERDICTS SO FAR:\n" + _verdicts_text(nr),
        "THE OUTLINE:\n" + script.outline_text(proof.get("outline") or {"chapters": []}, _angle(nr)),
        "CHAPTER 1, IN FULL:\n" + _sheet(proof.get("outline") or {}, proof.get("scenes") or []),
        "WHAT THE CODE FOUND (no model): " + ("; ".join(found) or "nothing"),
        f"Reworks left: {ROUNDS['proof'] - used}.",
        "HOW THE SCRIPT WAS TO BE WRITTEN (judge it against this):\n" + script.instructions(channel)] if p)


def _brief_draft(channel, row) -> str:
    from pipeline.documentary import script
    entry, data, nr = _film(channel, row)
    proof = nr.get("proof") or {}
    outline_ = proof.get("outline") or {"chapters": []}
    targets = []
    for n, c in enumerate(outline_.get("chapters") or [], start=1):
        words, scenes = script.chapter_target(channel, outline_, n)
        targets.append(f"- chapter {n} ({c['title']}): about {words} words in about {scenes} scenes")
    parts = [_channel_text(channel),
             "THE COMMISSIONED PITCH:\n" + _pitch_text(nr.get("pitch") or {}),
             "THE OUTLINE:\n" + script.outline_text(outline_, _angle(nr)),
             "CHAPTER 1 AS PASSED (keep it, refined only where a note asks):\n"
             + _sheet(outline_, proof.get("scenes") or []),
             _notes_text(nr),
             "HOW THE SCRIPT IS WRITTEN:\n" + script.instructions(channel),
             "THE SCENE SHAPE:\n" + json.dumps(script.schema()["properties"]["scenes"]["items"], indent=1),
             f"EACH CHAPTER'S LENGTH (the desk checks each is at least {int(script.SHORT_OF * 100)}% of this):\n"
             + "\n".join(targets)]
    if nr.get("draft"):
        parts.append("YOUR LAST DRAFT (rework it to the notes):\n" + _sheet(outline_, nr["draft"]["scenes"]))
    return "\n\n".join(p for p in parts if p)


def _brief_edit(channel, row) -> str:
    from pipeline.documentary import editor, kinds, script
    entry, data, nr = _film(channel, row)
    outline_, draft = nr["proof"]["outline"], nr["draft"]
    found = editor.checks(draft, outline_, _angle(nr), kinds.of(channel))
    used = nr.get("rounds", {}).get("draft", 0)
    return "\n\n".join(p for p in [
        _channel_text(channel), _learnt(channel),
        "THE COMMISSIONED PITCH:\n" + _pitch_text(nr.get("pitch") or {}),
        "THE VERDICTS SO FAR:\n" + _verdicts_text(nr),
        "HOW EACH CHAPTER IS SCORED:\n" + editor.critic_text(kinds.of(channel)),
        "REPEATED POINTS:\n" + editor.RESTATED.replace("{most}", str(editor.RESTATED_MAX)),
        "THE LAST LINE:\n" + editor.FINAL,
        "WHAT THE CODE FOUND (no model; fix or overrule each):\n"
        + ("\n".join(f"- chapter {n}: {p}" for n, ps in sorted(found.items()) for p in ps) or "nothing"),
        f"Reworks left: {ROUNDS['draft'] - used}.",
        "THE OUTLINE:\n" + script.outline_text(outline_, _angle(nr)),
        "THE SCRIPT:\n" + _sheet(outline_, draft["scenes"]),
        f"THE DESCRIPTION: {draft.get('description', '')}"] if p)


def _brief_facts(channel, row) -> str:
    from pipeline.documentary import editor
    entry, data, nr = _film(channel, row)
    draft = nr["draft"]
    cards = editor.cards_prompt(draft, _angle(nr))
    return "\n\n".join(p for p in [
        _channel_text(channel),
        "HOW TO CHECK THE FACTS:\n" + editor.FACTS,
        "Check the film's central claims against real sources (search the web); work every ratio out yourself.",
        editor.facts_prompt(draft, _angle(nr)),
        ("HOW TO REVIEW THE CARDS:\n" + editor.CARDS + "\n\n" + cards) if cards
        else "There are no cards: leave `cards.fixes` empty."] if p)


def _brief_pictures(channel, row) -> str:
    from pipeline.documentary import kinds, pictures
    entry, data, nr = _film(channel, row)
    outline_, draft = nr["proof"]["outline"], nr["draft"]
    left = row.get("left") or []
    return "\n\n".join(p for p in [
        "HOW TO PLAN THE PICTURES:\n" + pictures.system_text(kinds.family(kinds.of(channel)), most=60),
        "NAMING SUBJECTS (for `subjects`, every picture scene):\n" + pictures.SUBJECTS,
        "Every picture scene gets a subject. `changes` lists every change you make, all of them each time "
        "you hand in: the desk applies them to the script as edited, then counts what's still wrong.",
        ("WHAT THE CODE STILL FOUND LAST TIME (fix each):\n"
         + "\n".join(f"- scene {p['scene']}: {p['problem']}" for p in left)) if left else "",
        f"Tries so far: {row.get('tries', 0)} of {SUBMITS}.",
        pictures._brief(outline_, draft["scenes"])] if p)


def _brief_packaging(channel, row) -> str:
    from pipeline.documentary import pitch
    entry, data, nr = _film(channel, row)
    outline_, draft = nr["proof"]["outline"], nr["draft"]
    system, _ = pitch.prompt(channel, entry, angles=1)
    others = pitch.earlier_titles(channel.key, entry.get("id", ""))
    return "\n\n".join(p for p in [
        _channel_text(channel), _learnt(channel),
        "HOW A TITLE AND THUMBNAIL ARE WRITTEN:\n" + "\n\n".join(b.text for b in system),
        f"The plan entry's subject, which the title or thumbnail words must name: {entry.get('title', '')}",
        "THE PITCHED ANGLE:\n" + _pitch_text(nr.get("pitch") or {}),
        ("THE FACT CHECKER SAYS the pitched title or thumbnail words claim what the script doesn't; its "
         "suggestion: " + "; ".join(f"{k}: {v}" for k, v in nr["packaging_fix"].items()))
        if nr.get("packaging_fix") else "",
        ("The other films' titles (don't repeat their shape):\n" + "\n".join(f"- {t}" for t in others))
        if others else "",
        "THE FINISHED SCRIPT (the title and thumbnail must promise only what this delivers):\n"
        + _sheet(outline_, draft["scenes"], pictures=False),
        f"THE WRITER'S DESCRIPTION: {draft.get('description', '')}"] if p)


def _brief_final(channel, row) -> str:
    from pipeline.documentary import script
    entry, data, nr = _film(channel, row)
    outline_, draft = nr["proof"]["outline"], nr["draft"]
    pack = nr.get("packaging") or {}
    thumb = pack.get("thumbnail") or {}
    used = nr.get("rounds", {}).get("final", 0)
    return "\n\n".join(p for p in [
        _channel_text(channel), _learnt(channel),
        "THE VERDICTS SO FAR:\n" + _verdicts_text(nr),
        f"TITLE: {pack.get('title', '')}\nTHUMBNAIL: {thumb.get('subject', '')} / words \"{thumb.get('words', '')}\""
        f"\nDESCRIPTION: {pack.get('description', '')}",
        "THE PITCH:\n" + _pitch_text(nr.get("pitch") or {}),
        "THE OUTLINE:\n" + script.outline_text(outline_, _angle(nr)),
        "THE SCRIPT AS IT WILL BE VOICED AND DRAWN:\n" + _sheet(outline_, draft["scenes"]),
        f"Sending it back: {ROUNDS['final'] - used} time(s) left."] if p)


def _brief_overseer(channel, row) -> str:
    role = row["role"]
    sid = row["films"][0] if row["films"] else ""
    if role == "storyboard":
        return (f"FILM {channel.key}/{sid}: its storyboard is drawn. Follow 'Checkpoint 2: the storyboard' in "
                f"docs/overseer.md exactly, with its commands (python -m core.overseer board {channel.key} {sid}, "
                f"redraw, approve, note). Then hand in a one-line summary.")
    if role == "teasers":
        return (f"FILM {channel.key}/{sid}: its teasers are written. Follow 'Checkpoint 3: the teasers' in "
                f"docs/overseer.md exactly, with its commands. Then hand in a one-line summary.")
    return (f"The topic plan of {channel.key} is running low. Follow 'The topic bank' in docs/overseer.md "
            f"exactly, with its commands. Lean towards questions like the films that did best:\n\n"
            + _learnt(channel) + "\n\nThen hand in a one-line summary.")


_BRIEFS = {"pitch": _brief_pitch, "commission": _brief_commission, "proof": _brief_proof,
           "proof_review": _brief_proof_review, "draft": _brief_draft, "edit": _brief_edit, "facts": _brief_facts,
           "pictures": _brief_pictures, "packaging": _brief_packaging, "final": _brief_final,
           "storyboard": _brief_overseer, "teasers": _brief_overseer, "bank": _brief_overseer,
           "analysis": lambda channel, row: _brief_analysis(channel, row)}


# --- taking the work back -----------------------------------------------------------------

def _blank_newsroom() -> dict:
    return {"state": "", "rounds": {}, "log": [], "notes": []}


def _change(channel, sid: str, change) -> dict:
    entry = curriculum.find(channel.key, sid) or {}

    def apply(d):
        change(d, d.setdefault("newsroom", _blank_newsroom()))
    return production.update(channel.key, sid, apply, title=entry.get("title", ""))


def _logged(nr: dict, role: str, aid: str, verdict: str, reason: str = "", **extra) -> None:
    nr.setdefault("log", []).append({"at": _stamp(), "role": role, "assignment": aid, "verdict": verdict,
                                     **({"reason": reason} if reason else {}), **extra})


def _text(value) -> str:
    return " ".join(str(value or "").split())


def _notes(value) -> list:
    return [_text(n) for n in (value or []) if _text(n)] if isinstance(value, list) else \
        ([_text(value)] if _text(value) else [])


def _scores(value: dict, keys: tuple) -> tuple:
    """({key: 1-10}, problems)."""
    found, problems = {}, []
    for k in keys:
        try:
            found[k] = int((value or {}).get(k))
        except (TypeError, ValueError):
            problems.append(f"score `{k}` is missing or not a whole number")
            continue
        if not 1 <= found[k] <= 10:
            problems.append(f"score `{k}` must be 1 to 10")
    return found, problems


def _scrap(channel, sid: str, role: str, aid: str, reason: str) -> None:
    def change(d, nr):
        nr["state"] = "scrapped"
        _logged(nr, role, aid, "scrap", reason)
    _change(channel, sid, change)
    curriculum.skip(channel.key, sid, f"newsroom: {reason}")


def _take_pitch(channel, row, data) -> tuple:
    from pipeline.documentary import pitch as pitches
    given = {str(p.get("film")): p for p in data.get("pitches") or [] if isinstance(p, dict)}
    problems = []
    for sid in row["films"]:
        p = given.get(sid)
        if not p:
            problems.append(f"no pitch for film {sid}")
            continue
        entry = curriculum.find(channel.key, sid) or {}
        angle = p.get("angle") or {}
        thumb = angle.get("thumbnail") or {}
        for k in ("question", "answer", "why_care", "risks"):
            if not _text(p.get(k)):
                problems.append(f"{sid}: `{k}` is empty")
        for k in ("title", "promise", "hook", "open_loop"):
            if not _text(angle.get(k)):
                problems.append(f"{sid}: the angle's `{k}` is empty")
        beats = [b for b in p.get("beats") or [] if _text((b or {}).get("beat")) and _text((b or {}).get("reveal"))]
        if len(beats) < 5:
            problems.append(f"{sid}: {len(beats)} beats; a 9-minute film needs at least 5, each with its reveal")
        if not [d for d in p.get("demand") or [] if _text((d or {}).get("query")) and _text((d or {}).get("found"))]:
            problems.append(f"{sid}: no demand evidence; search with `python -m core.newsroom demand`")
        if len(_text(angle.get("hook")).split()) > 40:
            problems.append(f"{sid}: the hook is over 40 words")
        if len(_text(thumb.get("words")).split()) > pitches.THUMB_WORDS:
            problems.append(f"{sid}: thumbnail words are at most {pitches.THUMB_WORDS}")
        problems += [f"{sid}: the title {x}" for x in
                     pitches.title_problems(_text(angle.get("title")), _text(thumb.get("words")), entry.get("title", ""))]
    if problems:
        return problems, ""
    for sid in row["films"]:
        p = given[sid]

        def change(d, nr, p=p):
            nr["pitch"] = p
            nr["state"] = "pitched"
            nr["notes"] = []
            _logged(nr, "pitch", row["id"], "pitched")
        _change(channel, sid, change)
    return [], f"{len(row['films'])} pitched"


def _take_commission(channel, row, data) -> tuple:
    given = {str(v.get("film")): v for v in data.get("verdicts") or [] if isinstance(v, dict)}
    problems, plan = [], []
    for sid in row["films"]:
        v = given.get(sid)
        if not v:
            problems.append(f"no verdict for film {sid}")
            continue
        verdict, reason, notes = v.get("verdict"), _text(v.get("reason")), _notes(v.get("notes"))
        scores, bad = _scores(v.get("scores"), ("curiosity", "demand", "material", "pictures"))
        problems += [f"{sid}: {b}" for b in bad]
        nr = newsroom_of(production.load(channel.key, sid))
        if verdict not in ("commission", "rework", "scrap"):
            problems.append(f"{sid}: the verdict must be commission, rework or scrap")
        if not reason:
            problems.append(f"{sid}: give the reason")
        if verdict == "commission" and scores and min(scores.values()) < LOWEST_PASS:
            problems.append(f"{sid}: a score under {LOWEST_PASS} can't be commissioned: rework it or scrap it")
        if verdict == "rework" and nr.get("rounds", {}).get("pitch", 0) >= ROUNDS["pitch"]:
            problems.append(f"{sid}: it's had its rework; commission it or scrap it")
        if verdict == "rework" and not notes:
            problems.append(f"{sid}: say what the rework must change")
        plan.append((sid, verdict, reason, notes, scores))
    if problems:
        return problems, ""
    for sid, verdict, reason, notes, scores in plan:
        if verdict == "scrap":
            _scrap(channel, sid, "commission", row["id"], reason)
            continue

        def change(d, nr, verdict=verdict, reason=reason, notes=notes, scores=scores):
            if verdict == "rework":
                nr["rounds"]["pitch"] = nr["rounds"].get("pitch", 0) + 1
            nr["state"] = "commissioned" if verdict == "commission" else "rework_pitch"
            nr["notes"] = notes
            nr["scores"] = scores
            _logged(nr, "commission", row["id"], verdict, reason, scores=scores)
        _change(channel, sid, change)
    return [], ", ".join(f"{sid} {v}" for sid, v, *_ in plan)


def _rules(channel) -> dict:
    from pipeline.documentary import script
    return {"paintings": script._paintings(channel), "dialogue": bool(getattr(channel.documentary, "dialogue", False))}


def _short_chapters(channel, outline_: dict, scenes: list, numbers) -> list:
    from pipeline.documentary import script
    problems = []
    for n in numbers:
        said = sum(len(s["narration"].split()) for s in scenes if s["chapter"] == n)
        target = script.chapter_target(channel, outline_, n)[0]
        if said < script.SHORT_OF * target:
            problems.append(f"chapter {n} is {said} words; it needs about {target} (at least "
                            f"{round(script.SHORT_OF * target)}): more scenes and fuller narration, not padding")
    return problems


def _take_proof(channel, row, data) -> tuple:
    from pipeline.documentary import outline, script
    sid = row["films"][0]
    nr = newsroom_of(production.load(channel.key, sid))
    minutes = float(channel.documentary.minutes)
    try:
        made = outline.finish(channel, outline.clean(data.get("outline") or {}, minutes), _angle(nr))
    except (PipelineError, KeyError, TypeError, ValueError, AttributeError) as exc:
        return [f"the outline isn't in the outline shape ({exc})"], ""
    problems = outline.problems(made, minutes)
    raw = [dict(s, chapter=1) for s in data.get("scenes") or [] if isinstance(s, dict)]
    try:
        opening = script.clean({"scenes": raw, "description": ""}, made, **_rules(channel))["scenes"]
    except (PipelineError, KeyError, TypeError, ValueError) as exc:
        return problems + [f"chapter 1's scenes aren't in the scene shape ({exc})"], ""
    problems += _short_chapters(channel, made, opening, [1])
    if problems:
        return problems, ""

    def change(d, nr):
        nr["proof"] = {"outline": made, "scenes": opening, "answered": _text(data.get("answered"))}
        nr["state"] = "proofed"
        nr["notes"] = []
        _logged(nr, "proof", row["id"], "proofed")
    _change(channel, sid, change)
    return [], "proofed"


def _verdict(channel, row, data, role: str, allowed: tuple, keys: tuple, rounds: str) -> tuple:
    """(verdict, reason, notes, scores, problems) for a go-rework-scrap read."""
    sid = row["films"][0]
    nr = newsroom_of(production.load(channel.key, sid))
    verdict, reason, notes = data.get("verdict"), _text(data.get("reason")), _notes(data.get("notes"))
    problems = []
    if verdict not in allowed:
        problems.append("the verdict must be " + " or ".join(allowed))
    if not reason:
        problems.append("give the reason")
    if verdict == "rework" and nr.get("rounds", {}).get(rounds, 0) >= ROUNDS[rounds]:
        problems.append("it's had its reworks; pass it or scrap it")
    if verdict == "rework" and not notes:
        problems.append("say what the rework must change")
    return verdict, reason, notes, nr, problems


def _take_proof_review(channel, row, data) -> tuple:
    verdict, reason, notes, nr, problems = _verdict(channel, row, data, "proof_review", ("go", "rework", "scrap"),
                                                   (), "proof")
    scores, bad = _scores(data.get("scores"), ("opening", "momentum", "clarity", "material"))
    problems += bad
    if verdict == "go" and scores and min(scores.values()) < LOWEST_PASS:
        problems.append(f"a score under {LOWEST_PASS} can't go on: rework it or scrap it")
    if problems:
        return problems, ""
    sid = row["films"][0]
    if verdict == "scrap":
        _scrap(channel, sid, "proof_review", row["id"], reason)
        return [], "scrapped"

    def change(d, nr):
        if verdict == "rework":
            nr["rounds"]["proof"] = nr["rounds"].get("proof", 0) + 1
        nr["state"] = "drafting" if verdict == "go" else "rework_proof"
        nr["notes"] = notes
        _logged(nr, "proof_review", row["id"], verdict, reason, scores=scores)
    _change(channel, sid, change)
    return [], verdict


def _take_draft(channel, row, data) -> tuple:
    from pipeline.documentary import script
    sid = row["films"][0]
    nr = newsroom_of(production.load(channel.key, sid))
    outline_ = nr["proof"]["outline"]
    try:
        made = script.clean({"scenes": [s for s in data.get("scenes") or [] if isinstance(s, dict)],
                             "description": data.get("description") or ""}, outline_, **_rules(channel))
    except (PipelineError, KeyError, TypeError, ValueError) as exc:
        return [f"the scenes aren't in the scene shape ({exc})"], ""
    count = len(outline_["chapters"])
    problems = [f"chapter {n} has no scenes" for n in range(1, count + 1)
                if not any(s["chapter"] == n for s in made["scenes"])]
    problems += _short_chapters(channel, outline_, made["scenes"], range(1, count + 1))
    if not made["description"]:
        problems.append("the description is empty")
    if problems:
        return problems, ""

    def change(d, nr):
        nr["draft"] = {**made, "answered": _text(data.get("answered"))}
        nr["state"] = "drafted"
        nr["notes"] = []
        _logged(nr, "draft", row["id"], "drafted", words=script.words(made))
    _change(channel, sid, change)
    return [], f"drafted, {script.words(made)} words"


def _take_edit(channel, row, data) -> tuple:
    verdict, reason, notes, nr, problems = _verdict(channel, row, data, "edit", ("pass", "rework", "scrap"),
                                                   (), "draft")
    count = len(nr["proof"]["outline"]["chapters"])
    rated = {}
    for c in data.get("chapters") or []:
        scores, bad = _scores(c, ("momentum", "specificity", "voice", "clarity"))
        try:
            n = int(c.get("chapter"))
        except (TypeError, ValueError, AttributeError):
            continue
        problems += [f"chapter {n}: {b}" for b in bad]
        rated[n] = scores
    missing = [n for n in range(1, count + 1) if n not in rated]
    if missing:
        problems.append("score every chapter; missing: " + ", ".join(map(str, missing)))
    low = [n for n, s in rated.items() if s and min(s.values()) < LOWEST_PASS]
    if verdict == "pass" and low:
        problems.append(f"chapter(s) {', '.join(map(str, low))} score under {LOWEST_PASS}: edit them up, "
                        f"or send it back")
    scenes = [dict(s) for s in nr["draft"]["scenes"]]
    edits = []
    for e in data.get("edits") or []:
        try:
            i = int(e.get("scene"))
        except (TypeError, ValueError, AttributeError):
            problems.append("an edit without a scene number")
            continue
        line = _text(e.get("narration"))
        if not 0 <= i < len(scenes) or not line:
            problems.append(f"edit to scene {i}: no such scene, or an empty line")
            continue
        scenes[i]["narration"] = line
        edits.append({"scene": i, "why": _text(e.get("why"))})
    if problems:
        return problems, ""
    sid = row["films"][0]
    if verdict == "scrap":
        _scrap(channel, sid, "edit", row["id"], reason)
        return [], "scrapped"

    def change(d, nr):
        nr["draft"]["scenes"] = scenes
        nr.setdefault("edits", []).extend(edits)
        nr["review"] = {str(n): round(sum(s.values()) / len(s), 1) for n, s in rated.items() if s}
        if verdict == "rework":
            nr["rounds"]["draft"] = nr["rounds"].get("draft", 0) + 1
        nr["state"] = "edited" if verdict == "pass" else "rework_draft"
        nr["notes"] = notes
        _logged(nr, "edit", row["id"], verdict, reason, edits=len(edits), scores=nr["review"])
    _change(channel, sid, change)
    return [], f"{verdict}, {len(edits)} line(s) edited"


def _take_facts(channel, row, data) -> tuple:
    from pipeline.documentary import editor
    sid = row["films"][0]
    nr = newsroom_of(production.load(channel.key, sid))
    verdict, checked = data.get("verdict"), _notes(data.get("checked"))
    problems = []
    if verdict not in ("ok", "scrap"):
        problems.append("the verdict must be ok or scrap")
    if not checked:
        problems.append("list the central claims you checked, and where (`checked`)")
    if verdict == "scrap" and not _text(data.get("reason")):
        problems.append("give the reason for scrapping it")
    if problems:
        return problems, ""
    if verdict == "scrap":
        _scrap(channel, sid, "facts", row["id"], _text(data.get("reason")))
        return [], "scrapped"
    fixed, facts = editor.apply_facts(nr["draft"], data.get("facts") or {}, _angle(nr))
    retitle = fixed.pop("packaging_fix", None)
    fixed, cards = editor.apply_cards(fixed, data.get("cards") or {})

    def change(d, nr):
        nr["draft"] = fixed
        nr["facts"], nr["cards"], nr["checked"] = facts, cards, checked
        if retitle:
            nr["packaging_fix"] = retitle
        nr["state"] = "checked"
        _logged(nr, "facts", row["id"], "ok", fixes=len(facts), cards=len(cards))
    _change(channel, sid, change)
    return [], f"{len(facts)} fact fix(es), {len(cards)} card fix(es)"


def _take_pictures(channel, row, data) -> tuple:
    from pipeline.documentary import kinds, pictures
    sid = row["films"][0]
    nr = newsroom_of(production.load(channel.key, sid))
    outline_ = nr["proof"]["outline"]
    scenes = [dict(s) for s in nr["draft"]["scenes"]]
    changes = [c for c in data.get("changes") or [] if isinstance(c, dict)]
    notes = pictures._apply(outline_, scenes, {"changes": changes})
    scenes = pictures.validate(outline_, scenes)
    subjects = {}
    for r in data.get("subjects") or []:
        try:
            subjects[int(r.get("scene"))] = _text(r.get("subject"))
        except (TypeError, ValueError, AttributeError):
            continue
    unnamed = [i for i, s in enumerate(scenes) if s.get("medium", "picture") != "card"
               and not isinstance(s.get("same_as"), int) and not subjects.get(i)]
    if unnamed and row.get("tries", 0) < SUBMITS:
        return [f"name the main subject of every picture; missing: {', '.join(map(str, unnamed[:20]))}"], ""
    kind = kinds.family(kinds.of(channel))
    groups = pictures.grouped(outline_, scenes, subjects)
    left = pictures.problems(outline_, scenes, groups, kind)
    if left and row.get("tries", 0) < SUBMITS:
        row["left"] = left
        return [f"scene {p['scene']}: {p['problem']}" for p in left], ""

    def change(d, nr):
        nr["draft"]["scenes"] = scenes
        nr["pictures"] = {"planned": True, "changes": notes, "unfixed": left,
                          "looks": [g for g in groups if len(g["scenes"]) > 1],
                          "shown_again": sum(1 for s in scenes if isinstance(s.get("same_as"), int))}
        nr["state"] = "pictured"
        _logged(nr, "pictures", row["id"], "planned", changes=len(notes), unfixed=len(left))
    _change(channel, sid, change)
    return [], f"{len(notes)} picture change(s)" + (f", {len(left)} left unfixed" if left else "")


def _take_packaging(channel, row, data) -> tuple:
    from pipeline.documentary import pitch
    sid = row["films"][0]
    entry = curriculum.find(channel.key, sid) or {}
    title, thumb = _text(data.get("title")), data.get("thumbnail") or {}
    words = _text(thumb.get("words"))
    problems = [f"the title {p}" for p in pitch.title_problems(title, words, entry.get("title", ""))]
    if not title:
        problems.append("the title is empty")
    if not _text(thumb.get("subject")):
        problems.append("say what the thumbnail shows (`thumbnail.subject`)")
    if len(words.split()) > pitch.THUMB_WORDS:
        problems.append(f"thumbnail words are at most {pitch.THUMB_WORDS}")
    if not _text(data.get("description")):
        problems.append("the description is empty")
    if problems:
        return problems, ""

    def change(d, nr):
        nr["packaging"] = {"title": title, "thumbnail": {"subject": _text(thumb.get("subject")), "words": words},
                           "description": str(data.get("description")).strip(), "why": _text(data.get("why"))}
        nr["state"] = "packaged"
        _logged(nr, "packaging", row["id"], "packaged", title=title)
    _change(channel, sid, change)
    return [], f"packaged: {title}"


BACK = {"draft": "rework_draft", "edit": "drafted", "pictures": "checked", "packaging": "pictured"}


def _take_final(channel, row, data) -> tuple:
    verdict, notes, summary = data.get("verdict"), _notes(data.get("notes")), _text(data.get("summary"))
    sid = row["films"][0]
    nr = newsroom_of(production.load(channel.key, sid))
    problems = []
    if verdict not in ("pass", "back", "scrap"):
        problems.append("the verdict must be pass, back or scrap")
    if not summary:
        problems.append("write the summary for the owner")
    if verdict == "back":
        if data.get("back_to") not in BACK:
            problems.append("`back_to` must be draft, edit, pictures or packaging")
        if not notes:
            problems.append("say what must change")
        if nr.get("rounds", {}).get("final", 0) >= ROUNDS["final"]:
            problems.append("it's been sent back once already; pass it or scrap it")
    if problems:
        return problems, ""
    if verdict == "scrap":
        _scrap(channel, sid, "final", row["id"], summary)
        return [], "scrapped"
    if verdict == "back":
        def change(d, nr):
            nr["rounds"]["final"] = nr["rounds"].get("final", 0) + 1
            if data["back_to"] == "draft":
                nr["rounds"]["draft"] = min(nr["rounds"].get("draft", 0), ROUNDS["draft"] - 1)
            nr["state"] = BACK[data["back_to"]]
            nr["notes"] = notes
            _logged(nr, "final", row["id"], f"back to {data['back_to']}", summary)
        _change(channel, sid, change)
        return [], f"sent back to {data['back_to']}"
    commit(channel, sid, row["id"], summary)
    return [], "passed: it goes to the storyboard"


def commit(channel, sid: str, aid: str = "", summary: str = "") -> None:
    """A passed film made the production's: its angle, outline and script
    approved by the newsroom, so the autopilot draws it next."""
    from pipeline.documentary import cast, pitch

    def change(d, nr):
        pack = nr["packaging"]
        angle = {**_angle(nr), "title": pack["title"], "thumbnail": pack["thumbnail"], "why": pack.get("why", ""),
                 "scores": {k: nr.get("scores", {}).get(k, 7) for k in ("curiosity", "familiarity", "clarity", "payoff")},
                 "problems": []}
        angle["score"] = pitch.score(angle)
        outline_ = dict(nr["proof"]["outline"])
        outline_["title_options"] = [pack["title"]] + [t for t in outline_.get("title_options") or []
                                                       if t != pack["title"]][:2]
        draft = nr["draft"]
        script_ = {"scenes": draft["scenes"], "description": pack.get("description") or draft.get("description", ""),
                   "edits": nr.get("edits", []), "facts": nr.get("facts", []), "cards": nr.get("cards", []),
                   "restated": [], "ending": "", "review": nr.get("review", {}), "pictures": nr.get("pictures") or {},
                   "by": "newsroom"}
        for stage, content in (("pitch", {"angles": [angle], "chosen": 0, "by": "newsroom"}),
                               ("outline", outline_), ("script", script_)):
            production.made(d, stage, content)
            production.mark(d, stage, "approved")
            d["history"].append({"at": production._now(), "stage": stage, "did": "approved", "by": "newsroom"})
        nr["state"] = "passed"
        nr["notes"] = []
        _logged(nr, "final", aid, "pass", summary)
    data = _change(channel, sid, change)
    cast.merge(channel.key, sid, data["outline"].get("cast") or [])


def _take_summary(channel, row, data) -> tuple:
    summary = _text(data.get("summary"))
    if not summary:
        return ["write the summary"], ""
    if row["films"]:
        def change(d, nr):
            _logged(nr, row["role"], row["id"], "done", summary)
        _change(channel, row["films"][0], change)
    return [], summary


_TAKE = {"pitch": _take_pitch, "commission": _take_commission, "proof": _take_proof,
         "proof_review": _take_proof_review, "draft": _take_draft, "edit": _take_edit, "facts": _take_facts,
         "pictures": _take_pictures, "packaging": _take_packaging, "final": _take_final,
         "storyboard": _take_summary, "teasers": _take_summary, "bank": _take_summary,
         "analysis": lambda channel, row, data: _take_analysis(channel, row, data)}


def submit(key: str, aid: str, now: float = None) -> tuple:
    """(accepted, [problems], what happened) for an assignment's work as
    its role handed it in."""
    now = now or _now()
    ledger = load_ledger(key)
    row = ledger["open"].get(aid)
    if row is None:
        return False, [f"there's no open assignment {aid} (handed in already, or given up after {STALE_HOURS} hours)"], ""
    row["tries"] = row.get("tries", 0) + 1
    path = work_dir(key) / f"{aid}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        save_ledger(key, ledger)
        return False, [f"couldn't read {path} as JSON ({exc})"], ""
    channel = _channel(key)
    problems, what = _TAKE[row["role"]](channel, row, data)
    if problems:
        if row["tries"] >= SUBMITS:
            ledger["done"].append({**ledger["open"].pop(aid), "verdict": "rejected", "done_at": now,
                                   "problems": problems[:10]})
            save_ledger(key, ledger)
            return False, problems, f"rejected after {SUBMITS} tries; the work is due again next session"
        save_ledger(key, ledger)
        return False, problems, f"try {row['tries']} of {SUBMITS}"
    ledger["done"].append({**ledger["open"].pop(aid), "verdict": what, "done_at": now})
    save_ledger(key, ledger)
    log.info(f"{key}: newsroom {row['role']} {', '.join(row['films'])}: {what}")
    return True, [], what


# --- what the YouTube search shows --------------------------------------------------------

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


def _age(published: str, now: float) -> str:
    try:
        then = datetime.fromisoformat(published.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return "?"
    days = (now - then) / 86400
    return f"{days:.0f} days" if days < 60 else (f"{days / 30:.0f} months" if days < 730 else f"{days / 365:.0f} years")


def demand(key: str, query: str, now: float = None) -> str:
    """The long-form videos YouTube shows for `query`: views, age, the
    channel's subscribers and views per subscriber (a video far above its
    channel's size is a topic people want). 101 quota units a search."""
    import requests
    from core import youtube
    now = now or _now()
    ledger = load_ledger(key)
    today = [d for d in ledger["demand"] if now - d["at"] < 86400]
    if len(today) >= DEMAND_PER_DAY:
        return f"No searches left today ({DEMAND_PER_DAY} a day). Judge from what you have."
    headers = {"Authorization": f"Bearer {youtube.access_token(key)}"}
    found = requests.get(SEARCH_URL, headers=headers, timeout=20, params={
        "part": "snippet", "q": query, "type": "video", "maxResults": 15, "relevanceLanguage": "en",
        "videoDuration": "medium", "safeSearch": "none"})
    ledger["demand"] = [d for d in ledger["demand"] if now - d["at"] < 7 * 86400] + [{"at": now, "query": query}]
    save_ledger(key, ledger)
    if not found.ok:
        raise PipelineError(f"search {found.status_code}: {found.text[:200]}",
                            user_message=f"The YouTube search failed ({found.status_code}).")
    ids = [i["id"]["videoId"] for i in found.json().get("items") or [] if i.get("id", {}).get("videoId")]
    if not ids:
        return f'No long-form videos found for "{query}".'
    videos = requests.get(VIDEOS_URL, headers=headers, timeout=20,
                          params={"part": "snippet,statistics", "id": ",".join(ids)}).json().get("items") or []
    owners = {v["snippet"]["channelId"] for v in videos}
    subs = {c["id"]: int(c.get("statistics", {}).get("subscriberCount") or 0) for c in requests.get(
        CHANNELS_URL, headers=headers, timeout=20,
        params={"part": "statistics", "id": ",".join(owners)}).json().get("items") or []}
    rows = []
    for v in videos:
        views = int(v.get("statistics", {}).get("viewCount") or 0)
        owner = v["snippet"]["channelId"]
        ratio = f"{views / subs[owner]:.1f}x its subscribers" if subs.get(owner) else "subscribers hidden"
        rows.append((views, f"{views:>12,} views | {_age(v['snippet'].get('publishedAt'), now):>9} | "
                            f"{v['snippet'].get('channelTitle', '')} ({subs.get(owner, 0):,} subs; {ratio}) | "
                            f"{v['snippet'].get('title', '')}"))
    return f'YouTube, 4-20 minute videos for "{query}":\n' + "\n".join(r for _, r in sorted(rows, reverse=True))


# --- the analyst: what the published films teach each role --------------------------------
#
# The owner, 21 Oct: "is there a retrospective agent that looks at previous
# videos, click-through and retention etc and feeds this back to the agents
# responsible for these things eg script and thumbnails etc?" Each film's
# own lessons (core.lessons) are two generic lines from one curve; the
# analyst reads across every film once a week, with the tests' figures, and
# says what it means for each role's own work, with how sure it is.

ANALYSIS_EVERY_DAYS = 6
ANALYSIS_AFTER_DAYS = 7         # a film's first week, before it's worth reading
FINDINGS_PER_ROLE = 4
CONFIDENCE = ("strong", "suggestive", "hunch")
# Which findings each role is briefed with.
READS = {"pitch": "scout", "commission": "scout", "bank": "scout", "proof": "writer", "draft": "writer",
         "proof_review": "script_editor", "edit": "script_editor", "final": "script_editor",
         "packaging": "packaging", "pictures": "pictures", "storyboard": "pictures"}
FINDING_ROLES = ("scout", "writer", "script_editor", "packaging", "pictures")


def _findings_path(key: str):
    return CHANNELS_DIR / key / "newsroom_findings.json"


def load_findings(key: str) -> dict:
    try:
        data = json.loads(_findings_path(key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("latest", {})
    data.setdefault("from", [])
    data.setdefault("history", [])
    return data


def _published(channel, now: float = None) -> list:
    """[(production, video path, publish info, stats, days out)] for the
    channel's films that are out."""
    from core import gallery
    now = now or _now()
    out = []
    for data in production.all_for(channel.key):
        path = production.video_file(channel, data)
        if path is None or not path.exists():
            continue
        info = gallery.load_publish_info(path)
        if not gallery.is_out(info):
            continue
        try:
            days = (now - datetime.fromisoformat(info.get("published_at") or "").timestamp()) / 86400
        except (TypeError, ValueError):
            days = 0
        out.append((data, path, info, gallery.load_stats(path) or {}, days))
    return out


def analysis_due(channel, now: float = None) -> bool:
    """A film has had its first week since the last analysis, and the last
    is at least ANALYSIS_EVERY_DAYS old."""
    now = now or _now()
    found = load_findings(channel.key)
    ready = [p.stem for _, p, _, _, days in _published(channel, now) if days >= ANALYSIS_AFTER_DAYS]
    last = found["latest"].get("at_ts", 0)
    return bool(set(ready) - set(found["from"])) and now - last >= ANALYSIS_EVERY_DAYS * 86400


def _tests_text(key: str) -> str:
    """The thumbnail and title tests' figures, round by round."""
    from core import thumbnail_tests as tt
    lines = []
    for r in tt.load(key)["rounds"]:
        if r.get("kind") != "film":
            continue
        result = r.get("result") or {}
        changes = {v["label"]: v.get("change") or "the channel's current look" for v in r["variants"]}
        lines.append(f"- {r.get('phase', '')} round {r['id']} ({r['status']}): thumbnails "
                     + "; ".join(f"{l} = {c}" for l, c in changes.items()))
        for label, c in sorted((result.get("tally") or {}).items()):
            if c.get("impressions"):
                lines.append(f"    thumbnail {label}: {c['impressions']} impressions, {100 * (c.get('ctr') or 0):.1f}%")
        for label, c in sorted((result.get("title_tally") or {}).items()):
            if c.get("impressions"):
                lines.append(f"    title {label}: {c['impressions']} impressions, {100 * (c.get('ctr') or 0):.1f}%")
        for v in r["videos"]:
            if v.get("titles"):
                lines.append(f"    {v['stem']}: titles A \"{v.get('title_a', '')}\" / " + " / ".join(
                    f"{l} \"{t}\"" for l, t in sorted(v["titles"].items())))
        for k in ("verdict", "winner", "title_verdict", "title_winner"):
            if result.get(k):
                lines.append(f"    {k}: {result[k]}")
    return "\n".join(lines) or "No test has figures yet."


def _brief_analysis(channel, row) -> str:
    from core import reach, retention
    from core.audience import video_id
    found = load_findings(channel.key)
    films = []
    for data, path, info, stats, days in _published(channel):
        scenes = (data.get("script") or {}).get("scenes") or []
        outline_ = data.get("outline") or {}
        vid = video_id(info.get("youtube_url") or "")
        reach_days = reach.days(channel.key, vid) if vid else {}
        shown = sum(d[0] for d in reach_days.values())
        clicks = sum(d[0] * (d[1] / 100 if d[1] > 1 else d[1]) for d in reach_days.values())
        curve = retention.for_video(path)
        pack = production.packaging(data)
        lines = [f"FILM {data['subtopic_id']} ({days:.0f} days out; "
                 f"{'made by the newsroom' if (data.get('script') or {}).get('by') == 'newsroom' else 'made the old way'})",
                 f"  Title: {info.get('title') or pack.get('title', '')} | thumbnail words "
                 f"\"{(pack.get('thumbnail') or {}).get('words', '')}\"",
                 f"  Views {stats.get('views', '?')}, likes {stats.get('likes', '?')}, comments {stats.get('comments', '?')}; "
                 f"impressions {shown}, click-through {100 * clicks / shown:.1f}%" if shown else
                 f"  Views {stats.get('views', '?')}; no impressions figures yet",
                 f"  Average viewed {stats.get('avg_view_percent', '?')}% ({stats.get('avg_view_seconds', '?')} s); "
                 f"kept at 30 s {curve.get('kept_30s', '?')}%; at the end {curve.get('end', '?')}%",
                 "  Chapters: " + "; ".join(c.get("title", "") for c in outline_.get("chapters") or []),
                 "  Opening: " + " ".join(s["narration"] for s in scenes[:3])]
        for drop in curve.get("drops") or []:
            s = scenes[drop["scene"]] if drop["scene"] < len(scenes) else {}
            lines.append(f"  Lost {drop['lost']:.0f}% at {drop['at']} s during scene {drop['scene']}: said "
                         f"\"{s.get('narration', '')}\"; showed {s.get('medium', 'picture')}: {s.get('direction', '')[:140]}")
        log_ = newsroom_of(data).get("log") or []
        if log_:
            lines.append("  The newsroom's verdicts: " + "; ".join(
                f"{r['role']} {r['verdict']}" + (f" {r['scores']}" if r.get("scores") else "") for r in log_))
        films.append("\n".join(lines))
    previous = found["latest"]
    return "\n\n".join(p for p in [
        _channel_text(channel),
        "BENCHMARKS (typical, from large studies; a channel's own history matters more once it has one): "
        "long-form videos average about 30% viewed; 60-70% still watching at 30 seconds is good; click-through "
        "for channels under 1,000 subscribers is usually 2-4%, about 4.5% for education.",
        "THE PUBLISHED FILMS:\n" + ("\n\n".join(films) or "None yet."),
        "THE THUMBNAIL AND TITLE TESTS:\n" + _tests_text(channel.key),
        ("YOUR LAST FINDINGS (" + previous.get("at", "") + "), to confirm, revise or drop:\n"
         + "\n".join(f"- {role}: {f['text']} ({f['confidence']})" for role in FINDING_ROLES
                     for f in previous.get(role) or [])) if previous else "",
        "Which role reads what: `scout` (topics and pitches), `writer` (openings, structure, lines), "
        "`script_editor` (what to judge drafts by), `packaging` (titles and thumbnails), `pictures`."] if p)


def _take_analysis(channel, row, data) -> tuple:
    problems, kept = [], {}
    given = data.get("findings") or {}
    for role in FINDING_ROLES:
        rows = []
        for f in given.get(role) or []:
            text, evidence, sure = _text((f or {}).get("text")), _text((f or {}).get("evidence")), (f or {}).get("confidence")
            if not text or not evidence:
                problems.append(f"{role}: every finding needs its text and its evidence (films and figures)")
                continue
            if sure not in CONFIDENCE:
                problems.append(f"{role}: confidence must be strong, suggestive or hunch")
                continue
            rows.append({"text": text, "evidence": evidence, "confidence": sure})
        if len(rows) > FINDINGS_PER_ROLE:
            problems.append(f"{role}: at most {FINDINGS_PER_ROLE} findings; keep the ones that matter most")
        kept[role] = rows
    if not any(kept.values()):
        problems.append("no findings: if the figures are too thin to say anything, say that as a hunch, with them")
    if problems:
        return problems, ""
    store = load_findings(channel.key)
    stems = [p.stem for _, p, _, _, days in _published(channel) if days >= ANALYSIS_AFTER_DAYS]
    if store["latest"]:
        store["history"] = (store["history"] + [store["latest"]])[-12:]
    store["latest"] = {"at": _stamp(), "at_ts": _now(), "summary": _text(data.get("summary")), **kept}
    store["from"] = sorted(set(store["from"]) | set(stems))
    path = _findings_path(channel.key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=1, ensure_ascii=False), encoding="utf-8")
    return [], f"{sum(len(v) for v in kept.values())} finding(s)"


def findings_text(key: str, role: str) -> str:
    """The analyst's latest findings for the role doing `role`'s work."""
    reader = READS.get(role)
    latest = load_findings(key)["latest"]
    rows = latest.get(reader) or [] if reader else []
    if not rows:
        return ""
    return (f"WHAT THE ANALYST FOUND IN THE PUBLISHED FILMS ({latest.get('at', '')[:10]}), for your work. "
            "Act on the strong ones; weigh the rest:\n"
            + "\n".join(f"- [{f['confidence']}] {f['text']} (evidence: {f['evidence']})" for f in rows))


# --- the command line ---------------------------------------------------------------------

def status_text(key: str, now: float = None) -> str:
    now = now or _now()
    channel = _channel(key)
    ledger = load_ledger(key)
    lines = [f"NEWSROOM {key}: {'on' if getattr(channel.documentary, 'newsroom', False) else 'OFF'}",
             f"Points: {points_used(ledger, 7 * 24, now)} of {WEEK_POINTS} this week, "
             f"{points_used(ledger, SESSION_HOURS, now)} of {SESSION_POINTS} this session; "
             f"{tokens_used(ledger, 7 * 24, now):,} subscription tokens this week."]
    for _, d in _films(channel):
        nr = newsroom_of(d)
        last = (nr.get("log") or [{}])[-1]
        lines.append(f"  {d['subtopic_id']} {d.get('title', '')[:50]}: {nr.get('state') or 'new'}"
                     + (f" (last: {last.get('role')} {last.get('verdict')})" if last else ""))
    for row in ledger["open"].values():
        lines.append(f"  open: {row['id']} ({row['agent']}, tries {row.get('tries', 0)})")
    lines += [f"  due: {a['role']} {' '.join(a['films'])}" for a in due(channel, ledger)]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.newsroom")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "next", "performance"):
        sub.add_parser(name).add_argument("channel")
    for name in ("brief", "submit"):
        p = sub.add_parser(name)
        p.add_argument("channel")
        p.add_argument("assignment")
    p = sub.add_parser("demand")
    p.add_argument("channel")
    p.add_argument("query")
    p = sub.add_parser("spent")
    p.add_argument("channel")
    p.add_argument("assignment")
    p.add_argument("tokens", type=int)
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        if args.command == "status":
            print(status_text(args.channel))
        elif args.command == "performance":
            print(performance(_channel(args.channel)))
        elif args.command == "next":
            channel = _channel(args.channel)
            if not getattr(channel.documentary, "newsroom", False):
                print("NOTHING: the newsroom is off for this channel")
                return 0
            row, why = next_assignment(channel)
            if row is None:
                print(f"NOTHING: {why}")
            else:
                print(f"ASSIGNMENT {row['id']} AGENT {row['agent']} ROLE {row['role']} "
                      f"FILMS {' '.join(row['films']) or '-'}")
        elif args.command == "brief":
            print(brief(args.channel, args.assignment))
        elif args.command == "submit":
            ok, problems, what = submit(args.channel, args.assignment)
            if ok:
                print(f"ACCEPTED: {what}")
            else:
                print("NOT ACCEPTED" + (f" ({what})" if what else "") + ". Fix these and submit again:\n"
                      + "\n".join(f"- {p}" for p in problems))
                return 1
        elif args.command == "demand":
            print(demand(args.channel, args.query))
        elif args.command == "spent":
            print("recorded" if spent(args.channel, args.assignment, args.tokens) else "no such assignment")
    except PipelineError as exc:
        print(f"ERROR: {exc.user_message}")
        return 2
    return 0


if __name__ == "__main__":
    from core.logging_setup import configure
    configure()
    raise SystemExit(main())
