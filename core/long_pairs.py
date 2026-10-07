"""
A long quiz's two versions, of which only one goes out (decision 078).

Every long quiz is made twice, answers as you go and answers at the end
(decision 047), so the owner can choose. Both are the same questions in
the same voice: publishing both is "the repeated posting of the same or
similar content", which YouTube's spam and inauthentic-content policies
penalise, on one channel or across several. So they're a pair:

- approving one sets the other aside: out of review and the queue, and
  not a discard, since nothing was wrong with it;
- approving the other later swaps them, until one has gone out;
- one never goes out once its other version has.

Which to approve is suggested by episode, alternating, so the two styles
build up comparable numbers on Insights.
"""

from __future__ import annotations

import json
from pathlib import Path

from core import gallery

AT_END = "at_end"
AFTER_EACH = "after_each"
LABELS = {AFTER_EACH: "Answers as you go", AT_END: "Answers at the end"}


def _sidecar(video_path: Path) -> dict:
    from pipeline import quiz
    try:
        data = json.loads(quiz.round_sidecar(Path(video_path)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if data.get("longform") else {}


def variant(video_path: Path) -> str:
    """AFTER_EACH or AT_END for a long quiz, "" for anything else."""
    return _sidecar(video_path).get("variant", "") if gallery.is_long(video_path) else ""


def partner(video_path: Path):
    """The other version of this long quiz, if it exists; else None."""
    from pipeline.longform import AT_END_SUFFIX
    video_path = Path(video_path)
    if not variant(video_path):
        return None
    stem = video_path.stem
    other = stem[:-len(AT_END_SUFFIX)] if stem.endswith(AT_END_SUFFIX) else stem + AT_END_SUFFIX
    path = video_path.with_name(other + video_path.suffix)
    return path if path.exists() and variant(path) else None


def suggested(video_path: Path) -> str:
    """The version to publish for this episode: answers as you go on odd
    episodes, at the end on even ones, so both styles get measured."""
    episode = int(_sidecar(video_path).get("episode") or 1)
    return AFTER_EACH if episode % 2 else AT_END


def note(video_path: Path) -> str:
    """A line for Review: what this version is, and what approving it does."""
    mine = variant(video_path)
    other = partner(video_path)
    if not mine or other is None:
        return ""
    info = gallery.load_publish_info(other)
    if gallery.is_out(info):
        return f"{LABELS[mine]}. The other version has already gone out, so this one can't."
    hint = (" Suggested for this episode: the two styles alternate, so Insights can compare them."
            if suggested(video_path) == mine else
            f" The suggestion for this episode is the other version ({LABELS[suggested(video_path)].lower()}),"
            " so the two styles alternate and can be compared.")
    return (f"{LABELS[mine]}. Approving it sets the other version aside (not a discard, and never "
            f"published); approving that one later swaps them.{hint}")


def compare(videos: list) -> list:
    """For Insights: published long quizzes by style, with their audience.
    `videos` as gallery.list_videos gives them, with a "path"."""
    rows = {AFTER_EACH: [], AT_END: []}
    for v in videos:
        kind = variant(v["path"])
        if kind and v.get("published"):
            rows[kind].append(v.get("stats") or {})

    def mean(stats, key):
        values = [s[key] for s in stats if isinstance(s.get(key), (int, float))]
        return round(sum(values) / len(values), 1) if values else None

    return [{"variant": k, "label": LABELS[k], "videos": len(stats), "views": mean(stats, "views"),
             "avg_view_percent": mean(stats, "avg_view_percent"),
             "avg_view_minutes": (round(mean(stats, "avg_view_seconds") / 60, 1)
                                  if mean(stats, "avg_view_seconds") is not None else None)}
            for k, stats in rows.items()]
