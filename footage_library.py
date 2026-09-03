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
whether it came from a quote, a joke, or anything else. Each candidate
clip gets an explicit 1-10 confidence score from the model, and anything
below MATCH_CONFIDENCE_THRESHOLD is treated as no match at all — added
after real use showed the matcher calling loosely-related clips "good
enough" on theme alone (e.g. a generic crowd shot offered up for a
segment specifically about doubt).

A segment's footage is split into several shots (see
video_assemble._split_segment_into_shots), and every shot in the whole
video gets a distinct clip — the same clip is never reused twice in one
video. When there aren't enough genuinely good matches in the library to
cover a segment's shots, that same matching call also asks Claude for
several SHORT, DISTINCT search phrases for it (e.g. "open hands",
"hoping", "asking" rather than one sentence like "a person standing with
open hands asking for something") — no extra request needed. If
PEXELS_API_KEY/PIXABAY_API_KEY is set, each phrase is queried separately
(a few results per site per phrase) and all results are fetched,
normalized (center crop — no human in the loop here to pick an off-center
one), and described/added, fully unattended. Querying several distinct
short phrases instead of one broad one is what stops a single shortfall
from flooding the library with near-duplicates of itself (e.g. "20
videos of calm water" from one over-broad query). Without a key
configured, it falls back to the interactive "pause here to add footage"
prompt instead.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from llm_json import call_for_json
import job_context

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

# Below this, a candidate clip is treated as no match at all (not even a
# weak fallback) — added after real use showed the matcher was too willing
# to call a loosely-related clip "good enough" (e.g. a generic crowd shot
# offered up for a segment specifically about doubt or introspection, on
# theme alone). Forcing an explicit numeric self-rating and filtering on it
# in code is a real mechanism, not just stronger wording in the prompt —
# the model still has to commit to a score it can't quietly fudge past.
# Originally 7, then 6 - real runs kept coming back with almost nothing
# matched (near-constant auto-fetch/fallback even for segments the
# library plainly had reasonable footage for), so lowered again to 5.
# Still a real bar, not "anything goes": _build_prompt's rubric below
# defines 5 as a genuine, if generous, pass ("real connection to the
# subject, not just a shared vibe") and keeps 1-4 as an explicit MISS -
# the threshold and the rubric band it lands on are edited together on
# purpose, so the model is never scoring against a different bar than the
# code actually enforces.
MATCH_CONFIDENCE_THRESHOLD = 5

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


def _build_prompt(segment_timings: list, shot_counts: list, clips: list, avoid_imagery: list,
                   tried_queries_by_segment: dict = None) -> str:
    tried_queries_by_segment = tried_queries_by_segment or {}
    segment_lines = []
    for i, (s, n) in enumerate(zip(segment_timings, shot_counts)):
        line = (f'{i}. "{s["text"]}" (keywords: {", ".join(s["keywords"])}) '
                f'- needs {n} distinct clip{"s" if n != 1 else ""}')
        tried = tried_queries_by_segment.get(i)
        if tried:
            line += (f' [already searched without finding enough good matches: '
                      f'{", ".join(sorted(tried))} — try different angles/phrases '
                      f'this time, not these same ones]')
        segment_lines.append(line)
    segments_desc = "\n".join(segment_lines)
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
theme). Also keep "search_queries" away from these — don't phrase a
search in a way likely to return this imagery."""
    return f"""Here are the segments of a short video script, in order. Each
segment's footage is shown in several-second chunks, so a segment needing
more than one clip should get several DIFFERENT clips shown in sequence,
not one clip repeated:
{segments_desc}

Here is the available footage library (filename: description):
{clips_desc}

For each segment, list every clip that could plausibly fit, best fit
first, and rate each one's confidence from 1-10 for how well it actually
depicts that segment's specific subject (not just its general theme or
mood):
- 9-10: an unmistakable, direct depiction of the segment's actual subject.
- 7-8: a clear, specific depiction of the same concept, differing only in
  incidental detail (setting, framing, who's in it).
- 6: still a real depiction of the specific subject, not just its theme —
  but weaker or more incidental than 7-8 (e.g. the subject is present but
  not the focus of the shot). A genuine pass, just not a generous one.
- 5: a real, honest connection to the specific subject (not just the same
  mood) but indirect or partial — e.g. footage of rain for a segment
  about a storm, or a single candle for a segment about warmth in
  general. Generous, but still a real link to what the segment is
  actually about, not merely the same vibe. Use this band rather than
  inventing a 6+ score you don't believe.
- 1-4: the same general theme or mood ONLY, with no real connection to
  the specific subject — e.g. a generic crowd shot for a segment
  specifically about doubt or introspection, or open ocean for a segment
  specifically about calm rather than the ocean itself. This band is a
  MISS, not a soft yes — rate it honestly even though it's tempting to
  call it close enough.
Match on meaning, not literal word overlap — e.g. a clip described as
"golden sunlight through a window" can legitimately score 9 for a segment
about "sunshine" or "dawn" even though those exact words don't appear in
the description — but that's a real match on the specific subject, not a
mood-only stretch.

Be strict with the score itself, not just the list — this library is
small and still growing, so most clips are generic and only cover a
narrow slice of possible themes. A clip of prayer beads scores high for a
segment about prayer or devotion, but should score low (2-3) for a
segment about "joy" or "the ocean" even though it's from the same
library and vaguely Bible-adjacent. Leaving a segment's list short, or
full of clips scored below 7, is the expected, correct outcome whenever
the library doesn't have enough genuine fits — any shortfall gets filled
by fetching real footage, so there's no reason to inflate a score to pad
the list.

A clip can only be used ONCE across the whole video — if an earlier
segment claims a clip, a later segment can't reuse it even if it's also a
good fit for both, so list every plausible fit you can find with its
honest score (not just one), so a later segment still has real options
left over if the top pick is already taken.

Respond with ONLY a JSON object shaped like:
{{"picks": [
  {{"segment_index": 0, "matches": [{{"filename": "clip1.mp4", "confidence": 9}}, {{"filename": "clip5.mp4", "confidence": 6}}],
    "search_queries": ["storm clouds", "lightning strike", "dark horizon"]}},
  {{"segment_index": 1, "matches": [], "search_queries": ["candle flame", "warm glow", "quiet room"]}}
]}}
"matches" is ranked best-first; include every plausible candidate with
its honest score, even ones you expect to score below 7 — the caller
does the filtering, don't pre-filter by omitting low scores yourself.
Always include "search_queries": 2-3 SHORT, DISTINCT phrases (1-3 words
each) for this segment's theme, each capturing a different concrete
visual angle — not one longer descriptive sentence. For a segment about
someone hopefully asking for something, that's ["open hands", "hoping",
"asking"], not one query like "a person standing with open hands asking
for something" — the point is several different real search results
across genuinely different angles on the theme, not many near-duplicate
results for one over-specific phrase. Keep each phrase literal and
visual, not abstract.{avoid_block}"""


def _pick_fallback(clips: list, used: set) -> str:
    available = [c for c in clips if c["filename"] not in used]
    if not available:
        print("  [footage] library fully exhausted for this video - a clip will have to repeat.")
        available = clips
    return min(available, key=lambda c: c.get("last_used") or "")["filename"]


# Each individual query now fetches only a few results per site — the
# diversity comes from issuing SEVERAL DISTINCT queries (see
# _build_prompt's "search_queries": "open hands", "hoping", "asking" as
# separate requests, not one descriptive phrase), not from fetching many
# results for one broad phrase. That's what fixed "20 videos of calm
# water": one query, however broad, fetched at a high count, always
# collapses into near-duplicates of itself.
FETCH_PER_SITE_PER_QUERY = 2

# How many fetch-and-recheck cycles pick_clips_for_shots will run per video
# before giving up and using fallback clips for whatever's still short.
# Fetching once and trusting the result unconditionally (the old behavior)
# never actually verified relevance - this caps the alternative (fetch,
# re-run the real matching/scoring call, and if still short, fetch again
# with different search terms) so a persistently hard-to-match segment
# can't loop forever.
MAX_FETCH_ATTEMPTS = 3

# How many clips download+normalize at once. This is network-I/O-bound
# (waiting on Pexels'/Pixabay's servers, not this machine's CPU), so a
# wide pool is fine and is what actually fixes "downloads look batched" -
# the earlier default (parallel_map's generic max_workers=8, sized for
# CPU-adjacent work) meant any round with more than 8 candidates visibly
# finished in groups of 8 rather than one continuous stream. This is
# still a real cap, not "everything at once" — Pexels/Pixabay are free-
# tier APIs, and a genuinely unbounded burst risks tripping their own
# rate limiting, which would look like failures, not speed.
FETCH_MAX_WORKERS = 16

# Hard cap on how many clips one fetch round downloads at once, regardless
# of how many segments are short or how many queries that produces -
# without this, combining every shortfalled segment's queries into one
# round (see the "batching" fix above pick_clips_for_shots) could balloon
# into dozens of simultaneous downloads for a video with several weak
# segments. A capped round that sometimes needs a second round (the
# fetch-and-recheck loop already supports that, up to MAX_FETCH_ATTEMPTS)
# is a much better experience than one enormous round.
MAX_CANDIDATES_PER_ROUND = 12


def _auto_fetch_and_add(queries, min_count: int = 1) -> list:
    """Downloads stock-footage matches for EACH of `queries` (a list of
    short, distinct conceptual phrases — see _build_prompt) from BOTH
    Pexels and Pixabay (whichever have keys configured), a few per site per
    query, normalizes each with a plain center crop, and adds ALL of them
    to the library. Returns the new clips' library Paths; the caller only
    needs `min_count` of these for the current video, but every one added
    here is now available for future videos too. Accepts a single string
    for backward compatibility, treated as a one-query list. May return
    fewer than `min_count` total if there weren't enough results or a
    download/describe step failed."""
    if isinstance(queries, str):
        queries = [queries]
    queries = [q.strip() for q in queries if q and q.strip()] or ["stock footage"]

    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    OLD_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    # Search is quick metadata; download+normalize (network transfer + an
    # ffmpeg subprocess per clip) is the actually-slow, fully independent
    # part, so gather every candidate across all queries first, then fetch
    # them all concurrently. add_normalized_clip (perceptual-duplicate
    # check + Claude vision describe + manifest write) stays sequential
    # afterward - it reads and mutates the SHARED manifest, so two threads
    # racing there could each miss the other's just-added entry and create
    # duplicate clips from the same batch.
    by_query = {}  # query -> [(url, dest_name), ...]
    for query in queries:
        urls = []
        if os.environ.get("PEXELS_API_KEY"):
            try:
                urls += search_pexels(query, count=FETCH_PER_SITE_PER_QUERY)
            except Exception as e:
                print(f"  [footage] pexels search failed for \"{query}\": {e}")
        if os.environ.get("PIXABAY_API_KEY"):
            try:
                urls += search_pixabay(query, count=FETCH_PER_SITE_PER_QUERY)
            except Exception as e:
                print(f"  [footage] pixabay search failed for \"{query}\": {e}")
        if not urls:
            print(f"  [footage] no stock footage results for \"{query}\".")
            continue

        seen_urls = set()
        urls = [u for u in urls if not (u in seen_urls or seen_urls.add(u))]
        slug = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_") or "clip"
        by_query[query] = [(url, f"{slug}_auto{idx}.mp4") for idx, url in enumerate(urls, 1)]

    # Combining every shortfalled segment's queries into one round (the
    # earlier "batching" fix) means a video with several segments short on
    # footage can generate a LOT of queries at once - unchecked, that's
    # what produced a real run with 36 simultaneous downloads queued, way
    # more than anyone can usefully watch progress on or than is a
    # reasonable amount of work for one round. Capped here, round-robin
    # across queries (one from each query, then a second pass, etc.) so
    # the cap doesn't just favor whichever segment's queries happened to
    # be built first - every shortfalled segment gets a fair shot within
    # the round even when the total had to be trimmed.
    candidates = []  # (query, url, dest_name)
    query_order = list(by_query.keys())
    round_idx = 0
    while len(candidates) < MAX_CANDIDATES_PER_ROUND and any(by_query.values()):
        added_this_pass = False
        for query in query_order:
            if len(candidates) >= MAX_CANDIDATES_PER_ROUND:
                break
            bucket = by_query[query]
            if round_idx < len(bucket):
                url, dest_name = bucket[round_idx]
                candidates.append((query, url, dest_name))
                added_this_pass = True
        if not added_this_pass:
            break
        round_idx += 1

    # Each round replaces the detail panel's clip tower rather than
    # appending to it - a previous round's rows are no longer live once a
    # new round starts. Each clip moves through ordered "step" values
    # (see FOOTAGE_STEPS below) - a single field rather than two
    # coarse booleans, so the frontend can render an actual multi-segment
    # progress bar per clip instead of two flashing dots that look
    # identical whether a step is active or already done.
    job_context.report_detail("footage", None, {"items": [], "total_candidates": len(candidates)})
    for item_index, (query, url, dest_name) in enumerate(candidates):
        job_context.report_detail("footage", item_index, {
            "query": query, "filename": dest_name, "step": "queued",
        })

    def _fetch_one(indexed):
        item_index, (query, url, dest_name) = indexed
        raw_path = OLD_DOWNLOADS_DIR / dest_name
        normalized_path = NORMALIZED_DIR / dest_name
        job_context.report_detail("footage", item_index, {"step": "downloading"})
        try:
            print(f"  [footage] downloading \"{dest_name}\" for \"{query}\"...")
            _download(url, raw_path)
            job_context.report_detail("footage", item_index, {"step": "normalizing"})
            _normalize(raw_path, normalized_path)
            return item_index, query, url, dest_name, normalized_path, None
        except Exception as e:
            job_context.report_detail("footage", item_index, {"step": "failed"})
            return item_index, query, url, dest_name, None, e

    fetched = job_context.parallel_map(_fetch_one, list(enumerate(candidates)), max_workers=FETCH_MAX_WORKERS)

    added = []
    seen_paths = set()
    for item_index, query, url, dest_name, normalized_path, error in fetched:
        if error is not None:
            print(f"  [footage] auto-fetch failed for one clip (\"{query}\"): {error}")
            continue
        job_context.report_detail("footage", item_index, {"step": "analyzing"})
        try:
            # add_normalized_clip does its own perceptual-duplicate check
            # (footage/manage_library.py) before spending an API call — if
            # this download turns out to match a clip already in the
            # library (including one added earlier in this same batch,
            # e.g. two different queries or both Pexels and Pixabay
            # returning the same underlying stock clip), it returns that
            # EXISTING entry instead of a new one.
            entry = add_normalized_clip(normalized_path, dest_name=dest_name,
                                         source=f"auto-fetched for \"{query}\": {url}")
            job_context.report_detail("footage", item_index, {"step": "done"})
            path = LIBRARY_DIR / entry["filename"]
            if path not in seen_paths:
                seen_paths.add(path)
                added.append(path)
        except Exception as e:
            job_context.report_detail("footage", item_index, {"step": "failed"})
            print(f"  [footage] auto-fetch failed for one clip (\"{query}\"): {e}")

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
    fetch_attempt = 0
    tried_queries_by_segment = {}
    job_context.report_detail("footage", None, {"total_shots": sum(shot_counts)})

    # This is the single most expensive part of a video to redo after an
    # interruption (a Claude matching call per round, plus real fetches) -
    # a retry (see webapp/jobs.py's retry_job) reuses this exact pick if
    # the checkpoint is for the SAME shot_counts (a different script would
    # need different shots, so a stale checkpoint from a differently-
    # shaped script must never be reused blindly).
    cached = job_context.load_json_checkpoint("footage_picks")
    if cached and cached.get("shot_counts") == shot_counts:
        cached_picks = cached["picks"]
        manifest_now = {c["filename"] for c in _load_manifest()["clips"]}
        if all(f in manifest_now for group in cached_picks for f in group):
            print("  [footage] reusing previously matched footage (resumed from checkpoint)...")
            return [[LIBRARY_DIR / f for f in group] for group in cached_picks]

    def _finalize(result: list) -> list:
        try:
            job_context.save_json_checkpoint("footage_picks", {"shot_counts": shot_counts, "picks": result})
        except Exception:
            pass  # checkpointing is best-effort, never block a real result on it
        return [[LIBRARY_DIR / f for f in fnames] for fnames in result]

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
            user_msg=_build_prompt(segment_timings, shot_counts, clips, avoid_imagery, tried_queries_by_segment),
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
            pick = picks.get(i) or {}
            # Drop anything the model itself rated below the confidence bar
            # before we even look at it — this is the enforced half of "stop
            # being generous about weak matches" (the prompt's scoring
            # bands are the other half). Sort defensively by confidence in
            # case the model's own ranking and its scores ever disagree.
            confident_matches = sorted(
                (m for m in (pick.get("matches") or [])
                 if isinstance(m, dict) and m.get("confidence", 0) >= MATCH_CONFIDENCE_THRESHOLD),
                key=lambda m: m.get("confidence", 0),
                reverse=True,
            )
            for m in confident_matches:
                fname = m.get("filename")
                if len(result[i]) >= needed:
                    break
                if fname in by_filename and fname not in used:
                    result[i].append(fname)
                    used.add(fname)
            deficit = needed - len(result[i])
            if deficit > 0:
                queries = pick.get("search_queries") or segment["keywords"] or ["stock footage"]
                shortfalls.append((i, deficit, queries))

        if not shortfalls:
            return _finalize(result)

        if auto_fetch_available and fetch_attempt < MAX_FETCH_ATTEMPTS:
            fetch_attempt += 1
            job_context.report_detail("footage", None, {"round": fetch_attempt, "total_rounds": MAX_FETCH_ATTEMPTS})
            # Every shortfalled segment's queries are fetched in ONE
            # combined call, not one call per segment — a separate call
            # per segment meant a separate sequential search-then-download
            # round-trip for EACH segment, which is what actually looked
            # like "batching" from outside even though downloads within
            # any one call were already parallel. Segment-level detail
            # doesn't need to survive into the fetch itself: the search
            # queries carry everything the fetch needs to know, and the
            # NEXT matching call re-scores the whole (now bigger) library
            # against every segment fresh, so it doesn't matter which
            # segment's shortfall originally requested which query.
            all_queries = []
            for i, deficit, queries in shortfalls:
                segment = segment_timings[i]
                query_desc = ", ".join(f'"{q}"' for q in queries)
                print(f"\n  [footage] segment #{i} (\"{segment['text'][:40]}...\") needs {deficit} more "
                      f"distinct clip(s) - queuing fetch for {query_desc} "
                      f"(attempt {fetch_attempt}/{MAX_FETCH_ATTEMPTS}) ...")
                all_queries.extend(queries)
                tried_queries_by_segment.setdefault(i, set()).update(q.lower() for q in queries)
            total_deficit = sum(deficit for _, deficit, _ in shortfalls)
            fetched = _auto_fetch_and_add(all_queries, min_count=total_deficit)
            # The search queries are steered away from avoid_imagery in
            # the prompt, but that's not a guarantee — check each
            # fetched clip's real (just-generated) description before
            # it's even eligible to be picked. A violating clip stays in
            # the shared library either way, just unused here.
            fresh_by_name = {c["filename"]: c for c in _load_manifest()["clips"]}
            violating = [p for p in fetched
                         if _clip_violates_avoid_list(fresh_by_name.get(p.name, {"filename": p.name}), avoid_imagery)]
            if violating:
                print(f"  [footage] {len(violating)} fetched clip(s) matched this channel's "
                      f"avoid list - added to the shared library but skipped this round.")
            if not fetched:
                print("  [footage] no usable results this attempt.")
            print(f"  [footage] rechecking relevance of the updated library "
                  f"(attempt {fetch_attempt}/{MAX_FETCH_ATTEMPTS}) ...")
            # Loop back to the full matching call instead of trusting the
            # fetch blindly — this is what actually verifies the new clips
            # are relevant (scored the same way as everything else, via
            # MATCH_CONFIDENCE_THRESHOLD) rather than assuming a stock
            # search result is automatically good enough. tried_queries_by_segment
            # steers next round's search_queries toward different angles
            # instead of repeating whatever didn't already work.
            continue

        if auto_fetch_available:
            # Spent all MAX_FETCH_ATTEMPTS fetch-and-recheck cycles and
            # segment(s) are still short - settle for fallback clips rather
            # than fetching indefinitely.
            print(f"\n  [footage] still short after {MAX_FETCH_ATTEMPTS} fetch attempt(s) for segment(s): "
                  + ", ".join(f"#{i} (needs {n} more)" for i, n, _ in shortfalls))
            for i, deficit, _ in shortfalls:
                while len(result[i]) < shot_counts[i]:
                    fallback = _pick_fallback(clips, used)
                    result[i].append(fallback)
                    used.add(fallback)
            return _finalize(result)

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
            return _finalize(result)

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
        return _finalize(result)


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
