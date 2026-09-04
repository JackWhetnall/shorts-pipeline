"""
Shortlisting: pick the ~50 clips worth showing the matcher, instead of
all of them.

This is the fix for the project's biggest running cost. The matcher sent
every clip description in the library to Claude on every call — ~52,000
input tokens against a 264-clip library, re-sent on each fetch-and-recheck
round and on every subsequent video. Because auto-fetch adds clips
unattended after most renders, the library grows on its own, so each
video was making every future video more expensive. Prompt caching (see
pipeline.llm) cuts the price of re-sending it; only shortlisting stops it
growing.

The retrieval is lexical (SQLite FTS5's BM25), not embeddings. That's a
deliberate choice: it needs no new service, no API key, no index to keep
warm, and no second thing that can be stale — and it doesn't have to be
precise, because it isn't making the decision. It only has to get the
plausible candidates into a set of fifty that Claude then reads properly.
Recall matters here; precision is the model's job.

Two things keep recall honest. Each segment contributes its own top
matches rather than one query for the whole video, so a segment whose
subject is rare still gets its own candidates. And the shortlist is
topped up with least-recently-used clips, which both fills gaps when the
lexical query finds little and keeps some rotation in the pool.
"""

from __future__ import annotations

import re

from core.logging_setup import get_logger
from pipeline.footage import store

log = get_logger(__name__)

# Fifty descriptions is roughly 10k tokens — enough for the matcher to
# have real choice on every segment of a typical video, and about an
# eighth of what sending the whole library costs today. It's a cap on
# prompt size, not a limit on the library: the library can grow to
# thousands without this number moving.
MAX_SHORTLIST = 50
PER_SEGMENT = 14

# Added to a clip's BM25 rank for each time a video using it was discarded
# for its footage. BM25 ranks are negative and better when lower, so a
# positive penalty pushes a repeatedly-rejected clip down the list. Sized
# to be roughly one rank position per rejection — enough to matter over
# several, not enough for one to bury an otherwise perfect match.
REJECTION_PENALTY = 1.5

# Words that match half the library and carry no visual meaning. Kept
# deliberately short: an over-aggressive stoplist silently drops real
# query terms, and BM25 already discounts common words by document
# frequency.
STOPWORDS = frozenset("""
a an and are as at be been being but by can could did do does for from
had has have he her his how i if in into is it its me my no not of on
one or our out she should so than that the their them then there these
they this those to too us was we were what when where which who will
with would you your it's don't
""".split())

_WORD_RE = re.compile(r"[a-z0-9]+")


def _terms(text: str) -> list:
    """Content words, lowercased, deduped, order preserved. Short tokens
    go too — a two-letter fragment matches noise, not subjects."""
    seen = set()
    out = []
    for word in _WORD_RE.findall((text or "").lower()):
        if len(word) < 3 or word in STOPWORDS or word in seen:
            continue
        seen.add(word)
        out.append(word)
    return out


def build_query(segment) -> str:
    """An FTS5 OR-query for one segment.

    Built from the segment's shot brief and visual keywords — the literal
    "what should be on screen" — never from the spoken line. Both sides of
    the comparison are then concrete, which is the whole point.

    Keywords come first and are repeated once. FTS5 has no term-weight
    syntax, but a repeated term genuinely counts twice in BM25 scoring,
    which is the cheapest available way to say "these matter more than the
    incidental words in the brief".
    """
    keyword_terms = _terms(" ".join(segment.keywords or []))
    # The SHOT BRIEF, not the spoken line. Clip descriptions are literal
    # ("prayer beads on a polished table"); reflective narration is not.
    # Querying the spoken line was matching abstractions against concrete
    # text and finding nothing — measured at 63% of generated keywords
    # appearing in no clip description at all.
    keyword_set = set(keyword_terms)
    brief_terms = [t for t in _terms(segment.visual_text) if t not in keyword_set]
    terms = keyword_terms + keyword_terms + brief_terms
    if not terms:
        return ""
    # Each term quoted so FTS5 reads it as a literal, never as an
    # operator — a segment containing the word "or" or "near" would
    # otherwise change the query's meaning.
    return " OR ".join(f'"{t}"' for t in terms)


def clip_violates_avoid_list(clip, avoid_imagery) -> bool:
    """Whether a clip shows imagery this channel must never show.

    Checked against description and filename together, case-insensitively.
    The footage library is shared across channels, so a clip can be a
    strong thematic match and still be completely wrong for one audience
    — the real case this exists for is prayer imagery of the wrong
    religion scoring well on a segment about "prayer".
    """
    if not avoid_imagery:
        return False
    haystack = f"{clip.description} {clip.filename}".lower()
    return any(term.lower() in haystack for term in avoid_imagery)


def _search(conn, query: str, limit: int) -> list:
    """Weighted BM25 over subject, setting and description.

    The weights are what make this precise. A clip's description mentions
    everything incidentally visible — "a closed leather-bound Bible at the
    edge of frame" — so an unweighted match surfaces clips where the
    searched-for thing is a prop rather than the point of the shot.
    Weighting `subject` eight times the prose ranks a clip that IS the
    thing above one that merely contains it.

    `reject_count` nudges rankings too: a clip whose videos you keep
    discarding for their footage drifts down. A nudge, not a ban — one
    bad pairing doesn't make a clip bad.
    """
    if not query:
        return []
    try:
        rows = conn.execute(
            """
            SELECT c.*,
                   bm25(clips_fts, ?, ?, ?) + (c.reject_count * ?) AS rank
            FROM clips_fts
            JOIN clips c ON c.filename = clips_fts.filename
            WHERE clips_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (*store.FTS_WEIGHTS, REJECTION_PENALTY, query, limit),
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        # A malformed FTS expression must degrade to "no lexical hits",
        # not fail the render — the top-up below still produces a usable
        # shortlist. Logged rather than swallowed, because silently
        # returning nothing looks identical to a library with no relevant
        # footage in it.
        log.warning(f"  [footage] lexical search failed, falling back to recency: {exc}")
        return []
    return rows


def shortlist(segments, avoid_imagery=None, *, max_clips: int = MAX_SHORTLIST,
              per_segment: int = PER_SEGMENT, exclude: set = None,
              db_path=None) -> list:
    """The candidate clips to show the matcher, best-scoring first.

    Every segment contributes its own lexical matches; the union is
    deduplicated, filtered against the channel's avoid list, topped up
    with least-recently-used clips, and capped.

    `exclude` drops clips already claimed elsewhere in this video.
    """
    avoid_imagery = avoid_imagery or []
    exclude = set(exclude or ())

    ranked = {}     # filename -> best (lowest) bm25 rank seen
    clips = {}      # filename -> Clip

    with store.connect(db_path) as conn:
        for segment in segments:
            for row in _search(conn, build_query(segment), per_segment):
                name = row["filename"]
                if name in exclude:
                    continue
                clip = store._row_to_clip(row)
                if clip_violates_avoid_list(clip, avoid_imagery):
                    continue
                rank = row["rank"]
                if name not in ranked or rank < ranked[name]:
                    ranked[name] = rank
                clips[name] = clip

    selected = [clips[name] for name in sorted(ranked, key=lambda n: ranked[n])][:max_clips]

    if len(selected) < max_clips:
        already = {c.filename for c in selected} | exclude
        for clip in store.least_recently_used(max_clips * 2, exclude=already, db_path=db_path):
            if len(selected) >= max_clips:
                break
            if clip_violates_avoid_list(clip, avoid_imagery):
                continue
            selected.append(clip)

    return selected
