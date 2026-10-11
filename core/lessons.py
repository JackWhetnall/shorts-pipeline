"""
What a channel's viewers have taught it (decision 086).

A short list of plain lessons ("viewers left during the backstory in
chapter 2: start where the title's promise is"), kept per channel in
channels/<key>/lessons.json and read by every writer of a documentary
(the angle, the outline, the script). Each film adds at most two, worked
out from where its viewers left and how often its thumbnail was clicked
(core.retention, `learn`), and the owner can edit or clear them. Kept
short on purpose: a writer told twenty things follows none of them.

Filed in the channel's own folder, so a rename carries it (decision 057).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from core.logging_setup import get_logger
from core.paths import CHANNELS_DIR, write_atomically

log = get_logger(__name__)

MAX_LESSONS = 8


def path_for(channel_key: str):
    return CHANNELS_DIR / channel_key / "lessons.json"


def _read(channel_key: str) -> dict:
    try:
        data = json.loads(path_for(channel_key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"lessons": [], "learned_from": []}
    data.setdefault("lessons", [])
    data.setdefault("learned_from", [])
    return data


def _write(channel_key: str, data: dict) -> None:
    path = path_for(channel_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomically(path, json.dumps(data, indent=1, ensure_ascii=False))


def load(channel_key: str) -> list:
    """[{"text", "from", "at"}], oldest first."""
    return _read(channel_key)["lessons"]


def texts(channel_key: str) -> list:
    return [lesson["text"] for lesson in load(channel_key) if lesson.get("text")]


def for_prompt(channel_key: str) -> str:
    """The lessons as a writer reads them, or "" when there are none."""
    found = texts(channel_key)
    if not found:
        return ""
    return ("What this channel's own viewers have shown (from where they stopped watching and what "
            "they clicked); follow these:\n" + "\n".join(f"- {t}" for t in found))


def add(channel_key: str, new: list, source: str = "") -> list:
    """Add lessons learned from `source` (a video's stem), keeping the
    newest MAX_LESSONS. Returns the list."""
    data = _read(channel_key)
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    have = {lesson["text"].strip().lower() for lesson in data["lessons"]}
    for text in new:
        text = " ".join(str(text or "").split())
        if text and text.lower() not in have:
            data["lessons"].append({"text": text, "from": source, "at": at})
            have.add(text.lower())
    data["lessons"] = data["lessons"][-MAX_LESSONS:]
    if source and source not in data["learned_from"]:
        data["learned_from"].append(source)
    _write(channel_key, data)
    return data["lessons"]


def replace(channel_key: str, new_texts: list) -> list:
    """The owner's own edit of the list, one lesson a line."""
    data = _read(channel_key)
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    old = {lesson["text"]: lesson for lesson in data["lessons"]}
    data["lessons"] = [old.get(t) or {"text": t, "from": "you", "at": at}
                       for t in (" ".join(x.split()) for x in new_texts) if t][-MAX_LESSONS:]
    _write(channel_key, data)
    return data["lessons"]


def learned_from(channel_key: str, stem: str) -> bool:
    return stem in _read(channel_key)["learned_from"]
