"""
Carrying a channel's data across a rename (decision 057).

A channel's key is the name its data is filed under, and the data is in
many places: its topic plan and question bank, its record of what it has
asked and said, its cost log, which facts and questions it has used, its
jobs, its YouTube connection. Renaming moved only its config entry, its
assets and its output folder, and the rest was left filed under the old
name: the renamed quiz channel showed no topics and no videos, and its
questions would have been asked again.

`migrate` moves all of it, and is safe to run again: a step with nothing
left to move does nothing, one that would overwrite something refuses and
says so rather than overwriting, and nothing is deleted that isn't first
moved. It returns the problems it met (an empty list when all went well),
never raising for one store so that the others still move.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path

from core.logging_setup import get_logger

log = get_logger(__name__)


def _replace_path(value, old_prefix: str, new_prefix: str):
    """A stored path with the old output folder swapped for the new, in
    either slash style."""
    if not isinstance(value, str):
        return value
    for sep in ("/", "\\"):
        o, n = old_prefix.replace("/", sep) + sep, new_prefix.replace("/", sep) + sep
        value = value.replace(o, n)
    return value


def _move(source: Path, target: Path, problems: list, what: str) -> bool:
    """Move a file or folder unless something is already at the target."""
    if not source.exists():
        return False
    if target.exists():
        problems.append(f"{what}: {target} already exists, so {source} was left where it is")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return True


def _write_json(path: Path, data) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def _rekey_json(path: Path, old: str, new: str, problems: list, what: str, fix=None) -> bool:
    """A JSON file whose top level is keyed by channel: `old`'s entry
    moves to `new` (joined to what's there, if anything), `fix` applied to
    it on the way."""
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.append(f"{what}: couldn't be read ({exc})")
        return False
    if not isinstance(data, dict) or old not in data:
        return False
    entry = fix(data.pop(old)) if fix else data.pop(old)
    if new in data and data[new]:
        if isinstance(entry, list) and isinstance(data[new], list):
            entry = entry + data[new]
        elif isinstance(entry, dict) and isinstance(data[new], dict):
            entry = {**entry, **data[new]}
        else:
            problems.append(f"{what}: both names have entries; left under {old!r}")
            return False
    data[new] = entry
    _write_json(path, data)
    return True


def _rewrite_lines(path: Path, old: str, new: str, field: str = "channel") -> int:
    """A JSON-lines log with `old` as the channel on some lines: those lines
    changed, every other line kept exactly as it was."""
    if not path.exists():
        return 0
    changed, out = 0, []
    with path.open(encoding="utf-8", newline="") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                out.append(line)
                continue
            if isinstance(record, dict) and record.get(field) == old:
                record[field] = new
                ending = line[len(line.rstrip("\r\n")):]
                line = json.dumps(record, ensure_ascii=False) + ending
                changed += 1
            out.append(line)
    if changed:
        temp = path.with_name(path.name + ".tmp")
        temp.write_text("".join(out), encoding="utf-8", newline="")
        os.replace(temp, path)
    return changed


def migrate(old: str, new: str, output_moved: bool = True) -> list:
    """Move everything filed under channel key `old` to `new`. With
    `output_moved`, paths stored in that data to the channel's output
    folder are updated too. Returns the problems met."""
    from core import audience, costs, corpus, curriculum, gallery, publish_queue, youtube
    from core import paths
    from pipeline import quiz, similarity

    problems: list = []
    if old == new:
        return problems
    old_out, new_out = f"output/{old}", f"output/{new}"
    path_fix = (lambda v: _replace_path(v, old_out, new_out)) if output_moved else (lambda v: v)

    def attempt(what: str, step) -> None:
        try:
            result = step()
            if result:
                log.info(f"  [rename] {what}: moved to {new}" if result is True else
                         f"  [rename] {what}: {result} records moved to {new}")
        except Exception as exc:  # noqa: BLE001 - the other stores must still move
            log.exception(f"  [rename] {what} failed")
            problems.append(f"{what}: {exc}")

    # The topic plan: its file, and the name inside it (curriculum.save
    # writes to the file that name gives).
    def topic_plan() -> bool:
        source, target = curriculum.path_for(old), curriculum.path_for(new)
        if not _move(source, target, problems, "topic plan"):
            return False
        data = json.loads(target.read_text(encoding="utf-8"))
        data["channel"] = new
        _write_json(target, data)
        return True
    attempt("topic plan", topic_plan)

    attempt("question memory", lambda: _move(quiz._bank_path(old), quiz._bank_path(new), problems,
                                             "question memory"))
    attempt("source text", lambda: _move(corpus.CORPORA_DIR / f"{old}.txt", corpus.CORPORA_DIR / f"{new}.txt",
                                         problems, "source text"))
    attempt("YouTube connection", lambda: _move(youtube.TOKENS_DIR / f"{old}.json",
                                                youtube.TOKENS_DIR / f"{new}.json", problems,
                                                "YouTube connection"))
    from core import outlook
    attempt("outlook figures", lambda: _move(outlook._cache_path(old), outlook._cache_path(new), problems,
                                             "outlook figures"))

    def history_entry(entries):
        if not isinstance(entries, list):
            return entries
        return [{**e, **({"video": path_fix(e["video"])} if isinstance(e, dict) and "video" in e else {})}
                for e in entries]
    attempt("originality history", lambda: _rekey_json(similarity.SCRIPT_HISTORY_PATH, old, new, problems,
                                                       "originality history", history_entry))
    attempt("publishing state", lambda: _rekey_json(publish_queue.STATE_PATH, old, new, problems,
                                                    "publishing state"))
    attempt("schedule", lambda: _rekey_json(paths.SCHEDULE_PATH, old, new, problems, "schedule"))
    attempt("audience figures", lambda: _rekey_json(audience.STATUS_PATH, old, new, problems,
                                                    "audience figures"))
    attempt("cost log", lambda: _rewrite_lines(costs.COST_LOG_PATH, old, new, "channel_key"))
    attempt("discard history", lambda: _rewrite_lines(gallery.DISCARD_HISTORY_PATH, old, new))

    def used_records() -> int:
        from pipeline.facts import store
        conn = store.connect()
        moved = 0
        with conn:
            for table in ("used", "question_used"):
                moved += conn.execute(f"UPDATE OR IGNORE {table} SET channel = ? WHERE channel = ?",
                                      (new, old)).rowcount
                # What the new name already had: the old row is its duplicate.
                conn.execute(f"DELETE FROM {table} WHERE channel = ?", (old,))
        return moved
    attempt("facts and questions used", used_records)

    def footage_owner() -> int:
        from core.paths import LIBRARY_DB_PATH
        conn = sqlite3.connect(LIBRARY_DB_PATH, timeout=30)
        try:
            with conn:
                return conn.execute("UPDATE clips SET owner = ? WHERE owner = ?", (new, old)).rowcount
        finally:
            conn.close()
    attempt("footage owned", footage_owner)

    def jobs() -> int:
        moved = 0
        for record in paths.JOB_STATE_DIR.glob("*/job.json") if paths.JOB_STATE_DIR.exists() else ():
            data = json.loads(record.read_text(encoding="utf-8"))
            if data.get("channel_key") != old:
                continue
            data["channel_key"] = new
            if data.get("result_path"):
                data["result_path"] = path_fix(data["result_path"])
            _write_json(record, data)
            moved += 1
        return moved
    attempt("job records", jobs)

    def kits() -> int:
        # A remake kit remembers the video it remakes by its path.
        from core.channels import load_channels
        channel = load_channels(validate=False).get(new)
        moved = 0
        if channel is None or not output_moved:
            return 0
        for seed in gallery.resolve_output_dir(channel.output_dir).rglob("*_remake/seed.json"):
            data = json.loads(seed.read_text(encoding="utf-8"))
            was = data.get("remake_of", "").replace("\\", "/")
            if was.startswith(f"{old}/"):
                data["remake_of"] = f"{new}/" + was[len(old) + 1:]
                _write_json(seed, data)
                moved += 1
        return moved
    attempt("remake kits", kits)

    def previews() -> bool:
        from pipeline.animation import preview
        from pipeline.animation.style import preview as style_preview
        moved = False
        for folder in (preview.PREVIEWS_DIR, style_preview.PREVIEWS_DIR):
            moved = _move(folder / old, folder / new, problems, "previews") or moved
        return moved
    attempt("previews", previews)

    return problems
