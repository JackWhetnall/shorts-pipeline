"""
A documentary's scorecard: the hit recipe's checks, measured on the film
itself (decision 086).

Each check is a number against a target, worked out when the video is
made (pipeline.documentary.render) and shown as pills on its production
page before it's approved: the title's length, the thumbnail's words,
whether the film opens on its promise, pictures in the first thirty
seconds, the longest a picture holds, pictures a minute, words a minute,
how many kinds of picture, its length. None of them stops a video going
out; they say where it's likely to lose people.
"""

from __future__ import annotations

TITLE_MAX = 55
FIRST_30S_MIN = 5
LONGEST_HOLD_MAX = 9.0
PER_MINUTE_MIN = 8.0
WPM = (138, 168)
KINDS_MIN = 2
MINUTES_MIN = 8.0


def _opens_on_promise(hook: str, scenes: list) -> bool:
    want = {w.lower().strip(".,!?") for w in (hook or "").split() if len(w) > 4}
    if not want or not scenes:
        return None
    have = {w.lower().strip(".,!?") for w in " ".join(s["narration"] for s in scenes[:2]).split()}
    return len(want & have) >= 0.4 * len(want)


def score(title: str, angle: dict, scenes: list, numbers: dict) -> list:
    """[{"key", "label", "value", "target", "ok"}] (ok None: not measurable)."""
    seconds = float(numbers.get("video_seconds") or 0)
    minutes = seconds / 60 if seconds else 0
    words = int(numbers.get("words") or 0)
    wpm = round(words / minutes) if minutes else 0
    per_minute = round(numbers.get("pictures", 0) / minutes, 1) if minutes else 0
    thumb_words = len(((angle or {}).get("thumbnail") or {}).get("words", "").split())
    opens = _opens_on_promise((angle or {}).get("hook", ""), scenes)
    kinds = len(numbers.get("media") or [])
    return [
        {"key": "title", "label": "Title", "value": f"{len(title)} chars", "target": f"≤ {TITLE_MAX}",
         "ok": len(title) <= TITLE_MAX},
        {"key": "thumb_words", "label": "Thumbnail words", "value": str(thumb_words), "target": "1–4",
         "ok": 1 <= thumb_words <= 4 if angle else None},
        {"key": "opens", "label": "Opens on its promise", "value": {True: "yes", False: "no", None: "–"}[opens],
         "target": "yes", "ok": opens},
        {"key": "first_30s", "label": "Pictures in the first 30 s", "value": str(numbers.get("first_30s_pictures", 0)),
         "target": f"≥ {FIRST_30S_MIN}", "ok": numbers.get("first_30s_pictures", 0) >= FIRST_30S_MIN},
        {"key": "hold", "label": "Longest hold", "value": f"{numbers.get('longest_hold', 0):g} s",
         "target": f"≤ {LONGEST_HOLD_MAX:g} s", "ok": numbers.get("longest_hold", 0) <= LONGEST_HOLD_MAX},
        {"key": "per_minute", "label": "Pictures a minute", "value": f"{per_minute:g}",
         "target": f"≥ {PER_MINUTE_MIN:g}", "ok": per_minute >= PER_MINUTE_MIN},
        {"key": "wpm", "label": "Words a minute", "value": str(wpm), "target": f"{WPM[0]}–{WPM[1]}",
         "ok": WPM[0] <= wpm <= WPM[1]},
        {"key": "kinds", "label": "Kinds of picture", "value": str(kinds), "target": f"≥ {KINDS_MIN}",
         "ok": kinds >= KINDS_MIN},
        {"key": "length", "label": "Length", "value": f"{minutes:.1f} min", "target": f"≥ {MINUTES_MIN:g} min",
         "ok": minutes >= MINUTES_MIN},
    ]


def passed(card: list) -> tuple:
    """(checks passed, checks measured)."""
    measured = [c for c in card if c["ok"] is not None]
    return sum(1 for c in measured if c["ok"]), len(measured)
