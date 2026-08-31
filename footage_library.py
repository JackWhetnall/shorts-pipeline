"""
Shared footage library used across all channels (see CLAUDE.md — one pool,
not per-channel, so a clip pays off on Bible, Shakespeare, and future
channels alike).

Matching is semantic, not tag-lookup: pick_clips_for_shots() sends every
segment's text/keywords together with every library clip's
natural-language description (footage/manifest.json, written by
footage/manage_library.py) to Claude in one call and asks it to match by
meaning — this is what avoids the "tagged 'sunshine', quote says
'sunlight', zero matches" brittleness of exact-tag matching, without
needing a controlled vocabulary or an embedding index. This is entirely
content-agnostic — a segment is just {"text", "keywords"} regardless of
whether it came from a quote, a joke, or anything else.

A segment's footage is split into several shots (see
video_assemble._split_segment_into_shots), and every shot in the whole
video gets a distinct clip — the same clip is never reused twice in one
video. When there aren't enough genuinely good matches in the library to
cover a segment's shots, that same matching call also asks Claude for a
stock-footage search phrase for it (no extra request needed). If
PEXELS_API_KEY/PIXABAY_API_KEY is set, that phrase is used to
automatically fetch, normalize (center crop — no human in the loop here
to pick an off-center one), and describe/add real clips, fully
unattended. Without a key configured, it falls back to the interactive
"pause here to add footage" prompt instead.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from llm_json import call_for_json

ROOT = Path(__file__).parent
LIBRARY_DIR = ROOT / "footage" / "library"
MANIFEST_PATH = ROOT / "footage" / "manifest.json"
NORMALIZED_DIR = ROOT / "footage" / "normalized"
OLD_DOWNLOADS_DIR = ROOT / "footage" / "old_downloads"

sys.path.insert(0, str(ROOT / "footage"))
from bulk_download import search_pexels, search_pixabay, _download  # noqa: E402
from manage_library import _normalize, add_normalized_clip  # noqa: E402

MATCH_MODEL = "claude-sonnet-4-6"
RECENT_WINDOW_HOURS = 48  # clips used within this window get flagged in the prompt

MATCH_SYSTEM_PROMPT = "You match short video segments to stock footage clips by visual and thematic meaning."


def _load_manifest() -> dict:
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_manifest(manifest: dict):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def _is_recent(clip: dict) -> bool:
    if not clip.get("last_used"):
        return False
    last = datetime.fromisoformat(clip["last_used"])
    return (datetime.now(timezone.utc) - last).total_seconds() < RECENT_WINDOW_HOURS * 3600


def _clip_violates_avoid_list(clip: dict, avoid_imagery: list) -> bool:
    haystack = f"{clip.get('description', '')} {clip.get('filename', '')}".lower()
    return any(term.lower() in haystack for term in avoid_imagery)


def _build_prompt(segment_timings: list, shot_counts: list, clips: list, avoid_imagery: list) -> str:
    segments_desc = "\n".join(
        f'{i}. "{s["text"]}" (keywords: {", ".join(s["keywords"])}) '
        f'- needs {n} distinct clip{"s" if n != 1 else ""}'
        for i, (s, n) in enumerate(zip(segment_timings, shot_counts))
    )
    clips_desc = "\n".join(
        f"- {c['filename']}: {c['description']}" + (" [used recently]" if _is_recent(c) else "")
        for c in clips
    )
    avoid_block = ""
    if avoid_imagery:
        avoid_terms = ", ".join(avoid_imagery)
        avoid_block = f"""

IMPORTANT — this channel must never show: {avoid_terms}. This overrides
everything above: a clip is disqualified the moment its imagery relates to
any of these, even if it's otherwise a strong thematic fit for a segment
(e.g. a clip that's specifically prayer/devotion imagery of one of these
excluded kinds does NOT fit a segment about "prayer" or "devotion" in
general — the specific excluded imagery always loses to the general
theme). Also keep "search_query" away from these — don't phrase a search
in a way likely to return this imagery."""
    return f"""Here are the segments of a short video script, in order. Each
segment's footage is shown in several-second chunks, so a segment needing
more than one clip should get several DIFFERENT clips shown in sequence,
not one clip repeated:
{segments_desc}

Here is the available footage library (filename: description):
{clips_desc}

For each segment, list every clip that genuinely, specifically depicts its
subject — best fit first — up to as many as you can find that actually
fit (not just enough to hit the count). Match on meaning, not literal word
overlap — e.g. a clip described as "golden sunlight through a window" is
a good match for a segment about "sunshine" or "dawn" even though those
exact words don't appear in the description.

Be strict — this library is small and still growing, so most clips are
generic and only cover a narrow slice of possible themes. Do not stretch
a merely-adjacent clip into the list just because it's the closest thing
available or shares a vague general vibe (e.g. both being "Bible-related").
A clip of prayer beads genuinely fits a segment about prayer or devotion,
but does NOT fit a segment about "joy" or "the ocean" just because it's
from the same library. Leaving a segment's list short or empty is the
expected, correct outcome whenever the library doesn't have enough
genuine fits — any shortfall gets filled by fetching real footage, so
there's no reason to pad a list with weak options.

A clip can only be used ONCE across the whole video — if an earlier
segment claims a clip, a later segment can't reuse it even if it's also a
good fit for both, so list every genuine fit you can find (not just one),
ranked best first, so a later segment still has real options left over.

Respond with ONLY a JSON object shaped like:
{{"picks": [
  {{"segment_index": 0, "matching_filenames": ["clip1.mp4", "clip5.mp4"], "search_query": "storm clouds dark sky"}},
  {{"segment_index": 1, "matching_filenames": [], "search_query": "candle flame close up"}}
]}}
"matching_filenames" is a ranked list (best first) of clips that
genuinely fit — it's fine for it to be shorter than the segment's needed
count, or empty. Always include "search_query": a short (2-4 word),
concrete, visual stock-footage search phrase for this segment's theme —
used to fetch additional clips whenever the list doesn't cover the
needed count, so keep it literal, not abstract.{avoid_block}"""


def _pick_fallback(clips: list, used: set) -> str:
    available = [c for c in clips if c["filename"] not in used]
    if not available:
        print("  [footage] library fully exhausted for this video - a clip will have to repeat.")
        available = clips
    return min(available, key=lambda c: c.get("last_used") or "")["filename"]


# When a gap is found, fetch more than the immediate need from BOTH
# sources — not just one clip from whichever site answers first. A gap
# found once will come up again for similar future segments, so this is
# the moment to actually build out the library's variety, not just barely
# clear the current shortfall.
BULK_FETCH_PER_SITE = 4


def _auto_fetch_and_add(query: str, min_count: int = 1) -> list:
    """Downloads a batch of stock-footage matches for `query` from BOTH
    Pexels and Pixabay (whichever have keys configured) — at least
    `min_count` per site, more if configured higher — normalizes each with
    a plain center crop, and adds ALL of them to the library. Returns the
    new clips' library Paths; the caller only needs `min_count` of these
    for the current video, but every one added here is now available for
    future videos too. May return fewer than `min_count` total if there
    weren't enough results or a download/describe step failed."""
    per_site = max(BULK_FETCH_PER_SITE, min_count)
    urls = []
    if os.environ.get("PEXELS_API_KEY"):
        try:
            urls += search_pexels(query, count=per_site)
        except Exception as e:
            print(f"  [footage] pexels search failed: {e}")
    if os.environ.get("PIXABAY_API_KEY"):
        try:
            urls += search_pixabay(query, count=per_site)
        except Exception as e:
            print(f"  [footage] pixabay search failed: {e}")
    if not urls:
        print(f"  [footage] no stock footage results for \"{query}\".")
        return []

    seen = set()
    urls = [u for u in urls if not (u in seen or seen.add(u))]

    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    OLD_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_") or "clip"

    added = []
    for idx, url in enumerate(urls, 1):
        dest_name = f"{slug}_auto{idx}.mp4"
        raw_path = OLD_DOWNLOADS_DIR / dest_name
        try:
            _download(url, raw_path)
            normalized_path = NORMALIZED_DIR / dest_name
            _normalize(raw_path, normalized_path)
            # add_normalized_clip does its own perceptual-duplicate check
            # (footage/manage_library.py) before spending an API call — if
            # this download turns out to match a clip already in the
            # library (including one added earlier in this same batch,
            # e.g. Pexels and Pixabay returning the same underlying stock
            # clip), it returns that EXISTING entry instead of a new one.
            entry = add_normalized_clip(normalized_path, dest_name=dest_name,
                                         source=f"auto-fetched for \"{query}\": {url}")
            added.append(LIBRARY_DIR / entry["filename"])
        except Exception as e:
            print(f"  [footage] auto-fetch failed for one clip: {e}")

    # De-duplicate by path (preserving order) — a duplicate-of-existing
    # match above can make the same Path appear more than once here, which
    # would otherwise let one physical clip get assigned to two shots.
    seen_paths = set()
    added = [p for p in added if not (p in seen_paths or seen_paths.add(p))]
    return added


def pick_clips_for_shots(segment_timings: list, shot_counts: list, avoid_imagery: list = None,
                          interactive: bool = True) -> list:
    """
    segment_timings and shot_counts are parallel lists — shot_counts[i] is
    how many distinct clips segment_timings[i] needs (one per shot chunk
    of its real spoken duration). avoid_imagery is the channel's list of
    imagery to never show (config/channels.py) — clips matching it (by
    description/filename, case-insensitive) are dropped from the candidate
    pool entirely before matching even runs, so a thematically-close but
    wrong-imagery clip (e.g. Islamic prayer imagery for a Bible-verse
    segment about "prayer") can never be picked regardless of how well it
    otherwise scores; see _clip_violates_avoid_list and the prompt's
    explicit avoid instruction in _build_prompt for the semantic backstop.

    interactive=False skips the "pause here to add footage" stdin prompt
    when there's a shortfall and no auto-fetch keys — goes straight to
    fallback clips instead. Needed for the web app's background-thread
    generation, which has no TTY to read an answer from; the CLI always
    leaves this True.

    Returns a list of lists of library Paths, one inner list per segment,
    length shot_counts[i] each. Every Path across the ENTIRE result is
    distinct — a clip is never reused within one video (except as an
    absolute last resort if the whole library is smaller than the total
    shots needed, which prints a warning when it happens).
    """
    auto_fetch_available = bool(os.environ.get("PEXELS_API_KEY") or os.environ.get("PIXABAY_API_KEY"))
    avoid_imagery = avoid_imagery or []

    while True:
        manifest = _load_manifest()
        clips = [c for c in manifest["clips"] if not _clip_violates_avoid_list(c, avoid_imagery)]
        if not clips:
            raise FileNotFoundError(
                "footage/manifest.json has no clips - add some with "
                "footage/manage_library.py add <file>"
            )

        data = call_for_json(
            system=MATCH_SYSTEM_PROMPT,
            user_msg=_build_prompt(segment_timings, shot_counts, clips, avoid_imagery),
            model=MATCH_MODEL,
            max_tokens=1500,
        )
        picks = {p["segment_index"]: p for p in data.get("picks", [])}

        by_filename = {c["filename"]: c for c in clips}
        used = set()
        result = [[] for _ in segment_timings]
        shortfalls = []

        for i, segment in enumerate(segment_timings):
            needed = shot_counts[i]
            for fname in (picks.get(i) or {}).get("matching_filenames") or []:
                if len(result[i]) >= needed:
                    break
                if fname in by_filename and fname not in used:
                    result[i].append(fname)
                    used.add(fname)
            deficit = needed - len(result[i])
            if deficit > 0:
                query = (picks.get(i) or {}).get("search_query") or " ".join(segment["keywords"])
                shortfalls.append((i, deficit, query))

        if not shortfalls:
            return [[LIBRARY_DIR / f for f in fnames] for fnames in result]

        if auto_fetch_available:
            for i, deficit, query in shortfalls:
                segment = segment_timings[i]
                print(f"\n  [footage] segment #{i} (\"{segment['text'][:40]}...\") needs {deficit} more "
                      f"distinct clip(s) - fetching stock footage for \"{query}\" ...")
                fetched = _auto_fetch_and_add(query, min_count=deficit)
                # The search query is steered away from avoid_imagery in the
                # prompt, but that's not a guarantee — check each fetched
                # clip's real (just-generated) description before using it
                # for THIS segment. A violating clip stays in the shared
                # library either way, just unused here.
                fresh_by_name = {c["filename"]: c for c in _load_manifest()["clips"]}
                fetched = [p for p in fetched
                           if not _clip_violates_avoid_list(fresh_by_name.get(p.name, {"filename": p.name}), avoid_imagery)]
                for path in fetched[:deficit]:
                    result[i].append(path.name)
                    used.add(path.name)
                if len(fetched) < deficit:
                    print(f"  [footage] only fetched {len(fetched)}/{deficit} for segment #{i} "
                          f"- filling the rest with a fallback clip.")
                elif len(fetched) > deficit:
                    print(f"  [footage] added {len(fetched)} new clips for \"{query}\" to the "
                          f"library ({len(fetched) - deficit} extra, ready for future videos).")
            manifest = _load_manifest()  # pick up whatever auto-fetch just added
            clips = [c for c in manifest["clips"] if not _clip_violates_avoid_list(c, avoid_imagery)]
            for i in range(len(segment_timings)):
                while len(result[i]) < shot_counts[i]:
                    fallback = _pick_fallback(clips, used)
                    result[i].append(fallback)
                    used.add(fallback)
            return [[LIBRARY_DIR / f for f in fnames] for fnames in result]

        summary = ", ".join(f"#{i} (needs {n} more)" for i, n, _ in shortfalls)
        print(f"\n  [footage] not enough distinct matches for segment(s): {summary}")
        print("  Add footage with: python footage/manage_library.py add <file>")
        print("  (or set PEXELS_API_KEY/PIXABAY_API_KEY to fetch stock footage automatically next time)")

        if not interactive:
            print("  Continuing with fallback clips for the remaining shot(s) (non-interactive mode).")
            for i, _, _ in shortfalls:
                while len(result[i]) < shot_counts[i]:
                    fallback = _pick_fallback(clips, used)
                    result[i].append(fallback)
                    used.add(fallback)
            return [[LIBRARY_DIR / f for f in fnames] for fnames in result]

        answer = input("  Pause here to add footage now? [y/N] ").strip().lower()
        if answer in ("y", "yes"):
            input("  Press Enter once you've added the clip(s) to retry the match... ")
            continue
        print("  Continuing with fallback clips for the remaining shot(s).")
        for i, _, _ in shortfalls:
            while len(result[i]) < shot_counts[i]:
                fallback = _pick_fallback(clips, used)
                result[i].append(fallback)
                used.add(fallback)
        return [[LIBRARY_DIR / f for f in fnames] for fnames in result]


def mark_used(clip_path):
    """Persist usage back to the manifest — call once per clip used after a
    successful render so recency-avoidance stays accurate."""
    manifest = _load_manifest()
    filename = Path(clip_path).name
    for clip in manifest["clips"]:
        if clip["filename"] == filename:
            clip["use_count"] = clip.get("use_count", 0) + 1
            clip["last_used"] = datetime.now(timezone.utc).isoformat()
            break
    _save_manifest(manifest)
