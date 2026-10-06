"""
A long-form video's production, stage by stage (decision 074).

A documentary channel's video isn't made in one go. It's planned in
stages, and each stage waits for the owner's approval before the next is
started:

1. **outline**: what the video says, chapter by chapter, and how each
   part is shown; who and what recurs in it.
2. **script**: the narration as a play, scene by scene, each with its
   stage direction (setting, who is there, what happens, the framing)
   and the words spoken over it.
3. **stills**: a drawn picture for every scene, in the channel's look,
   with its cast drawn from their model sheets: the storyboard.
4. **video**: voiced and cut to the stills, with camera moves, chapter
   titles and music, into review like any other video.
5. **teasers**: a few vertical shorts from it, written then made.

This module is the record only: what each stage holds and where it
stands. The work is pipeline.documentary's, run as jobs. Everything is
kept under channels/<key>/productions/<plan entry id>/, so it moves with
a renamed channel, with pictures named relative to that folder.

A stage's state is one of:
- todo: not started;
- working: a job is on it;
- ready: done and waiting for the owner;
- approved;
- failed: the job failed (`error` says why);
- stale: an earlier stage changed after this one was done, so it no
  longer follows from it. It's redone rather than trusted.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from core.errors import PipelineError
from core.paths import CHANNELS_DIR, safe_join

STAGES = ("outline", "script", "stills", "video", "teasers")
LABELS = {"outline": "Outline", "script": "Script", "stills": "Storyboard", "video": "Video",
          "teasers": "Teasers"}
STATES = ("todo", "working", "ready", "approved", "failed", "stale")

_lock = threading.Lock()


class ProductionError(PipelineError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def folder(channel_key: str, subtopic_id: str) -> Path:
    return safe_join(CHANNELS_DIR / channel_key / "productions", subtopic_id)


def _path(channel_key: str, subtopic_id: str) -> Path:
    return folder(channel_key, subtopic_id) / "production.json"


def blank(subtopic_id: str, title: str = "") -> dict:
    return {"subtopic_id": subtopic_id, "title": title, "created_at": _now(),
            "stages": {s: {"state": "todo"} for s in STAGES},
            "outline": None, "script": None, "stills": {}, "video": None, "teasers": None,
            "history": []}


def exists(channel_key: str, subtopic_id: str) -> bool:
    return _path(channel_key, subtopic_id).exists()


def load(channel_key: str, subtopic_id: str, title: str = "") -> dict:
    """The production for a plan entry, or a blank one."""
    path = _path(channel_key, subtopic_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return blank(subtopic_id, title)
    for stage in STAGES:
        data["stages"].setdefault(stage, {"state": "todo"})
    return data


def save(channel_key: str, data: dict) -> None:
    path = _path(channel_key, data["subtopic_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def all_for(channel_key: str) -> list:
    """Every production this channel has, by plan entry id."""
    root = CHANNELS_DIR / channel_key / "productions"
    if not root.exists():
        return []
    return [load(channel_key, d.name) for d in sorted(root.iterdir()) if (d / "production.json").exists()]


def state(data: dict, stage: str) -> str:
    return data["stages"][stage]["state"]


def current(data: dict) -> str:
    """The stage that needs something next: the first not approved."""
    return next((s for s in STAGES if state(data, s) != "approved"), None)


def can_start(data: dict, stage: str) -> bool:
    """A stage can be (re)made once every stage before it is approved."""
    before = STAGES[:STAGES.index(stage)]
    return all(state(data, s) == "approved" for s in before)


def update(channel_key: str, subtopic_id: str, change, title: str = "") -> dict:
    """Load, apply `change(data)`, save, under one lock. Returns the data."""
    with _lock:
        data = load(channel_key, subtopic_id, title)
        if title and not data.get("title"):
            data["title"] = title
        change(data)
        save(channel_key, data)
        return data


def mark(data: dict, stage: str, new_state: str, error: str = "") -> None:
    if new_state not in STATES:
        raise ValueError(new_state)
    entry = data["stages"][stage]
    entry.update(state=new_state, at=_now())
    if error:
        entry["error"] = error
    else:
        entry.pop("error", None)


def made(data: dict, stage: str, content=None) -> None:
    """A stage's work is done: its content stored, waiting for approval,
    and every later stage made stale (it followed from the old version)."""
    if content is not None:
        data[stage] = content
    mark(data, stage, "ready")
    _stale_after(data, stage)


def _stale_after(data: dict, stage: str) -> None:
    for later in STAGES[STAGES.index(stage) + 1:]:
        if state(data, later) not in ("todo",):
            mark(data, later, "stale")


def approve(channel_key: str, subtopic_id: str, stage: str) -> dict:
    def change(data):
        if state(data, stage) not in ("ready", "approved"):
            raise ProductionError(f"{stage} is {state(data, stage)}",
                                  user_message=f"The {LABELS[stage].lower()} isn't ready to approve.")
        if not can_start(data, stage):
            raise ProductionError("earlier stage unapproved", user_message=(
                "Approve the stages before it first."))
        mark(data, stage, "approved")
        data["history"].append({"at": _now(), "stage": stage, "did": "approved"})
    return update(channel_key, subtopic_id, change)


def edited(channel_key: str, subtopic_id: str, stage: str, content) -> dict:
    """The owner's own edit of a stage: stored and approved (they've looked
    at it), and what followed from the old version made stale."""
    def change(data):
        if state(data, stage) == "working":
            raise ProductionError("busy", user_message="That stage is being made right now.")
        data[stage] = content
        mark(data, stage, "approved")
        _stale_after(data, stage)
        data["history"].append({"at": _now(), "stage": stage, "did": "edited"})
    return update(channel_key, subtopic_id, change)


def asset(channel_key: str, subtopic_id: str, name: str) -> Path:
    """A file of this production (a still, a teaser), by its stored name."""
    return safe_join(folder(channel_key, subtopic_id), name)
