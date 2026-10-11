"""
Where viewers stopped watching a documentary, scene by scene, and what
the channel learns from it (decision 086).

YouTube's Analytics API gives a video's audience retention as a curve:
the share of viewers still watching at each hundredth of its length
(`audienceWatchRatio` by `elapsedVideoTimeRatio`). The documentary's
production sidecar records when each scene starts and ends, so a drop
in the curve can be put on the scene that was playing: "lost 18% during
scene 7". core.audience fetches the curve with the other figures; this
reads it, and once a film has a week of figures, turns its worst drops
and its click-through into a lesson or two for the channel's writers
(core.lessons), in one small model call.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from core.logging_setup import get_logger

log = get_logger(__name__)

LEARN_AFTER_DAYS = 7
TOP_DROPS = 3
LEARN_MODEL = "claude-haiku-4-5"


def _at(curve: list, ratio: float) -> float:
    """The watch ratio at `ratio` of the video, interpolated."""
    if not curve:
        return 0.0
    points = sorted((float(r), float(w)) for r, w, *_ in curve)
    if ratio <= points[0][0]:
        return points[0][1]
    for (r0, w0), (r1, w1) in zip(points, points[1:]):
        if r0 <= ratio <= r1:
            return w0 + (w1 - w0) * ((ratio - r0) / ((r1 - r0) or 1))
    return points[-1][1]


def scene_times(video_path: Path) -> list:
    sidecar = Path(video_path).with_name(f"{Path(video_path).stem}_production.json")
    try:
        return json.loads(sidecar.read_text(encoding="utf-8")).get("scenes") or []
    except (OSError, ValueError):
        return []


def summary(curve: list, times: list, seconds: float) -> dict:
    """{"kept_30s": %, "end": %, "drops": [{"scene", "at", "lost"}]}, or {}."""
    if not curve or not seconds:
        return {}
    out = {"kept_30s": round(100 * _at(curve, min(1.0, 30 / seconds))),
           "end": round(100 * _at(curve, 0.99))}
    drops = []
    for i, (start, end) in enumerate(times):
        lost = _at(curve, start / seconds) - _at(curve, min(1.0, end / seconds))
        # The first seconds always lose people who were only sampling; a
        # scene there counts only for what it loses beyond that.
        if start < 30 and i == 0:
            continue
        drops.append({"scene": i, "at": round(start), "lost": round(100 * lost, 1)})
    out["drops"] = sorted((d for d in drops if d["lost"] > 0), key=lambda d: -d["lost"])[:TOP_DROPS]
    return out


def for_video(video_path: Path) -> dict:
    """The video's retention summary from its stats sidecar, or {}."""
    from core import gallery
    stats = gallery.load_stats(video_path) or {}
    report = gallery.load_report(video_path) or {}
    return summary(stats.get("curve") or [], scene_times(video_path),
                   float(report.get("video_seconds") or 0))


LEARN = """
You help a YouTube documentary channel learn from its own viewers. You get
one film's numbers: where viewers stopped watching (with what was being
said and shown then), how many were still watching after thirty seconds,
and how often the thumbnail was clicked. Write one or two lessons for the
channel's writers: plain, specific instructions they can follow in the
next film ("Open on the most surprising fact, not on the setting: the
cold open lost 40% before it said what the film was about"). Only what
the numbers support; no generic advice. If nothing stands out, return no
lessons.
""".strip()


def learn(channel, video_path: Path) -> list:
    """Lessons from one film, added to the channel's list once. Returns
    the new lessons ([] if it's too early, already done, or nothing
    stands out)."""
    from core import gallery, lessons, production
    from pipeline.llm import call_json
    video_path = Path(video_path)
    info = gallery.load_publish_info(video_path)
    stats = gallery.load_stats(video_path) or {}
    if not stats.get("curve") or lessons.learned_from(channel.key, video_path.stem):
        return []
    published = info.get("published_at") or ""
    try:
        from datetime import datetime
        age = time.time() - datetime.fromisoformat(published).timestamp()
    except (TypeError, ValueError):
        return []
    if age < LEARN_AFTER_DAYS * 86400:
        return []
    found = for_video(video_path)
    sidecar = json.loads(video_path.with_name(f"{video_path.stem}_production.json").read_text(encoding="utf-8"))
    data = production.load(channel.key, sidecar["subtopic_id"])
    scenes = (data.get("script") or {}).get("scenes") or []
    lines = [f"Title: {info.get('title', '')}",
             f"Still watching after 30 seconds: {found.get('kept_30s', '?')}%; at the end: {found.get('end', '?')}%",
             f"Average percentage viewed: {stats.get('avg_view_percent', '?')}"]
    if stats.get("ctr") is not None:
        lines.append(f"Thumbnail click-through: {stats['ctr']}%")
    lines.append(f"Opening lines: {' '.join(s['narration'] for s in scenes[:2])}")
    for d in found.get("drops") or []:
        s = scenes[d["scene"]] if d["scene"] < len(scenes) else {}
        lines.append(f"Lost {d['lost']}% during scene {d['scene'] + 1} (at {d['at']} s): said "
                     f"\"{s.get('narration', '')}\"; showed {s.get('medium', 'picture')}: {s.get('direction', '')}")
    schema = {"type": "object", "properties": {"lessons": {"type": "array", "items": {"type": "string"}}},
              "required": ["lessons"], "additionalProperties": False}
    answer = call_json(LEARN, "\n".join(lines), schema, operation="documentary_lessons", model=LEARN_MODEL,
                       max_tokens=1500, effort=None)
    new = [" ".join(str(t).split()) for t in answer.get("lessons") or [] if str(t).strip()][:2]
    lessons.add(channel.key, new, source=video_path.stem)
    return new
