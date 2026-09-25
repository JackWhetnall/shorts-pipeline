"""
Two automatic checks on a finished video: its script and its frames.

They exist so a video can publish without a person watching it first
(decision 028). The render's own flags already say when footage repeated,
was unscored, or when the wording is close to an earlier script; these
cover what those can't see: a claim that is wrong or unsafe to state, a
line that breaks the channel's own rules, a shot that contradicts what is
being said or should never be on this channel, a caption nobody can read.

Both run on Haiku: each is one short, schema-constrained judgement over a
few hundred words or a handful of small frames, well under a cent together.
They run on every video, whether or not the channel publishes on its own,
so their verdicts build a record that can be compared against what a
person decided before anyone trusts them to decide alone.

A check that can't run (service down, refusal, budget) reports that it
didn't run. It never reports a pass: the gate treats "not checked" as
"needs a person", which is the safe direction.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from pathlib import Path

from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline import llm

log = get_logger(__name__)

# Haiku takes neither `effort` nor thinking by default, so both calls pass
# effort=None. Structured output is supported.
CHECK_MODEL = "claude-haiku-4-5"
CHECK_MAX_TOKENS = 2000

# Frames sampled for the visual check. One per shot would be sixteen
# images for a long video; six spread across it catches the same class of
# problem at a third of the cost.
MAX_FRAMES = 6
FRAME_SIZE = (540, 960)

BLOCK, NOTE = "block", "note"

PROBLEMS_SCHEMA = {
    "type": "object",
    "properties": {
        "problems": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "where": {"type": "string"},
                    "problem": {"type": "string"},
                    "severity": {"type": "string", "enum": [BLOCK, NOTE]},
                },
                "required": ["where", "problem", "severity"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["problems"],
    "additionalProperties": False,
}

SEVERITY_GUIDE = f"""
Use "{BLOCK}" only for something that should stop this going out unseen:
a person would have to fix it or would be embarrassed it was published.
Use "{NOTE}" for things worth a glance that are not wrong. Return an empty
list when nothing qualifies - most videos should have no problems at all.
Do not report style preferences, word choices you would make differently,
or anything you are unsure is actually a problem.
""".strip()

SCRIPT_SYSTEM = f"""
You are the last editor before a short vertical video is published
without a person watching it. You are given the channel's own writing
rules and the video's spoken script. Report only real problems:

- A factual error: a misattributed quote, a wrong name, date, place or
  context (for example, saying who said a verse, or to whom, incorrectly).
- Medical, legal or financial advice, or a promised result, stated as
  fact.
- A line that breaks the channel's own rules below.
- Text that is not a finished spoken line: a note, placeholder, stage
  direction or bracketed slot. It is read aloud exactly as written.
- Anything demeaning to a group, or unsuitable for a general audience.
- The opening (the first line) doesn't hook: it opens no specific
  question or tension, or starts with a greeting or preamble. A note.
- The opening promises something the script never delivers: bait.
  Block it.
- The ending doesn't land: it trails off, leads into more, or never
  closes the question the opening opened. A note.
- A line that sounds machine-written rather than spoken by a person
  (stock phrases like "here's the thing", "that's the whole trick",
  "it's not X, it's Y", slogan-shaped closing lines). A note.

Text marked SOURCE is someone else's words, quoted verbatim. Never report
it as a problem; judge only whether the lines around it describe it
accurately.

{SEVERITY_GUIDE}
""".strip()

FRAMES_SYSTEM = f"""
You are checking frames from a short vertical video before it is
published without a person watching it. Each frame is labelled with the
line being spoken at that moment and the shot the editor asked for.
Burned-in captions are part of the video. Report only real problems:

- The picture contradicts or undermines what is being said, or would
  read as a mistake to a viewer.
- It shows something this channel must never show (listed below), or
  anything unsuitable for a general audience.
- A technical fault: a black or frozen-looking frame, heavy compression
  damage, or a visible watermark or logo.
- The caption is unreadable against the picture.

A shot that is merely generic, or only loosely related, is fine: this is
background footage. Do not report it.

Some frames are animated explanations (diagrams, labels, equations drawn
in the channel's style) rather than footage. Judge those against the
words only: are the numbers, labels and pictures right for what is being
said, and readable? A diagram is never a problem for not being the
footage a shot brief described, and a caption is only ever a few words
of the line: never report a caption as incomplete.

{SEVERITY_GUIDE}
""".strip()


@dataclass
class CheckResult:
    """`ran` False means the check couldn't be made - never a pass."""

    ran: bool
    problems: list = field(default_factory=list)
    error: str = ""

    @property
    def blocking(self) -> list:
        return [p for p in self.problems if p.get("severity") == BLOCK]

    def to_jsonable(self) -> dict:
        return {"ran": self.ran, "problems": list(self.problems), "error": self.error}


def check_script(script, channel) -> CheckResult:
    lines = []
    for i, segment in enumerate(script.segments):
        label = "SOURCE" if (i == script.source_index and script.citation) else f"LINE {i}"
        lines.append(f"[{label}] {segment.text}")
    if script.citation:
        lines.append(f"[CITATION, spoken after the source] {script.citation}")
    if getattr(script, "hook_promise", ""):
        lines.append(f"[THE WRITER'S PLAN] Opening loop: {script.hook_promise}. "
                     f"Closed by: {script.payoff}")
    avoid = ", ".join(channel.avoid_imagery) or "(none)"
    user = (f"The channel's writing rules:\n{channel.style_prompt}\n\n"
            f"Subjects this channel avoids: {avoid}\n\n"
            f"The script, in order:\n" + "\n".join(lines))
    return _run(SCRIPT_SYSTEM, user, "check_script")


def check_frames(video_path: Path, plan) -> CheckResult:
    """Sample frames from the rendered video itself, captions included,
    and ask whether any of them is wrong for the line under it."""
    shots = [s for s in plan.shots if s.duration > 0]
    if not shots:
        return CheckResult(ran=False, error="no shots to check")
    picked = _spread(shots, MAX_FRAMES)
    # An animated scene builds up while it's spoken; mid-way it is only
    # ever "incomplete". Judge it near its end, once it's all there.
    moments = [s.start + (s.end - s.start) * (0.9 if s.scene else 0.5) for s in picked]
    try:
        images = _frames_at(video_path, [video_time(plan, t) for t in moments])
    except Exception as exc:  # noqa: BLE001 - a check that can't run says so
        log.warning(f"  [check] couldn't read frames for the visual check ({exc}).")
        return CheckResult(ran=False, error="couldn't read frames")

    segments = plan.script.segments
    content = []
    for n, (shot, data, moment) in enumerate(zip(picked, images, moments), 1):
        # An animated scene's shot spans several segments: judge the frame
        # against the words actually being spoken at that moment.
        segment = next((s for s in segments if s.start <= moment < s.end),
                       segments[shot.segment_index])
        # A scene is drawn from the words, not the stock-footage brief:
        # judged against the brief, every diagram "fails" to be footage.
        asked = ("an animated explanation of these words" if shot.scene
                 else f'"{segment.shot_brief}"')
        content.append({"type": "text",
                        "text": f'Frame {n}. Spoken: "{segment.text}" Shot asked for: {asked}'})
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
    avoid = ", ".join(plan.channel.avoid_imagery) or "(none)"
    content.append({"type": "text",
                    "text": f"This channel must never show: {avoid}. Report problems by frame number."})
    return _run(FRAMES_SYSTEM, content, "check_frames")


def _run(system: str, user, operation: str) -> CheckResult:
    try:
        data = llm.call_json(system, user, PROBLEMS_SCHEMA, operation=operation,
                             model=CHECK_MODEL, max_tokens=CHECK_MAX_TOKENS, effort=None)
    except PipelineError as exc:
        log.warning(f"  [check] {operation} couldn't run ({exc}); this video will need a person.")
        return CheckResult(ran=False, error=exc.user_message)
    problems = [p for p in data.get("problems") or [] if isinstance(p, dict)]
    return CheckResult(ran=True, problems=problems)


def _spread(items: list, count: int) -> list:
    if len(items) <= count:
        return list(items)
    step = (len(items) - 1) / (count - 1)
    return [items[round(i * step)] for i in range(count)]


def video_time(plan, narration_time: float) -> float:
    """Where a moment of narration falls in the finished file: later by
    the title card's length if the card comes before it."""
    if plan.title_card_seconds and narration_time >= plan.title_card_at:
        return narration_time + plan.title_card_seconds
    return narration_time


def _frames_at(video_path: Path, times: list) -> list:
    """Base64 JPEGs at the given times, downscaled for the vision call."""
    from moviepy.editor import VideoFileClip
    from PIL import Image

    clip = VideoFileClip(str(video_path))
    try:
        out = []
        for t in times:
            t = min(max(t, 0.0), max(clip.duration - 0.05, 0.0))
            frame = Image.fromarray(clip.get_frame(t)).convert("RGB")
            frame.thumbnail(FRAME_SIZE, Image.LANCZOS)
            buffer = io.BytesIO()
            frame.save(buffer, format="JPEG", quality=80)
            out.append(base64.b64encode(buffer.getvalue()).decode("ascii"))
        return out
    finally:
        clip.close()
