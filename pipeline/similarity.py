"""
Catching generated scripts that are drifting toward reworded copies of
earlier ones.

This is the highest-ranked lever in the project's own policy notes and
was never built. It matters because the whole monetization case rests on
originality: YouTube's reused-content rules single out "AI-generated
content made with generic or unoriginal templates giving the impression
of mass production", and a pipeline generating from the same style prompt
forever will converge on its own house phrasing long before a human
watching one video at a time would notice.

Two measures, because they catch different failures:

  - **Word-trigram overlap** catches near-verbatim reuse. Whole phrases
    reappearing is the obvious version of the problem.
  - **Content-word cosine** catches paraphrase. A script that says the
    same things in a different order shares few trigrams but nearly all
    of its vocabulary, and that's the version that creeps in gradually.

Deliberately pure Python with no embedding model or API call. This runs
on every generated script, and it only has to answer "is this suspiciously
like something already published on this channel" — a question lexical
measures answer well and cheaply. It reports; it never blocks. The point
is that a human sees the flag at review time.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.logging_setup import get_logger
from core.paths import SCRIPT_HISTORY_PATH

log = get_logger(__name__)

# Above either of these against any single earlier script, the new script
# is flagged for a human look. Chosen to be quiet in normal use: two
# genuinely different reflections on different verses land well below,
# while a reworded retread of an earlier one clears them.
TRIGRAM_THRESHOLD = 0.28
COSINE_THRESHOLD = 0.62

# How many recent scripts per channel to compare against and keep. Old
# enough scripts stop being a plagiarism risk against each other and the
# file shouldn't grow without limit.
HISTORY_LIMIT = 200

STOPWORDS = frozenset("""
a an and are as at be been being but by can could did do does for from
had has have he her his how i if in into is it its me my no not of on
one or our out she should so than that the their them then there these
they this those to too us was we were what when where which who will
with would you your
""".split())

_WORD_RE = re.compile(r"[a-z0-9']+")


@dataclass
class SimilarityReport:
    """`flagged` is what the UI shows. `closest_title` names the earlier
    script it resembles, because "this is 71% similar to something" is
    not actionable without knowing to what."""

    max_trigram: float = 0.0
    max_cosine: float = 0.0
    closest_title: str = None
    flagged: bool = False
    compared_against: int = 0
    # The closest earlier script's own words, so a rewrite can be told
    # what to steer away from rather than just that it's too close.
    closest_text: str = ""
    # How far past the nearer threshold the closest script is: 1.0 is
    # exactly at the flag line. One number, so two candidate scripts can
    # be compared to see which is more original.
    exceedance: float = 0.0

    @property
    def summary(self) -> str:
        if not self.flagged:
            return "No close matches in this channel's history."
        return (f'Similar to "{self.closest_title}" '
                f"({self.max_trigram:.0%} phrase overlap, {self.max_cosine:.0%} wording overlap). "
                f"Worth a read before publishing.")


def _words(text: str) -> list:
    return [w for w in _WORD_RE.findall((text or "").lower()) if w not in STOPWORDS]


def _trigrams(words: list) -> set:
    return {tuple(words[i:i + 3]) for i in range(len(words) - 2)}


def trigram_overlap(a_words: list, b_words: list) -> float:
    """Jaccard over word trigrams: shared phrases / all phrases."""
    a, b = _trigrams(a_words), _trigrams(b_words)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cosine(a_words: list, b_words: list) -> float:
    """Cosine over content-word frequencies — order-insensitive, so it
    sees through reordering and light paraphrase."""
    a, b = Counter(a_words), Counter(b_words)
    if not a or not b:
        return 0.0
    shared = set(a) & set(b)
    dot = sum(a[w] * b[w] for w in shared)
    if not dot:
        return 0.0
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    return dot / (norm_a * norm_b)


def script_text(script) -> str:
    """The generated prose only.

    For a quote channel, segment 0 is the source quote — someone else's
    words, identical every time that verse comes up, and not what this
    check is about. Including it would flag every repeated verse as
    self-plagiarism while hiding real drift in the analysis.
    """
    segments = script.segments
    if script.citation and segments:
        segments = segments[1:]
    return " ".join(s.text for s in segments)


def _load(path: Path = None) -> dict:
    path = Path(path or SCRIPT_HISTORY_PATH)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # A corrupt history file must not stop video generation — the
        # check is advisory. Losing it degrades to "no history yet".
        log.warning("  [similarity] script history unreadable; starting a fresh one.")
        return {}


def _save(history: dict, path: Path = None) -> None:
    path = Path(path or SCRIPT_HISTORY_PATH)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except OSError:
        log.warning("  [similarity] couldn't write script history.")


def check(channel_key: str, script, path: Path = None) -> SimilarityReport:
    """Compare against this channel's earlier scripts. Read-only."""
    history = _load(path).get(channel_key, [])
    words = _words(script_text(script))
    report = SimilarityReport(compared_against=len(history))
    if not words or not history:
        return report

    # Rank candidates by how far each measure exceeds its own threshold,
    # so the named script is the one a person would actually call the
    # closest — not merely whichever happened to top one raw measure.
    best_exceedance = -1.0
    for entry in history:
        previous = _words(entry.get("text", ""))
        if not previous:
            continue
        tri = trigram_overlap(words, previous)
        cos = cosine(words, previous)
        report.max_trigram = max(report.max_trigram, tri)
        report.max_cosine = max(report.max_cosine, cos)

        exceedance = max(tri / TRIGRAM_THRESHOLD, cos / COSINE_THRESHOLD)
        if exceedance > best_exceedance:
            best_exceedance = exceedance
            report.closest_title = entry.get("title")
            report.closest_text = entry.get("text", "")

    report.exceedance = max(best_exceedance, 0.0)
    report.flagged = (report.max_trigram >= TRIGRAM_THRESHOLD
                      or report.max_cosine >= COSINE_THRESHOLD)
    return report


def cross_channel_report(path: Path = None) -> list:
    """How alike different channels' output has become.

    Distinct from `check`, which compares a script against its own
    channel's history. This asks a different question: whether two
    channels are converging on the same structure and vocabulary.

    That is the "mass production" risk rather than the plagiarism one —
    if every channel has the same rhythm, segment count and house
    phrasing, the pattern reads as templated at volume no matter how good
    any single video is, and no per-channel check can see it because each
    channel is perfectly consistent with itself.

    Returns one entry per channel pair, most similar first.
    """
    history = _load(path)
    channels = {key: entries for key, entries in history.items() if entries}
    if len(channels) < 2:
        return []

    # A channel's own vocabulary, pooled across its recent scripts.
    vocab = {key: _words(" ".join(e.get("text", "") for e in entries[-40:]))
             for key, entries in channels.items()}
    # Structure: mean words per segment-set, as a crude shape signal.
    shape = {key: sum(len(_words(e.get("text", ""))) for e in entries[-40:]) / len(entries[-40:])
             for key, entries in channels.items()}

    keys = sorted(channels)
    out = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            out.append({
                "channels": (a, b),
                "vocabulary_overlap": cosine(vocab[a], vocab[b]),
                "phrase_overlap": trigram_overlap(vocab[a], vocab[b]),
                "length_ratio": (min(shape[a], shape[b]) / max(shape[a], shape[b])
                                 if max(shape[a], shape[b]) else 1.0),
            })
    out.sort(key=lambda entry: -entry["vocabulary_overlap"])
    return out


def record(channel_key: str, title: str, script, path: Path = None) -> None:
    """Add a script to the history, oldest entries dropped past the
    limit. Called after a successful render, so a failed attempt doesn't
    leave a phantom entry that later scripts get compared against."""
    history = _load(path)
    entries = history.setdefault(channel_key, [])
    entries.append({
        "title": title,
        "at": datetime.now(timezone.utc).isoformat(),
        "text": script_text(script),
    })
    history[channel_key] = entries[-HISTORY_LIMIT:]
    _save(history, path)
