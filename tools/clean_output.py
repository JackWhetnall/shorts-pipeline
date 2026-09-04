"""
Reclaim the disk that discarded and abandoned videos are sitting on.

    python tools/clean_output.py                    # report everything
    python tools/clean_output.py --delete           # act on it
    python tools/clean_output.py --older-than 30    # only discards over 30 days old
    python tools/clean_output.py --channel minute_pastor
    python tools/clean_output.py --orphans-only

Two kinds of dead weight accumulate under output/, and nothing has ever
removed either.

**Discarded takes.** Discarding is deliberately reversible — the files
stay, a flag flips — which is right for a decision made in the review
queue and wrong forever. On this project's own output directory that was
416 MB across 19 videos, from a system producing two a day.

**Orphans.** A run that crashed after the voiceover stage leaves its
per-segment mp3s behind. Every listing in the app enumerates `*.mp4`, so
nothing notices them, and they never get cleaned up by the retry either
(a retry writes under a new stem).

Deleting a discarded video does NOT delete the fact that it was
discarded: a tombstone goes to `config/discard_history.jsonl` first, so
the discard rate and its reasons on /insights survive the cleanup. That
matters more than the disk — a daily loop of "discard the bad ones, then
free the space" would otherwise erase the only measurement of whether the
output is improving, and leave the keep rate reading 100%.

Reporting is the default. Deletion is not undoable.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import gallery                                          # noqa: E402
from core.channels import load_channels                           # noqa: E402
from core.logging_setup import configure, get_logger              # noqa: E402

log = get_logger(__name__)


def _mb(size: int) -> str:
    return f"{size / 1e6:.1f} MB"


def _age_days(stamp: str):
    """Days since an ISO timestamp, or None if there isn't a usable one.

    Videos discarded before reasons were recorded have no timestamp at
    all. They are the oldest things here by definition, so an unknown age
    passes any --older-than filter rather than being excluded from the
    cleanup it most obviously applies to.
    """
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).days


def survey(channel_keys=None, older_than: int = None) -> dict:
    channels = load_channels(validate=False)
    if channel_keys:
        channels = {k: v for k, v in channels.items() if k in channel_keys}

    discarded, orphans, skipped = [], [], 0
    for key, channel in channels.items():
        directory = gallery.resolve_output_dir(channel.output_dir)
        if not directory.exists():
            continue
        for video in sorted(directory.rglob("*.mp4")):
            info = gallery.load_publish_info(video)
            if not info["discarded"]:
                continue
            age = _age_days(info.get("discarded_at"))
            if older_than is not None and age is not None and age < older_than:
                skipped += 1
                continue
            files = gallery.sidecars_of(video)
            discarded.append({
                "channel": key, "path": video,
                "reason": info.get("discard_reason") or "unrecorded",
                "age": age, "files": files,
                "bytes": sum(f.stat().st_size for f in files),
            })
        for path in gallery.orphaned_files(channel.output_dir):
            orphans.append({"channel": key, "path": path,
                            "bytes": path.stat().st_size})

    return {"discarded": discarded, "orphans": orphans, "skipped": skipped}


def report(found: dict, orphans_only: bool) -> None:
    if not orphans_only:
        rows = found["discarded"]
        total = sum(r["bytes"] for r in rows)
        print(f"\nDiscarded videos: {len(rows)}, {_mb(total)}")
        for row in rows:
            age = "unknown age" if row["age"] is None else f"{row['age']}d old"
            print(f"  {row['channel']:16s} {row['path'].name:36s} "
                  f"{row['reason']:12s} {age:14s} "
                  f"{len(row['files'])} files  {_mb(row['bytes'])}")
        if found["skipped"]:
            print(f"  ({found['skipped']} newer than the age cutoff, left alone)")

    rows = found["orphans"]
    total = sum(r["bytes"] for r in rows)
    print(f"\nOrphaned files (no video): {len(rows)}, {_mb(total)}")
    for row in rows:
        print(f"  {row['channel']:16s} {row['path'].name}")


def main() -> None:
    configure()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--delete", action="store_true",
                        help="Actually remove the files. Not undoable.")
    parser.add_argument("--older-than", type=int, metavar="DAYS",
                        help="Only discards at least this old. Videos with no "
                             "recorded discard date always qualify.")
    parser.add_argument("--channel", action="append", dest="channels",
                        help="Limit to one channel. Repeatable.")
    parser.add_argument("--orphans-only", action="store_true",
                        help="Leave discarded videos alone.")
    args = parser.parse_args()

    found = survey(args.channels, args.older_than)
    report(found, args.orphans_only)

    freeable = sum(r["bytes"] for r in found["orphans"])
    if not args.orphans_only:
        freeable += sum(r["bytes"] for r in found["discarded"])

    if not args.delete:
        print(f"\nWould free {_mb(freeable)}. Re-run with --delete to do it.")
        return

    freed = failed = 0
    if not args.orphans_only:
        for row in found["discarded"]:
            try:
                result = gallery.purge(row["path"], row["channel"])
                freed += result["bytes"]
            except (OSError, ValueError) as exc:
                # One locked file (a video open in a player is the usual
                # cause on Windows) should not stop the rest.
                failed += 1
                log.warning(f"Could not remove {row['path'].name}: {exc}")

    for row in found["orphans"]:
        try:
            row["path"].unlink()
            freed += row["bytes"]
        except OSError as exc:
            failed += 1
            log.warning(f"Could not remove {row['path'].name}: {exc}")

    print(f"\nFreed {_mb(freed)}." + (f" {failed} could not be removed." if failed else ""))
    if not args.orphans_only and found["discarded"]:
        print("Discard reasons kept in config/discard_history.jsonl; "
              "/insights still counts them.")


if __name__ == "__main__":
    main()
