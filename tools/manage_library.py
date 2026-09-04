"""
Maintain the shared footage library.

    python tools/manage_library.py add clip.mp4
    python tools/manage_library.py add clip.mp4 --notes "camera pans slowly left"
    python tools/manage_library.py list
    python tools/manage_library.py stats
    python tools/manage_library.py import-manifest      # one-time, JSON -> SQLite
    python tools/manage_library.py find-duplicates [--delete]
    python tools/manage_library.py prune [--delete]
    python tools/manage_library.py set-license <filename> "<licence text>"

`prune` is the one that reclaims disk. The intake flow leaves the raw
download in footage/old_downloads/ and the crop-normalized copy in
footage/normalized/, and nothing ever cleaned either up — on this
project's own library that was ~20 GB of files nothing reads, on top of a
4.7 GB directory of clips that no code or documentation referenced at
all. Reporting is the default; --delete is deliberate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.logging_setup import configure, get_logger              # noqa: E402
from core.paths import (                                          # noqa: E402
    CACHE_DIR, FOOTAGE_DIR, LIBRARY_DIR, NEW_DOWNLOADS_DIR, NORMALIZED_DIR,
    OLD_DOWNLOADS_DIR,
)
from pipeline.footage import intake, store                        # noqa: E402

log = get_logger(__name__)

# Directories the intake flow writes to but never reads back. Kept
# separate from the library itself, which is the only one the pipeline
# actually uses.
STAGING_DIRS = (
    (NORMALIZED_DIR, "crop-normalized copies, already inside the library"),
    (OLD_DOWNLOADS_DIR,
     "raw originals — auto-fetched ones are re-downloadable from their recorded URL"),
    (FOOTAGE_DIR / "default_downloaded",
     "an old bulk-download batch — referenced by no code and no documentation"),
    (CACHE_DIR / "downloads", "in-flight downloads; deleted automatically after use"),
)


def _human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} TB"


def _dir_size(path: Path) -> tuple:
    if not path.exists():
        return 0, 0
    total = count = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
            count += 1
    return total, count


def cmd_add(args) -> int:
    source = Path(args.file)
    if not source.exists():
        print(f"No such file: {source}")
        return 1

    dest_name = args.name or (source.stem.lower().replace(" ", "_") + ".mp4")
    if not dest_name.endswith(".mp4"):
        dest_name += ".mp4"

    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    normalized = LIBRARY_DIR / dest_name
    log.info(f"Normalizing {source.name} -> footage/library/{dest_name} ...")
    intake.normalize(source, normalized)
    intake.add_normalized_clip(normalized, dest_name=dest_name, source=args.source,
                               license_text=args.license, license_verified=bool(args.license),
                               notes=args.notes)
    return 0


def cmd_list(args) -> int:
    clips = store.all_clips()
    if not clips:
        print("The library is empty.")
        return 0
    for clip in clips:
        flag = "" if clip.license_verified else "  [licence unverified]"
        print(f"{clip.filename}  ({clip.duration:.1f}s, used {clip.use_count}x){flag}")
        print(f"    {clip.description or '(no description)'}")
    return 0


def cmd_stats(args) -> int:
    clips = store.all_clips()
    missing = [c for c in clips if not (LIBRARY_DIR / c.filename).exists()]
    unverified = [c for c in clips if not c.license_verified]
    unused = [c for c in clips if not c.use_count]

    print(f"Clips:              {len(clips)}")
    print(f"Never used:         {len(unused)}")
    print(f"Licence unverified: {len(unverified)}")
    print(f"Files missing:      {len(missing)}")
    if unverified:
        print("\nClips whose licence isn't confirmed:")
        for clip in unverified:
            print(f"  {clip.filename}  (source: {clip.source or 'unknown'})")
        print("\nConfirm one with: python tools/manage_library.py "
              "set-license <filename> \"<licence text>\"")
    return 0


def cmd_import_manifest(args) -> int:
    result = store.import_manifest()
    print(f"Imported {result['imported']} clip(s); the library now holds {result['total']}.")
    print("footage/manifest.json is left in place as a backup.")
    return 0


def cmd_set_license(args) -> int:
    clip = store.get(args.filename)
    if clip is None:
        print(f"No clip called {args.filename}.")
        return 1
    clip.license = args.license
    clip.license_verified = True
    store.upsert(clip)
    print(f"{clip.filename}: licence recorded as verified.")
    return 0


def cmd_find_duplicates(args) -> int:
    clips = [c for c in store.all_clips() if c.frame_hashes]
    pairs, cliques, ambiguous = intake.cluster_duplicates(clips)

    if not pairs:
        print("No likely duplicates found.")
        return 0

    for group in cliques:
        print("  Duplicate group (every clip matches every other): "
              + ", ".join(clips[i].filename for i in group))
    for group in ambiguous:
        print("  Ambiguous group (some pairs match, some don't — review by hand): "
              + ", ".join(clips[i].filename for i in group))

    if not args.delete:
        removable = sum(len(g) - 1 for g in cliques)
        print(f"\n{len(cliques)} confident group(s), {removable} clip(s) removable, "
              f"plus {len(ambiguous)} ambiguous group(s) needing a look.")
        print("Re-run with --delete to remove the confident ones.")
        return 0

    removed = []
    for group in cliques:
        members = [clips[i] for i in group]
        keep = intake.keeper(members)
        for clip in members:
            if clip.filename == keep.filename:
                continue
            (LIBRARY_DIR / clip.filename).unlink(missing_ok=True)
            removed.append(clip.filename)
            print(f"  Removed {clip.filename} (duplicate of {keep.filename})")
    store.delete(removed)
    print(f"\nRemoved {len(removed)} clip(s). The library now holds {store.count()}.")
    if ambiguous:
        print(f"{len(ambiguous)} ambiguous group(s) left alone.")
    return 0


def cmd_enrich(args) -> int:
    """Distil structured attributes out of the descriptions we already have."""
    from pipeline.footage import enrich

    estimate = enrich.estimate_cost(only_missing=not args.all)
    if not estimate["clips"]:
        print("Every clip already has structured attributes. Use --all to redo them.")
        return 0

    cost = f"${estimate['usd']:.2f}" if estimate["usd"] is not None else "an unknown amount"
    print(f"{estimate['clips']} clip(s) to enrich in {estimate['batches']} batch(es).")
    print(f"Estimated cost: {cost}.")
    print()
    print("This reads the descriptions already in the library — it does not look at")
    print("the videos again — and gives each clip a subject, setting, motion, palette")
    print("and time of day. Matching weights `subject` eight times the prose, so a")
    print("brief asking for prayer beads stops ranking clips that merely have some")
    print("on the table.")

    if not args.yes:
        print()
        if input("Go ahead? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Nothing done.")
            return 0

    def progress(done, total):
        print(f"  {done}/{total} ...")

    result = enrich.enrich_library(only_missing=not args.all, progress=progress)
    print()
    print(f"Enriched {result['updated']} of {result['considered']} clip(s).")
    return 0


def cmd_compact(args) -> int:
    """Trim and re-encode the library. Reports first; only acts with --apply."""
    from pipeline.footage import compact

    proposal = compact.plan(args.max_seconds, args.crf)
    before = proposal["total_before"]
    saving = proposal["estimated_saving"]

    total_clips = len(proposal["candidates"]) + proposal["skipped"]
    print(f"Library: {_human(before)} across {total_clips} clip(s).")
    print()
    print(f"  would rewrite : {len(proposal['candidates'])} clip(s)")
    print(f"  already small : {proposal['skipped']} clip(s), left alone")
    print(f"  trim to       : {args.max_seconds:.0f}s "
          f"({int(args.max_seconds // 5)} distinct 5s windows per clip)")
    print(f"  quality       : CRF {args.crf}")
    print()
    print(f"  estimated after : {_human(before - saving)}")
    print(f"  estimated saving: {_human(saving)}  ({saving / before:.0%})" if before else "")

    if not args.apply:
        print()
        print("This only reports. Re-run with --apply to rewrite the clips.")
        print("Re-encoding is lossy and cannot be undone — but the originals for")
        print("auto-fetched clips are recorded as URLs and can be fetched again.")
        return 0

    print()
    def progress(done, total):
        if done % 10 == 0 or done == total:
            print(f"  {done}/{total} ...")

    result = compact.compact_library(args.max_seconds, args.crf, progress=progress)
    print()
    print(f"Rewrote {result['processed']} clip(s).")
    print(f"Reclaimed {_human(result['saved'])} — library now {_human(result['after'])}.")
    return 0


def cmd_prune(args) -> int:
    """Report — or with --delete, remove — staging directories nothing reads."""
    print("Footage directories:\n")
    library_size, library_count = _dir_size(LIBRARY_DIR)
    print(f"  {'library/':22s} {_human(library_size):>10s}  "
          f"{library_count:>4d} files   IN USE — the pipeline reads this")
    incoming_size, incoming_count = _dir_size(NEW_DOWNLOADS_DIR)
    print(f"  {'new_downloads/':22s} {_human(incoming_size):>10s}  "
          f"{incoming_count:>4d} files   awaiting review")

    reclaimable = 0
    targets = []
    print()
    for path, why in STAGING_DIRS:
        size, count = _dir_size(path)
        if not count:
            continue
        reclaimable += size
        targets.append(path)
        print(f"  {path.name + '/':22s} {_human(size):>10s}  {count:>4d} files   {why}")

    if not targets:
        print("  Nothing to reclaim.")
        return 0

    print(f"\nReclaimable: {_human(reclaimable)}")
    if not args.delete:
        print("\nThis only reports. Re-run with --delete to actually remove these.")
        print("Note: removing old_downloads/ gives up the ability to re-crop a clip")
        print("from its original — the library copies themselves are untouched.")
        return 0

    import shutil
    for path in targets:
        shutil.rmtree(path, ignore_errors=True)
        print(f"  Removed {path}")
    print(f"\nReclaimed {_human(reclaimable)}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the shared footage library.")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Normalize, describe and add a clip")
    add.add_argument("file")
    add.add_argument("--name", help="Filename to save as")
    add.add_argument("--notes", help="Context the frames can't show (e.g. camera motion)")
    add.add_argument("--source", help="Where this clip came from (a URL)")
    add.add_argument("--license", help="Licence text, if you've confirmed it")
    add.set_defaults(func=cmd_add)

    sub.add_parser("list", help="List every clip").set_defaults(func=cmd_list)
    sub.add_parser("stats", help="Library health, including licence status").set_defaults(func=cmd_stats)
    sub.add_parser("import-manifest",
                   help="One-time import of footage/manifest.json").set_defaults(func=cmd_import_manifest)

    license_cmd = sub.add_parser("set-license", help="Record a confirmed licence for one clip")
    license_cmd.add_argument("filename")
    license_cmd.add_argument("license")
    license_cmd.set_defaults(func=cmd_set_license)

    dupes = sub.add_parser("find-duplicates", help="Scan for duplicate clips")
    dupes.add_argument("--delete", action="store_true", help="Remove the confident duplicates")
    dupes.set_defaults(func=cmd_find_duplicates)

    prune = sub.add_parser("prune", help="Report (or remove) staging files nothing reads")
    prune.add_argument("--delete", action="store_true", help="Actually delete them")
    prune.set_defaults(func=cmd_prune)

    enrich = sub.add_parser(
        "enrich", help="Give clips a subject/setting/motion, for sharper matching")
    enrich.add_argument("--all", action="store_true",
                        help="Redo clips that already have attributes")
    enrich.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation")
    enrich.set_defaults(func=cmd_enrich)

    compact = sub.add_parser(
        "compact", help="Trim and re-encode the library to reclaim disk")
    compact.add_argument("--max-seconds", type=float, default=15.0, dest="max_seconds",
                         help="Trim clips longer than this (default 15)")
    compact.add_argument("--crf", type=int, default=26,
                         help="x264 quality, higher is smaller (default 26)")
    compact.add_argument("--apply", action="store_true", help="Actually rewrite the clips")
    compact.set_defaults(func=cmd_compact)

    args = parser.parse_args()
    configure()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
