"""
Matching script segments to footage.

The shape of the problem: every shot in a video needs a distinct clip
that genuinely depicts what's being said at that moment. Matching is
semantic — done by reading natural-language clip descriptions, not by
tag overlap, which was tried first and fails on synonyms ("sunshine"
tagged, "sunlight" searched, no match, no signal they're related).

What changed here is what the model is asked to read. It used to receive
every description in the library on every call: ~52,000 input tokens
against 264 clips, re-sent on each retry round and on every subsequent
video, growing on its own because auto-fetch adds clips unattended. Now
a lexical index (see retrieval.py) narrows the field to ~50 plausible
candidates first, and the model does what it's actually good at — judging
which of those genuinely fit — over a prompt whose size no longer depends
on how big the library has grown.

What the model is asked to JUDGE changed too. The old rubric demanded a
clip "actually depict the segment's specific subject" and called anything
matching only theme or mood "a MISS". For reflective narration there is
no depictable subject — you cannot film integrity — so by its own rules
almost everything scored 1-4, and the confidence bar was lowered (7, then
6, then 5) to compensate. That was the rubric being fought rather than
fixed.

Segments now arrive with a shot brief: a literal, filmable sentence
describing what should be on screen, produced by the script generator
while it still has the passage in front of it. The rubric scores against
that brief, asking only "would a competent editor cut to this here", and
penalises contradiction and inertness rather than abstraction. See
docs/decisions/012-shot-briefs.md.

The bar stays at 5, but it now means something different: under this
rubric 5-6 is "right feeling, nothing works against the line", which is
where most usable b-roll genuinely sits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from core import job_context
from core.errors import ExternalServiceError, FootageLibraryError, PipelineError
from core.logging_setup import get_logger
from core.paths import CACHE_DIR, LIBRARY_DIR
from pipeline import llm
from pipeline.footage import enrich, intake, retrieval, sources, store

log = get_logger(__name__)

# Below this, a candidate is treated as no match at all rather than a
# weak one. Forcing an explicit numeric self-rating and filtering on it
# in code is a real mechanism — stronger prompt wording alone left the
# model free to call a loosely-related clip "good enough".
MATCH_CONFIDENCE_THRESHOLD = 5

# At or below this, the model called a clip "actively wrong" for the
# segment. A shortfall fill never uses such a clip, however short it is.
FALLBACK_REJECT_AT_OR_BELOW = 2

# Fetch-and-recheck rounds per video before settling for fallbacks.
MAX_FETCH_ATTEMPTS = 3

# Results per site per query. Diversity comes from issuing several
# DISTINCT queries, not from fetching one broad query deeply — one query
# fetched at volume collapses into near-duplicates of itself, which is
# what produced "20 videos of calm water" for a single shortfall.
FETCH_PER_SITE_PER_QUERY = 2

# Downloads run concurrently; this is network-bound waiting, not local
# CPU, so the pool is wide. Still bounded — Pexels and Pixabay are free
# tiers and an unbounded burst trips their rate limiting, which surfaces
# as failures rather than speed.
FETCH_MAX_WORKERS = 16

# One round's download cap. Combining every shortfalled segment's queries
# into a single round is what stopped fetches running sequentially per
# segment, but uncapped it produced a real run with 36 simultaneous
# downloads — more than is reasonable work for one round or fits in the
# UI. A capped round that comes up short simply tries again with
# different terms.
MAX_CANDIDATES_PER_ROUND = 12

# How alike two clips may look before they count as a poor pair to run
# back to back. Deliberately looser than the duplicate threshold (6 bits
# of 64): those are the same clip, these merely look the same, and
# cutting between two shots that look the same reads as a mistake even
# when they are genuinely different footage.
SIMILAR_LOOK_BITS = 14

# Raw downloads land here and are deleted as soon as they've been
# normalized into the library. Under cache/ rather than footage/ because
# nothing here is worth keeping or backing up.
RAW_DOWNLOAD_DIR = CACHE_DIR / "downloads"

# Room for reasoning AND the answer, since both come out of max_tokens.
# One call per round over ~50 clips is the most demanding thing this
# pipeline asks for.
MATCH_MAX_TOKENS = 12000
MATCH_EFFORT = "medium"

MATCH_SYSTEM_ROLE = (
    "You match short video script segments to stock footage clips by visual and "
    "thematic meaning."
)

SCORING_RUBRIC = """
Each segment comes with a SHOT BRIEF: what should be on screen while that
line is spoken. Score each candidate clip 1-10 on one question only:

    Would a competent video editor cut to this clip here?

- 9-10: essentially the briefed shot, or a better version of it.
- 7-8: shows the brief's subject or a clear equivalent, differing only in
  incidental detail — setting, framing, time of day, who is in it.
- 5-6: not the briefed shot, but the right feeling, and nothing in it
  works against the line being spoken. Ordinary, usable background
  footage. Most good b-roll lives here.
- 3-4: harmless but inert. Nothing wrong with it; it adds nothing and
  would leave the viewer wondering why this shot was chosen.
- 1-2: actively wrong. It contradicts the words, breaks the tone, is
  distractingly busy under quiet narration, or shows something that would
  read as a mistake.

Two things this rubric deliberately does NOT penalise.

Abstraction. A line about doubt or forgiveness has no literal subject to
depict, and demanding one would mean nothing ever scores. Background
footage carries mood; the shot brief already did the work of turning the
idea into an image. Judge against the brief, not against the sentence.

Familiarity. A calm ocean under a calm line is not a failure of
imagination, it is an editor making an easy correct choice. Score what
works on screen, not what is inventive.

What to be strict about is contradiction and inertness. A clip that fights
the narration belongs at 1-2 however pretty it is, and a clip nobody would
notice belongs at 3-4 however inoffensive.

A clip can only be used ONCE in the whole video. If an earlier segment
claims a clip, a later one cannot reuse it — so list every plausible fit
with its honest score, not just your favourite, or a later segment is left
with nothing.

Leaving a segment short is the correct outcome when the candidates
genuinely do not work. Any shortfall is filled by fetching real footage,
so there is no reason to inflate a score to pad a list.

Always include "search_queries": 2-3 SHORT phrases (1-3 words) that would
find the briefed shot on a stock footage site. Take them from the brief,
not from the spoken line. For a brief about open hands in window light
that is ["open hands", "palms up", "window light"] - literal, visual,
the kind of thing a clip would actually be tagged with. Never search on
abstractions like "hope" or "integrity"; no stock library is tagged that
way and the results come back unusable.
""".strip()

MATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_index": {"type": "integer"},
                    "matches": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "filename": {"type": "string"},
                                "confidence": {"type": "integer"},
                            },
                            "required": ["filename", "confidence"],
                            "additionalProperties": False,
                        },
                    },
                    "search_queries": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["segment_index", "matches", "search_queries"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["picks"],
    "additionalProperties": False,
}

FOOTAGE_STEPS = ("queued", "downloading", "normalizing", "analyzing", "done")


@dataclass
class Shortfall:
    segment_index: int
    needed: int
    queries: list = field(default_factory=list)


@dataclass
class MatchOutcome:
    """What the matcher produced, including what it couldn't.

    `repeated` and `shortfalls` are returned rather than logged and
    forgotten. A video containing repeated footage is exactly the
    mass-production signal that puts monetization at risk, so the caller
    surfaces it on the finished video instead of burying it in a log
    nobody opens.
    """

    picks: list                      # list[list[str]] — filenames per segment
    repeated: bool = False
    # True when clips were chosen without scoring, because the scoring
    # call failed. The video still renders; it just says so.
    degraded: bool = False
    shortfalls: list = field(default_factory=list)
    # Shots filled after fetching ran out, without a score at or above the
    # bar. See _fill_fallbacks.
    unconfident: int = 0


def _clip_block(clips: list) -> str:
    """The candidate descriptions, sorted by filename.

    Sorted rather than in relevance order so the prompt is deterministic
    for a given shortlist; the model reads and scores all of them
    regardless of position.
    """
    return "\n".join(f"- {c.filename}: {c.description}" for c in sorted(clips, key=lambda c: c.filename))


def _segment_block(segments, shot_counts, tried_queries: dict) -> str:
    lines = []
    for i, (segment, count) in enumerate(zip(segments, shot_counts)):
        line = (f'{i}. "{segment.text}" (keywords: {", ".join(segment.keywords)}) '
                f'- needs {count} distinct clip{"s" if count != 1 else ""}')
        tried = tried_queries.get(i)
        if tried:
            line += (f' [already searched without enough good matches: {", ".join(sorted(tried))}'
                     f' — try different angles this time, not these]')
        lines.append(line)
    return "\n".join(lines)


def _avoid_block(avoid_imagery: list) -> str:
    if not avoid_imagery:
        return ""
    return f"""

IMPORTANT — this channel must never show: {", ".join(avoid_imagery)}. This
overrides everything else: a clip is disqualified the moment its imagery relates
to any of these, however strong a thematic fit it otherwise is. A clip that is
specifically excluded-kind devotional imagery does NOT fit a segment about
"prayer" or "devotion" in general — the specific excluded imagery always loses to
the general theme. Keep "search_queries" away from these too."""


def _run_match(segments, shot_counts, clips, avoid_imagery, tried_queries) -> dict:
    """One matching call.

    Not prompt-cached. It was, on the theory that the candidate block
    repeats across a video's fetch rounds, but it doesn't: every round
    re-shortlists against a library that has just grown, and every video
    shortlists differently. Across a month of real runs the cache was
    written 26 times and read zero, so marking it cacheable only added
    the 25% cache-write premium to every call. The role and rubric alone
    are too short to cache. See decision 027.
    """
    stable = llm.SystemBlock(
        f"{MATCH_SYSTEM_ROLE}\n\n{SCORING_RUBRIC}\n\n"
        f"Available footage (filename: description):\n{_clip_block(clips)}",
    )
    user_msg = (
        "Here are the segments of a short video script, in order. Each segment's "
        "footage is shown in several-second chunks, so a segment needing more than "
        "one clip should get several DIFFERENT clips in sequence, never one repeated:\n"
        f"{_segment_block(segments, shot_counts, tried_queries)}"
        f"{_avoid_block(avoid_imagery)}"
    )
    # A generous ceiling and a real effort level. Scoring fifty clips
    # against several segments is genuine judgement, and thinking is
    # billed out of the same budget as the answer - the previous 3000
    # was consumed entirely by reasoning, returning no text at all.
    return llm.call_json(
        [stable], user_msg, MATCH_SCHEMA,
        operation="footage_match",
        max_tokens=MATCH_MAX_TOKENS, effort=MATCH_EFFORT,
    )


def _looks_like(a, b) -> bool:
    """Whether two clips would read as the same shot on screen.

    Uses the perceptual hashes already stored for duplicate detection —
    no extra work, no extra data. Compares the mean distance across
    sampled frames rather than requiring every frame to match, because
    the question here is "do these look alike" rather than "are these the
    same file".
    """
    if not a.frame_hashes or not b.frame_hashes:
        return False
    pairs = list(zip(a.frame_hashes, b.frame_hashes))
    if not pairs:
        return False
    distance = sum(intake.hamming(x, y) for x, y in pairs) / len(pairs)
    return distance <= SIMILAR_LOOK_BITS


def _too_alike(candidate, previous) -> bool:
    """Would this clip be a poor thing to cut to after `previous`?

    Two tests, either of which is enough. Subject equality catches
    semantic repetition once the library is enriched — two different
    ocean clips in a row still reads as one long ocean shot. The
    perceptual check catches visual repetition and works with no
    enrichment at all.
    """
    if previous is None:
        return False
    if candidate.subject and candidate.subject == previous.subject:
        return True
    return _looks_like(candidate, previous)


def _select(data: dict, segments, shot_counts, available: dict, used: set) -> tuple:
    """Turn the model's scored candidates into concrete picks.

    Anything the model itself rated below the bar is dropped before it's
    considered. Sorting by confidence defensively guards against the
    model's stated ranking disagreeing with its own numbers.
    """
    picks = {p["segment_index"]: p for p in data.get("picks", [])}
    result = [[] for _ in segments]
    shortfalls = []
    # Carried across segments, not reset per segment: the last shot of one
    # segment runs straight into the first of the next.
    previous = None

    for i in range(len(segments)):
        needed = shot_counts[i]
        pick = picks.get(i) or {}
        confident = sorted(
            (m for m in (pick.get("matches") or [])
             if isinstance(m, dict) and (m.get("confidence") or 0) >= MATCH_CONFIDENCE_THRESHOLD),
            key=lambda m: m.get("confidence", 0),
            reverse=True,
        )
        # Take the best-scoring clip that isn't too like the one before
        # it, falling back to score order if every candidate is similar.
        # Consecutive shots that look alike undo the point of cutting.
        for match in confident:
            if len(result[i]) >= needed:
                break
            name = match.get("filename")
            if name not in available or name in used:
                continue
            candidate = available[name]
            if _too_alike(candidate, previous) and any(
                    m.get("filename") in available and m.get("filename") not in used
                    and not _too_alike(available[m["filename"]], previous)
                    for m in confident):
                continue
            result[i].append(name)
            used.add(name)
            previous = candidate

        deficit = needed - len(result[i])
        if deficit > 0:
            queries = pick.get("search_queries") or list(segments[i].keywords) or ["stock footage"]
            shortfalls.append(Shortfall(i, deficit, queries))

    return result, shortfalls


def _round_robin(by_query: dict, cap: int) -> list:
    """Take one candidate from each query, then a second from each, until
    the cap.

    Round-robin rather than first-come: several shortfalled segments'
    queries are combined into one round, and taking them in order would
    let whichever segment's queries were built first consume the entire
    round while the others got nothing.
    """
    chosen = []
    queries = list(by_query)
    depth = 0
    while len(chosen) < cap:
        added = False
        for query in queries:
            if len(chosen) >= cap:
                break
            bucket = by_query[query]
            if depth < len(bucket):
                chosen.append(bucket[depth])
                added = True
        if not added:
            break
        depth += 1
    return chosen


def _fetch_and_add(queries: list) -> list:
    """Search, download, normalize and describe new footage for a set of
    queries. Returns the clips actually added.

    Download and normalize run concurrently (independent network and
    ffmpeg work). Describing and recording stay sequential: that phase
    reads the library to check for duplicates and then writes to it, so
    running it in parallel would let two clips from the same batch each
    miss the other and both be added.
    """
    queries = [q.strip() for q in queries if q and q.strip()] or ["stock footage"]
    RAW_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

    by_query = {}
    for query in queries:
        hits = sources.search_all(query, FETCH_PER_SITE_PER_QUERY)
        if not hits:
            log.info(f'  [footage] no stock results for "{query}".')
            continue
        slug = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_") or "clip"
        by_query[query] = [(hit, f"{slug}_auto{i}.mp4") for i, hit in enumerate(hits, 1)]

    candidates = _round_robin(by_query, MAX_CANDIDATES_PER_ROUND)
    if not candidates:
        return []

    # Each round replaces the progress panel's clip list rather than
    # appending — a previous round's rows aren't live any more.
    job_context.report_detail("footage", None,
                              {"items": [], "total_candidates": len(candidates)})
    for index, (hit, dest_name) in enumerate(candidates):
        job_context.report_detail("footage", index, {
            "query": hit.query, "filename": dest_name, "step": "queued",
        })

    def fetch_one(indexed):
        """Download, normalize straight into the library, drop the raw file.

        This used to leave three copies of every fetched clip on disk —
        the raw download in old_downloads/, the cropped copy in
        normalized/, and the library copy that is the only one anything
        reads. Nothing ever cleaned the first two up, and on this
        project's own library they had grown to 19 GB of files no code
        opens. The raw file is also the least worth keeping: its source
        URL is recorded, so it is one HTTP request away if it is ever
        wanted again.
        """
        index, (hit, dest_name) = indexed
        raw_path = RAW_DOWNLOAD_DIR / dest_name
        library_path = LIBRARY_DIR / dest_name
        try:
            job_context.report_detail("footage", index, {"step": "downloading"})
            log.info(f'  [footage] downloading "{dest_name}" for "{hit.query}"')
            sources.download(hit.url, raw_path)
            job_context.report_detail("footage", index, {"step": "normalizing"})
            intake.normalize(raw_path, library_path)
            return index, hit, dest_name, library_path, None
        except Exception as exc:  # noqa: BLE001 - one bad clip must not fail the render
            job_context.report_detail("footage", index, {"step": "failed"})
            return index, hit, dest_name, None, exc
        finally:
            raw_path.unlink(missing_ok=True)

    fetched = job_context.parallel_map(fetch_one, list(enumerate(candidates)),
                                       max_workers=FETCH_MAX_WORKERS)

    added = []
    for index, hit, dest_name, normalized_path, error in fetched:
        if error is not None:
            log.info(f'  [footage] skipped one clip for "{hit.query}": {error}')
            continue
        job_context.report_detail("footage", index, {"step": "analyzing"})
        try:
            license_text, verified = store.license_for_source(hit.source)
            clip = intake.add_normalized_clip(
                normalized_path, dest_name=dest_name,
                source=f'{hit.source}: {hit.url}',
                license_text=license_text, license_verified=verified,
            )
            job_context.report_detail("footage", index, {"step": "done"})
            if clip not in added:
                added.append(clip)
        except Exception as exc:  # noqa: BLE001
            job_context.report_detail("footage", index, {"step": "failed"})
            log.info(f'  [footage] couldn\'t add one clip for "{hit.query}": {exc}')

    _enrich_new(added)
    return added


def _enrich_new(clips: list) -> None:
    """Give freshly fetched clips their subject, setting and the rest
    before the re-score that's about to read them.

    Enrichment used to happen only when someone ran `manage_library.py
    enrich`, so every clip fetched since the last run had no subject. That
    was a quarter of the library, and the newest quarter: the 8x subject
    weighting in the shortlist and the "never cut between two shots of the
    same subject" check did nothing for exactly the clips fetched for
    recent videos. One text call per round covers every clip it added.

    Failing here costs the enrichment, not the render: an unenriched clip
    still matches on its prose, and the next `enrich` run picks it up.
    """
    pending = [c for c in clips if not c.enriched]
    if not pending:
        return
    try:
        enrich.enrich_batch(pending)
    except PipelineError as exc:
        log.warning(f"  [footage] couldn't enrich {len(pending)} new clip(s) ({exc}); "
                    f"they'll match on description alone until the next enrich run.")


def assign_clips(segments, shot_counts, avoid_imagery=None) -> MatchOutcome:
    """Pick one distinct clip per shot.

    `shot_counts[i]` is how many clips segment i needs. Every clip across
    the whole result is distinct, except in the last-resort case where
    the library is smaller than the video needs — which sets
    `repeated` so the caller can surface it.

    Never prompts. The old version asked on stdin whether to pause and
    add footage, which meant threading an `interactive` flag down three
    layers so background jobs wouldn't hang on a terminal that isn't
    there. Shortfalls come back in the result and the caller decides.
    """
    avoid_imagery = list(avoid_imagery or [])
    tried_queries = {}

    job_context.report_detail("footage", None, {"total_shots": sum(shot_counts)})

    cached = _load_checkpoint(shot_counts)
    if cached is not None:
        return cached

    if store.count() == 0:
        raise FootageLibraryError(
            "the footage library is empty",
            user_message=("The footage library has no clips yet. Add some with "
                          "`python tools/manage_library.py add <file>` before generating a video."),
        )

    for attempt in range(MAX_FETCH_ATTEMPTS + 1):
        clips = retrieval.shortlist(segments, avoid_imagery)
        if not clips:
            raise FootageLibraryError(
                "no usable clips after filtering",
                user_message=("Every clip in the footage library is excluded by this channel's "
                              "avoid-imagery list. Loosen the list or add more footage."),
            )

        log.info(f"  [footage] scoring {len(clips)} candidate clip(s) "
                 f"against {len(segments)} segment(s)...")
        try:
            data = _run_match(segments, shot_counts, clips, avoid_imagery, tried_queries)
        except (llm.TruncatedResponse, llm.RefusedResponse, ExternalServiceError) as exc:
            # The script and the voiceover are already paid for and sitting
            # on disk. Losing them because the scoring call failed would be
            # the most expensive possible response to a recoverable
            # problem, so fall back to the same recency-ordered picks used
            # when the library simply can't cover a video. The result is a
            # weaker video, flagged as such, rather than no video.
            log.warning(f"  [footage] scoring failed ({exc}). Falling back to "
                        f"least-recently-used clips so the render can finish.")
            return _finalize(_degraded_picks(segments, shot_counts, avoid_imagery),
                             shot_counts)

        available = {c.filename: c for c in clips}
        used = set()
        picks, shortfalls = _select(data, segments, shot_counts, available, used)

        if not shortfalls:
            return _finalize(MatchOutcome(picks=picks), shot_counts)

        is_last = attempt >= MAX_FETCH_ATTEMPTS
        if is_last or not sources.any_key_configured():
            return _finalize(_fill_fallbacks(picks, shortfalls, shot_counts, avoid_imagery,
                                             used, segments=segments, data=data,
                                             available=available),
                             shot_counts)

        job_context.report_detail("footage", None,
                                  {"round": attempt + 1, "total_rounds": MAX_FETCH_ATTEMPTS})
        all_queries = []
        for shortfall in shortfalls:
            segment = segments[shortfall.segment_index]
            log.info(f'  [footage] segment #{shortfall.segment_index} '
                     f'("{segment.text[:40]}...") needs {shortfall.needed} more clip(s) — '
                     f'fetching {", ".join(shortfall.queries)} '
                     f'(round {attempt + 1}/{MAX_FETCH_ATTEMPTS})')
            all_queries.extend(shortfall.queries)
            tried_queries.setdefault(shortfall.segment_index, set()).update(
                q.lower() for q in shortfall.queries)

        # One combined fetch for every shortfalled segment, not one per
        # segment: the next matching call re-scores the whole shortlist
        # against every segment regardless of which segment's shortfall
        # requested which query, so keeping fetches segment-scoped only
        # bought extra sequential round-trips.
        added = _fetch_and_add(all_queries)
        if not added:
            log.info("  [footage] nothing usable found this round.")
        log.info(f"  [footage] rechecking relevance of the updated library "
                 f"(round {attempt + 1}/{MAX_FETCH_ATTEMPTS})...")

    # Unreachable: the loop always returns. Present so a future edit that
    # breaks that invariant fails loudly instead of returning None.
    raise FootageLibraryError("footage matching ended without a result")


def _degraded_picks(segments, shot_counts, avoid_imagery) -> MatchOutcome:
    """Fill every shot from the shortlist, unscored.

    Used when the scoring call itself fails. Clips still come from the
    lexical shortlist, so they are at least topically plausible - this is
    "unranked" rather than "random". `degraded` is set so the finished
    video says so instead of quietly looking like a normal one.
    """
    used = set()
    picks = [[] for _ in segments]
    repeated = False

    for i, count in enumerate(shot_counts):
        while len(picks[i]) < count:
            candidates = retrieval.shortlist(
                [segments[i]], avoid_imagery, max_clips=1, exclude=used)
            if not candidates:
                candidates = [c for c in store.least_recently_used(len(used) + 20, exclude=used)
                              if not retrieval.clip_violates_avoid_list(c, avoid_imagery)]
            if candidates:
                picks[i].append(candidates[0].filename)
                used.add(candidates[0].filename)
                continue

            any_clip = store.least_recently_used(1)
            if not any_clip:
                raise FootageLibraryError(
                    "no clips available at all",
                    user_message="The footage library is empty.",
                )
            picks[i].append(any_clip[0].filename)
            repeated = True

    return MatchOutcome(picks=picks, repeated=repeated, degraded=True)


def _fill_fallbacks(picks, shortfalls, shot_counts, avoid_imagery, used,
                    segments=None, data=None, available=None) -> MatchOutcome:
    """Top up whatever is still short once fetching has run out of rounds.

    This used to go straight to the least-recently-used clips in the
    whole library, which for these purposes is random: nothing tied them
    to the line being spoken, nothing said it had happened, and it is how
    a line about a crowd in Jerusalem got an elephant procession. Now the
    best of what's left is used first, in order:

    1. The model's own runners-up for this segment: clips it scored 3-4,
       "harmless but inert", already judged against this brief.
    2. This segment's lexical shortlist, minus anything the model scored
       1-2 ("actively wrong") for it.
    3. Least-recently-used, as before, only when both are exhausted.

    Every shot filled here is counted in `unconfident`, which reaches the
    review screen: the video didn't fail, but nobody vouched for those
    shots. `repeated` is still set if the library is smaller than the
    video and a clip has to appear twice.
    """
    summary = ", ".join(f"#{s.segment_index} (needs {s.needed} more)" for s in shortfalls)
    log.warning(f"  [footage] still short after fetching for segment(s): {summary}")

    scored = {p.get("segment_index"): p for p in (data or {}).get("picks", [])}
    available = available or {}
    repeated = False
    unconfident = 0

    def take(i, name):
        nonlocal unconfident
        picks[i].append(name)
        used.add(name)
        unconfident += 1

    for shortfall in shortfalls:
        i = shortfall.segment_index
        matches = [m for m in (scored.get(i) or {}).get("matches") or [] if isinstance(m, dict)]
        rejected = {m.get("filename") for m in matches
                    if (m.get("confidence") or 0) <= FALLBACK_REJECT_AT_OR_BELOW}

        runners_up = sorted(
            (m for m in matches
             if FALLBACK_REJECT_AT_OR_BELOW < (m.get("confidence") or 0) < MATCH_CONFIDENCE_THRESHOLD),
            key=lambda m: m.get("confidence", 0), reverse=True)
        for match in runners_up:
            if len(picks[i]) >= shot_counts[i]:
                break
            name = match.get("filename")
            if name in available and name not in used:
                take(i, name)

        while len(picks[i]) < shot_counts[i] and segments is not None:
            candidates = retrieval.shortlist(
                [segments[i]], avoid_imagery, max_clips=1, exclude=used | rejected)
            if not candidates:
                break
            take(i, candidates[0].filename)

        while len(picks[i]) < shot_counts[i]:
            # Least-recently-used, skipping anything already claimed in
            # this video and anything this channel must not show.
            candidates = [
                c for c in store.least_recently_used(len(used) + 20, exclude=used | rejected)
                if not retrieval.clip_violates_avoid_list(c, avoid_imagery)
            ]
            if candidates:
                take(i, candidates[0].filename)
                continue

            # Nothing unused left: the library is smaller than this one
            # video needs, so a clip has to appear twice.
            any_clip = store.least_recently_used(1)
            if not any_clip:
                raise FootageLibraryError(
                    "no clips available at all",
                    user_message="The footage library is empty.",
                )
            picks[i].append(any_clip[0].filename)
            unconfident += 1
            repeated = True
            log.warning("  [footage] library exhausted for this video — a clip will repeat.")

    log.warning(f"  [footage] {unconfident} shot(s) filled without a confident match.")
    return MatchOutcome(picks=picks, repeated=repeated, shortfalls=shortfalls,
                        unconfident=unconfident)


def _finalize(outcome: MatchOutcome, shot_counts) -> MatchOutcome:
    try:
        job_context.save_json_checkpoint("footage_picks", {
            "shot_counts": list(shot_counts),
            "picks": outcome.picks,
            "repeated": outcome.repeated,
            "degraded": outcome.degraded,
            "unconfident": outcome.unconfident,
        })
    except Exception:  # noqa: BLE001 - checkpointing is best-effort
        pass
    return outcome


def _load_checkpoint(shot_counts):
    """Reuse a previous attempt's picks after an interruption — but only
    if the script still has the same shape AND every clip still exists.
    A stale checkpoint from a differently-shaped script must never be
    trusted."""
    cached = job_context.load_json_checkpoint("footage_picks")
    if not cached or cached.get("shot_counts") != list(shot_counts):
        return None
    names = {name for group in cached["picks"] for name in group}
    if not all((LIBRARY_DIR / name).exists() for name in names):
        return None
    log.info("  [footage] reusing previously matched footage (resumed).")
    return MatchOutcome(picks=cached["picks"], repeated=cached.get("repeated", False),
                        degraded=cached.get("degraded", False),
                        unconfident=cached.get("unconfident", 0))


def mark_used(filenames) -> None:
    """One write for the whole video (see store.mark_used)."""
    store.mark_used(filenames)
