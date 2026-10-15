"""
A long-form video's production, stage by stage (decisions 074, 086).

A documentary channel's video isn't made in one go. It's planned in
stages, and each stage waits for the owner's approval (or the channel's
autopilot, decision 086) before the next is started:

0. **pitch** (shown as "Angle"): how the film wins the click and the
   first minute, decided before a word is written: several angles, each
   a title, a thumbnail idea, the promise and the first line, scored, one
   chosen. Everything after keeps that promise.
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
from core.logging_setup import get_logger
from core.paths import CHANNELS_DIR, safe_join, write_atomically

STAGES = ("pitch", "outline", "script", "stills", "video", "teasers")
LABELS = {"pitch": "Angle", "outline": "Outline", "script": "Script", "stills": "Storyboard", "video": "Video",
          "teasers": "Teasers"}
STATES = ("todo", "working", "ready", "approved", "failed", "stale")

_lock = threading.Lock()


log = get_logger(__name__)


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
            "pitch": None, "outline": None, "script": None, "stills": {}, "video": None, "teasers": None,
            "history": []}


def exists(channel_key: str, subtopic_id: str) -> bool:
    return _path(channel_key, subtopic_id).exists()


def load(channel_key: str, subtopic_id: str, title: str = "") -> dict:
    """The production for a plan entry, or a blank one."""
    path = _path(channel_key, subtopic_id)
    if not path.exists():
        return blank(subtopic_id, title)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # Never a blank in its place: the next save would write over the
        # film, and the autopilot would pay to make it again (decision 097).
        raise ProductionError(f"{path} unreadable: {exc}", user_message=(
            f"This film's record ({subtopic_id}) can't be read; it's been left as it is.")) from exc
    for stage in STAGES:
        data["stages"].setdefault(stage, {"state": "todo"})
    data.setdefault("pitch", None)
    # A film started before the angle stage existed (decision 086) carries
    # on as it was: its outline stood in for the angle.
    if data["stages"]["pitch"]["state"] == "todo" and data.get("outline"):
        data["stages"]["pitch"] = {"state": "approved", "legacy": True}
    return data


def save(channel_key: str, data: dict) -> None:
    write_atomically(_path(channel_key, data["subtopic_id"]), json.dumps(data, indent=1, ensure_ascii=False))


def all_for(channel_key: str) -> list:
    """Every production this channel has, by plan entry id."""
    root = CHANNELS_DIR / channel_key / "productions"
    if not root.exists():
        return []
    films = []
    for d in sorted(root.iterdir()):
        if (d / "production.json").exists():
            try:
                films.append(load(channel_key, d.name))
            except ProductionError as exc:
                log.error(f"{channel_key}: skipping a film whose record can't be read ({exc})")
    return films


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


INTERRUPTED = "Stopped part-way: the app or the PC restarted."


def recover_interrupted(channel_keys) -> list:
    """At startup, nothing is being made yet, so a stage still marked
    working was cut short by a restart (decision 097). It becomes failed,
    flagged `interrupted`, so the autopilot starts it again (without
    counting that as its one retry) and the owner sees why. What it had
    already paid for is kept: drawn pictures, voiced lines and finished
    batches are picked up again. Returns [(channel, film, stage)]."""
    found = []
    for key in channel_keys:
        for data in all_for(key):
            stuck = [s for s in STAGES if state(data, s) == "working"]
            if not stuck:
                continue

            def change(d, stuck=stuck):
                for s in stuck:
                    mark(d, s, "failed", INTERRUPTED)
                    d["stages"][s]["interrupted"] = True
                    d["history"].append({"at": _now(), "stage": s, "did": "interrupted by a restart"})
            update(key, data["subtopic_id"], change)
            found += [(key, data["subtopic_id"], s) for s in stuck]
    return found


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


def approve(channel_key: str, subtopic_id: str, stage: str, choice: int = None, by: str = "you") -> dict:
    """Approve a ready stage. `choice`: for the angle, which one (else the
    one the pitch chose). `by`: "you", or "autopilot" (decision 086)."""
    def change(data):
        if state(data, stage) not in ("ready", "approved"):
            raise ProductionError(f"{stage} is {state(data, stage)}",
                                  user_message=f"The {LABELS[stage].lower()} isn't ready to approve.")
        if not can_start(data, stage):
            raise ProductionError("earlier stage unapproved", user_message=(
                "Approve the stages before it first."))
        if stage == "pitch" and choice is not None and data.get("pitch"):
            angles = data["pitch"].get("angles") or []
            if 0 <= choice < len(angles) and choice != data["pitch"].get("chosen"):
                data["pitch"]["chosen"] = choice
                data["pitch"].pop("title_from", None)
                _stale_after(data, stage)
        mark(data, stage, "approved")
        data["history"].append({"at": _now(), "stage": stage, "did": "approved",
                                **({"by": by} if by != "you" else {})})
    return update(channel_key, subtopic_id, change)


def chosen_angle(data: dict) -> dict:
    """The angle the film keeps (its title, thumbnail idea, promise and
    first line), or {} for a film made before angles existed."""
    pitch = data.get("pitch") or {}
    angles = pitch.get("angles") or []
    index = pitch.get("chosen") or 0
    return angles[index] if 0 <= index < len(angles) else {}


def packaging(data: dict) -> dict:
    """The angle whose title and thumbnail words the film goes out with:
    the chosen one, or another picked for its title alone (decision 090),
    which changes nothing the film says."""
    pitch = data.get("pitch") or {}
    angles = pitch.get("angles") or []
    index = pitch.get("title_from")
    if isinstance(index, int) and 0 <= index < len(angles):
        return angles[index]
    return chosen_angle(data)


def retitle(channel_key: str, subtopic_id: str, index: int) -> dict:
    """Use angle `index`'s title and thumbnail words, keeping the film."""
    def change(data):
        angles = (data.get("pitch") or {}).get("angles") or []
        if not 0 <= index < len(angles):
            raise ProductionError("no such angle", user_message="That title isn't there any more.")
        data["pitch"]["title_from"] = index
        data["history"].append({"at": _now(), "stage": "pitch", "did": f"title from angle {index + 1}"})
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


# Characters of narration per word, spaces included: this project's
# narration averages about 5.8, rounded up so a reserve errs on the safe side.
CHARACTERS_PER_WORD = 6
# A production nobody has touched for this long isn't counted as in progress.
ACTIVE_DAYS = 14


def last_touched(data: dict) -> float:
    """When anything last happened to this production, as unix time (0 if never)."""
    stamps = [entry.get("at") for entry in data["stages"].values()]
    stamps += [h.get("at") for h in data.get("history") or []]
    latest = 0.0
    for stamp in stamps:
        try:
            latest = max(latest, datetime.fromisoformat(stamp).timestamp())
        except (TypeError, ValueError):
            continue
    return latest


def narration_still_to_voice(data: dict) -> int:
    """Characters this production will still send to the voice (decision
    075): the film's narration until its video stage has been made, and
    its teasers' once they're written and waiting to be made.

    Exact from the script when there is one; estimated from the approved
    outline's minutes when that's all there is. Nothing for an outline
    that isn't approved: one written ahead isn't a film anyone has started."""
    total = 0
    if state(data, "video") not in ("ready", "approved", "working"):
        scenes = (data.get("script") or {}).get("scenes") or []
        if scenes:
            total += sum(len(s.get("narration") or "") for s in scenes)
        elif state(data, "outline") == "approved":
            from pipeline.documentary.script import WORDS_PER_SECOND
            minutes = sum(float(c.get("minutes") or 0) for c in (data.get("outline") or {}).get("chapters") or [])
            total += round(minutes * 60 * WORDS_PER_SECOND * CHARACTERS_PER_WORD)
    if state(data, "teasers") == "ready":
        for teaser in (data.get("teasers") or {}).get("scripts") or []:
            total += sum(len(s.get("narration") or "") for s in teaser.get("scenes") or [])
    return total


def asset(channel_key: str, subtopic_id: str, name: str) -> Path:
    """A file of this production (a still, a teaser), by its stored name."""
    return safe_join(folder(channel_key, subtopic_id), name)


# --- one approval for a film's video (decision 104) ----------------------------------------

def film_of(video_path):
    """(channel key, film id) whose made video is `video_path`, or None.
    A film's video is reviewed in Review like any other, and on the film's
    own page: the two were separate approvals, and approving in Review
    alone left the film's video unapproved, so its teasers never came."""
    from core import gallery
    from core.channels import load_channels
    video_path = Path(video_path).resolve()
    key = gallery._channel_key_for(video_path)
    if key is None:
        return None
    channel = load_channels(validate=False).get(key)
    if channel is None or getattr(channel, "format", "documentary") != "documentary":
        return None             # only films have a production to follow
    root = gallery.resolve_output_dir(channel.output_dir)
    for data in all_for(key):
        made = (data.get("video") or {}).get("path")
        if made and (root / made).resolve() == video_path:
            return key, data["subtopic_id"]
    return None


def video_reviewed(video_path, approved: bool) -> None:
    """Review approved the video (or took it back out of the queue): the
    film's video stage follows, so the teasers start from either place."""
    found = film_of(video_path)
    if found is None:
        return
    key, sid = found

    def change(data):
        now = state(data, "video")
        if approved and now == "ready" and can_start(data, "video"):
            mark(data, "video", "approved")
            data["history"].append({"at": _now(), "stage": "video", "did": "approved in Review"})
        elif not approved and now == "approved" and current(data) == "teasers"                 and not (data.get("teasers") or {}).get("videos"):
            mark(data, "video", "ready")
            data["history"].append({"at": _now(), "stage": "video", "did": "taken back out of the queue"})
    update(key, sid, change)


def video_file(channel, data: dict):
    """The film's made video as a path, or None."""
    from core import gallery
    made = (data.get("video") or {}).get("path")
    return gallery.resolve_output_dir(channel.output_dir) / made if made else None
