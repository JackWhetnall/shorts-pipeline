"""
A proglog logger that reports moviepy's encode progress as a real
number.

moviepy drives its progress bars through proglog, which supports custom
logger subclasses — so the encode percentage can be read from the value
proglog already computes, instead of being recovered by regex from the
tqdm bar's carriage-return-terminated stderr writes.

That regex (`(\\d{1,3})\\s*%` against captured stderr) was the last reason
the job runner needed to intercept a standard stream at all. With this,
encode progress arrives through the same explicit reporting channel as
every other stage, and the CLI simply gets moviepy's normal bar because
it never installs a sink.
"""

from __future__ import annotations

from proglog import ProgressBarLogger

from core import job_context


class JobProgressLogger(ProgressBarLogger):
    """Reports the main encode bar's completion percentage to the current
    job.

    moviepy runs several bars over one write_videofile call (a "chunk"
    bar for audio, a "t" bar for frames). Only the frame bar is worth
    showing — it's the long one — so the others are ignored rather than
    fighting each other over a single percentage field.
    """

    FRAME_BAR = "t"

    def bars_callback(self, bar, attr, value, old_value=None):
        if bar != self.FRAME_BAR or attr != "index":
            return
        total = (self.bars.get(bar) or {}).get("total")
        if not total:
            return
        percent = max(0.0, min(100.0, (value / total) * 100.0))
        job_context.report_progress(percent)


def encode_logger():
    """The logger to hand moviepy's write_videofile.

    Inside a job: this reporter, so the UI gets a real percentage.
    Outside one (CLI): moviepy's own "bar", so a terminal run still shows
    the frame-by-frame progress bar with an ETA that makes the slowest
    step in the pipeline bearable to watch.
    """
    return JobProgressLogger() if job_context.get_job_id() else "bar"
