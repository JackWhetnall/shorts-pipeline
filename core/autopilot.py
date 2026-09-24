"""
What happens to a finished video on a channel that publishes itself.

Called once a render has finished and written its report. Decides, from
the channel's autopilot setting and the gate's verdict already in that
report (core.publish_gate), whether the video is approved into the
publishing queue (core.publish_queue) to go out at the channel's next
slot, or waits in /review, and says why either way. Approval by the gate
and approval by you put a video in the same queue, so it goes out the
same way however it got there.

Nothing here raises for an ordinary failure. The video exists and is
paid for; the worst outcome of a problem at this point is that it waits
for a person, which is where it would have been anyway. See decision 028.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core import gallery, publish_queue, youtube
from core.logging_setup import get_logger

log = get_logger(__name__)

QUEUED, HELD, OFF = "queued", "held", "off"


@dataclass
class Decision:
    action: str            # queued | held | off
    message: str = ""


def after_render(channel, video_path: Path) -> Decision:
    video_path = Path(video_path)
    if channel.autopilot.mode != "when_clean":
        return Decision(OFF)

    report = gallery.load_report(video_path) or {}
    gate = report.get("gate") or {}
    if not gate.get("passed"):
        reasons = gate.get("reasons") or ["The automatic checks didn't run."]
        return _hold(video_path, report, "Held for review: " + " ".join(reasons))

    if _is_spot_check(channel, report):
        return _hold(video_path, report,
                     f"Held for a routine spot check (one clean video in "
                     f"{channel.autopilot.spot_check_every}). It passed every automatic check.",
                     spot_check=True)

    has_handoff = channel.publishing.handoff_tiktok or channel.publishing.handoff_instagram
    if not youtube.connection(channel.key)["connected"] and not has_handoff:
        return _hold(video_path, report,
                     "Passed every check, but this channel has nowhere to publish yet "
                     "(connect YouTube, or turn on a TikTok/Instagram hand-off), so it's "
                     "waiting in review.")

    publish_queue.enqueue(video_path, approved_by="checks")
    when = next((slot for path, slot in publish_queue.schedule_for(channel)
                 if Path(path).resolve() == video_path.resolve()), None)
    message = ("Passed every check and is queued to go out "
               + (when.strftime("%a %d %b at %H:%M") if when else "on the next check") + ".")
    log.info(f"{channel.key}: {message}")
    return Decision(QUEUED, message)


def _is_spot_check(channel, report: dict) -> bool:
    """Every Nth video that passes the gate is held anyway.

    Counted over this channel's own clean videos, this one included, so
    the sample is spread evenly rather than random and can't go a long
    stretch without one."""
    every = channel.autopilot.spot_check_every
    if every <= 0:
        return False
    clean = sum(1 for v in gallery.list_videos(channel.output_dir)
                if ((v.get("report") or {}).get("gate") or {}).get("passed"))
    return clean % every == 0


def _hold(video_path: Path, report: dict, message: str, spot_check: bool = False) -> Decision:
    """Record why it's waiting, beside the video, for the review queue."""
    report["autopilot"] = {"action": HELD, "message": message, "spot_check": spot_check}
    gallery.save_report(video_path, report)
    return Decision(HELD, message)
