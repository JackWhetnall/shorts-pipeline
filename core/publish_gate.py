"""
Whether a finished video can go out without a person looking at it.

One function over the render report, so the review queue, the job
warnings and the uploader all read the same verdict, and a report written
today can be re-judged tomorrow if the rules change. Every reason it gives
is written for the person who will see it in the review queue.

The rules are deliberately conservative: anything the pipeline already
flags as a quality risk, any problem an automatic check called blocking,
and any check that didn't run. "Couldn't check" is never "fine". Decision
028 has the reasoning.
"""

from __future__ import annotations


def evaluate(report: dict) -> dict:
    """{"passed": bool, "reasons": [str, ...]} for one render report."""
    report = report or {}
    reasons = []

    if report.get("footage_degraded"):
        reasons.append("Footage was picked without scoring (the matching step failed).")
    if report.get("footage_repeated"):
        reasons.append("A footage clip appears twice.")
    unconfident = int(report.get("footage_unconfident") or 0)
    if unconfident:
        reasons.append(f"{unconfident} shot{'s' if unconfident != 1 else ''} had no footage "
                       f"that scored as a good match.")
    unverified = report.get("quiz_unverified") or []
    if unverified:
        reasons.append(f"The fact check couldn't confirm the answer to question"
                       f"{'s' if len(unverified) != 1 else ''} "
                       f"{', '.join(str(n) for n in unverified)}.")
    if report.get("script_suspect"):
        reasons.append("A line reads like a note about a line rather than the line itself.")
    similarity = report.get("similarity") or {}
    if similarity.get("flagged"):
        closest = similarity.get("closest_title") or "an earlier video"
        reasons.append(f"The wording is close to {closest}.")

    checks = report.get("checks")
    if not checks:
        reasons.append("The automatic script and picture checks didn't run on this video.")
    else:
        for name, label in (("script", "script"), ("frames", "picture")):
            result = checks.get(name) or {}
            if not result.get("ran"):
                reasons.append(f"The automatic {label} check couldn't run.")
                continue
            for problem in result.get("problems") or []:
                if problem.get("severity") == "block":
                    where = problem.get("where") or label
                    reasons.append(f"{label.capitalize()} check ({where}): {problem.get('problem')}")

    return {"passed": not reasons, "reasons": reasons}
