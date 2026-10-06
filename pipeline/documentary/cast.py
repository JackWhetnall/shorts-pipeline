"""
A documentary channel's cast library: every person, place and thing its
videos have shown, with the description it's drawn from (decision 074).

Consistency across videos comes from two references every picture is
drawn with: the channel's style sheet (pipeline.animation.bible), which
fixes the hand, and the model sheet of each recurring member, which
fixes who they are. A member keeps one name and one description for
the channel's life: the outline writer is shown the library and told to
reuse them word for word, and a member whose look really changes (young
Washington the surveyor, old Washington the president) is a separate
member with its own name. Sheets are drawn once per member and look, on
first use, and kept in the look's bible folder.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from core.logging_setup import get_logger
from core.paths import CHANNELS_DIR, slugify

log = get_logger(__name__)

KINDS = ("character", "place", "object")
SHOWN = 80                  # members listed to the outline writer, most recent first

_lock = threading.Lock()


def _path(channel_key: str) -> Path:
    return CHANNELS_DIR / channel_key / "cast_library.json"


def load(channel_key: str) -> list:
    try:
        return json.loads(_path(channel_key).read_text(encoding="utf-8")).get("members") or []
    except (OSError, ValueError):
        return []


def _save(channel_key: str, members: list) -> None:
    path = _path(channel_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"members": members}, indent=1, ensure_ascii=False), encoding="utf-8")


def key_of(name: str) -> str:
    return slugify(name, "member")


def find(channel_key: str, name: str) -> dict:
    wanted = key_of(name)
    return next((m for m in load(channel_key) if key_of(m["name"]) == wanted), None)


def for_prompt(channel_key: str) -> str:
    members = load(channel_key)[-SHOWN:]
    if not members:
        return ""
    return "\n".join(f"- {m['name']} ({m['kind']}): {m['description']}" for m in reversed(members))


def merge(channel_key: str, subtopic_id: str, cast: list) -> list:
    """Add an approved outline's cast to the library. A member already
    there keeps its description (that's what its sheet was drawn from);
    a new one is added. Returns the cast as the library has it."""
    with _lock:
        members = load(channel_key)
        by_key = {key_of(m["name"]): m for m in members}
        out = []
        for c in cast:
            name = " ".join(str(c.get("name") or "").split())
            if not name:
                continue
            existing = by_key.get(key_of(name))
            if existing is None:
                existing = {"name": name, "kind": c.get("kind") if c.get("kind") in KINDS else "character",
                            "description": " ".join(str(c.get("description") or name).split()),
                            "videos": []}
                members.append(existing)
                by_key[key_of(name)] = existing
            if subtopic_id not in existing["videos"]:
                existing["videos"].append(subtopic_id)
            out.append(existing)
        _save(channel_key, members)
        return out


def sheet(channel, look: dict, member: dict, style_ref: Path) -> Path:
    """This member's reference picture in this look: a model sheet for a
    character, an establishing view of a place, an object on its own.
    Drawn on first need and kept for the channel's other videos."""
    from pipeline.animation import bible, models
    basis = hashlib.sha1(f"{member['kind']}|{member['name']}|{member['description']}|"
                         f"{look['identity']}".encode()).hexdigest()[:10]
    path = bible.folder(channel.key, look) / "library" / f"{member['kind']}_{key_of(member['name'])}_{basis}.png"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    log.info(f"  [documentary] drawing the {member['kind']} sheet for {member['name']}")
    return bible.element_sheet(member["kind"], member["name"], member["description"], look,
                               style_ref, path, models.image_model(models.BIBLE_IMAGE_MODEL))
