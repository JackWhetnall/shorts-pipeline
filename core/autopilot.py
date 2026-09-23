"""
What happens to a finished video on a channel that publishes itself.

Called once a render has finished and written its report. Decides, from
the channel's autopilot setting and the gate's verdict already in that
report (core.publish_gate), whether the video uploads now or waits in
/review, and says why either way. An upload goes through exactly the path
the review queue's button uses, so a published video looks the same
however it got there.

Nothing here raises for an ordinary failure. The video exists and is
paid for; the worst outcome of a problem at this point is that it waits
for a person, which is where it would have been anyway. See decision 028.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core import gallery, youtube
from core.errors import PipelineError
from core.logging_setup import get_logger

log = get_logger(__name__)

UPLOADED, HELD, OFF = "uploaded", "held", "off"


@dataclass
class Decision:
    action: str            # uploaded | held | off
    message: str = ""
    url: str = ""


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

    if not youtube.connection(channel.key)["connected"]:
        return _hold(video_path, report,
                     "Passed every check, but this channel isn't connected to YouTube, "
                     "so it's waiting in review.")

    info = gallery.load_publish_info(video_path)
    title = info.get("title") or (report.get("title_options") or [video_path.stem])[0]
    try:
        result = youtube.upload(channel.key, video_path, title, info.get("description") or "",
                                privacy="public")
    except PipelineError as exc:
        log.warning(f"{channel.key}: automatic upload failed: {exc}")
        return _hold(video_path, report,
                     f"Passed every check, but the upload failed: {exc.user_message} "
                     f"It's waiting in review.")

    gallery.save_publish_info(video_path, {"youtube_url": result["url"]})
    message = f"Uploaded to YouTube automatically: {result['url']}"
    if result.get("locked_private"):
        message += (" YouTube made it private, as it does for every upload until the "
                    "API project is audited. Make it public in Studio.")
    log.info(f"{channel.key}: {message}")
    return Decision(UPLOADED, message, result["url"])


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
