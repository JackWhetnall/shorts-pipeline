"""
The data that flows through the pipeline, as declared types.

Before this, each stage had its own ad-hoc shape: a seed dict with keys
that depended on its "type", a script dict of dicts, a five-tuple back
from the voiceover stage, two parallel lists-of-lists (spans and clip
paths) that the assembler had to re-zip by hand, and thirteen arguments
into build_video — five of which were the channel config, unpacked field
by field and passed individually.

The cost of that wasn't ugliness, it was that every new capability had to
be threaded through every signature. Adding a music bed meant a new
parameter in three functions and a sixth element in the tuple. Here a
stage takes the plan and returns the plan, so a new stage is one
function and a new field, and nothing upstream of it changes.

Everything is JSON round-trippable (see to_jsonable / *_from_jsonable)
because the checkpoint system persists partial plans so an interrupted
job can resume without re-paying for work that already completed. The one
exception is the raw audio sample array, which is checkpointed as an mp3
alongside — decoding a saved file is more reliable than serialising float
samples, the same reasoning the audio layer uses everywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.channels import ChannelConfig


@dataclass
class Seed:
    """What a video is about, before any text has been written.

    Two shapes behind one type: a quote carries text the pipeline must
    not alter (it's someone else's words), a topic carries only a subject
    and everything gets generated. Downstream stages never branch on
    this — only the script generator does.
    """

    type: str                 # "quote" | "topic"
    text: str = ""            # quote only: the source text, used verbatim
    reference: str = ""       # quote only: e.g. "John 3:16"
    topic: str = ""           # topic only
    # topic only, and only when the channel has a syllabus: which entry
    # this came from, so generating can claim that exact one rather than
    # whatever happens to be next by the time the job runs.
    topic_id: str = ""

    @property
    def title(self) -> str:
        """The human-readable label this video's files are named after —
        the reference for a quote, the topic otherwise. Filenames built
        from this are how repeats stay visible at a glance."""
        return self.reference if self.type == "quote" else self.topic

    def describe(self) -> str:
        if self.type == "quote":
            return f"{self.text}  —  {self.reference}"
        return self.topic

    def to_jsonable(self) -> dict:
        return {"type": self.type, "text": self.text,
                "reference": self.reference, "topic": self.topic,
                "topic_id": self.topic_id}

    @classmethod
    def from_jsonable(cls, data: dict) -> "Seed":
        return cls(type=data["type"], text=data.get("text", ""),
                   reference=data.get("reference", ""), topic=data.get("topic", ""),
                   topic_id=data.get("topic_id", ""))


@dataclass
class Segment:
    """One spoken chunk, plus a brief for the footage under it.

    `text` is what is said. `shot_brief` is what should be on screen — a
    literal, filmable sentence, deliberately separate from the words
    because the two are rarely the same thing. Reflective narration is
    abstract; footage cannot be. Keeping them apart is what lets the
    matcher compare something literal against literal clip descriptions
    instead of trying to bridge "integrity" to "prayer beads on a table".

    `keywords` are concrete, searchable terms drawn from the brief.

    start/end are filled in by the voiceover stage from the real
    synthesized audio — never estimated from word counts, which
    punctuation and TTS quirks make unreliable.
    """

    text: str
    shot_brief: str = ""
    keywords: list = field(default_factory=list)
    start: float = 0.0
    end: float = 0.0
    # Silence after this segment, overriding the channel's pacing: a
    # quiz's countdown after each question. None means the usual pause.
    pause_after: float = None

    @property
    def visual_text(self) -> str:
        """What to match footage against: the brief, falling back to the
        spoken words for scripts generated before briefs existed."""
        return self.shot_brief or self.text

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_jsonable(self) -> dict:
        return {"text": self.text, "shot_brief": self.shot_brief,
                "keywords": list(self.keywords),
                "start": self.start, "end": self.end, "pause_after": self.pause_after}

    @classmethod
    def from_jsonable(cls, data: dict) -> "Segment":
        # shot_brief is optional: checkpoints written before briefs
        # existed must still resume rather than crash a retry.
        return cls(text=data["text"], shot_brief=data.get("shot_brief", ""),
                   keywords=list(data.get("keywords") or []),
                   start=data.get("start", 0.0), end=data.get("end", 0.0),
                   pause_after=data.get("pause_after"))


@dataclass
class Script:
    """citation is optional generic metadata spoken right after segment 0
    — a Bible reference, say. Absent for topic-driven formats. No stage
    downstream of here knows what format produced these segments.

    `title_options` and `description_body` come back from the same call
    that writes the segments. They are nearly free — the model already has
    the passage and the analysis in front of it — and they replace the two
    things that were previously done by hand for every single video: a
    title that existed nowhere in the system, and a "ready-to-paste"
    description that was one reference line long.
    """

    segments: list
    citation: str = None
    title_options: list = field(default_factory=list)
    description_body: str = ""
    # Which segment is someone else's words read verbatim (the passage on
    # a quote channel), with the citation spoken straight after it. It
    # used to always be 0; a hook line now comes before it. None when the
    # format has no source text.
    source_index: int = None
    # What the opening makes the viewer want to know, and where the video
    # answers it: planned by the writer before the lines, kept so review
    # and the script check can hold the video to it.
    hook_promise: str = ""
    payoff: str = ""
    # The hook's punch as big on-screen text in the first seconds, and the
    # few words that pop in the captions as they're spoken.
    screen_hook: str = ""
    emphasis: list = field(default_factory=list)
    # A short museum search for a painting of this passage (pipeline.artwork).
    art_query: str = ""
    # A quiz's structure (pipeline.quiz): category, difficulty, and each
    # question with its answer and which segments ask and answer it.
    # None for every other format.
    quiz: dict = None

    def __post_init__(self):
        if self.source_index is None and self.citation:
            self.source_index = 0

    @property
    def title(self) -> str:
        return self.title_options[0] if self.title_options else ""

    def to_jsonable(self) -> dict:
        return {"citation": self.citation,
                "source_index": self.source_index,
                "hook_promise": self.hook_promise,
                "payoff": self.payoff,
                "screen_hook": self.screen_hook,
                "emphasis": list(self.emphasis),
                "art_query": self.art_query,
                "quiz": self.quiz,
                "segments": [s.to_jsonable() for s in self.segments],
                "title_options": list(self.title_options),
                "description_body": self.description_body}

    @classmethod
    def from_jsonable(cls, data: dict) -> "Script":
        return cls(citation=data.get("citation"),
                   source_index=data.get("source_index"),
                   hook_promise=data.get("hook_promise", ""),
                   payoff=data.get("payoff", ""),
                   screen_hook=data.get("screen_hook", ""),
                   emphasis=list(data.get("emphasis") or []),
                   art_query=data.get("art_query", ""),
                   quiz=data.get("quiz"),
                   segments=[Segment.from_jsonable(s) for s in data["segments"]],
                   title_options=list(data.get("title_options") or []),
                   description_body=data.get("description_body", ""))


@dataclass
class WordTiming:
    word: str
    start: float
    end: float

    def to_jsonable(self) -> dict:
        return {"word": self.word, "start": self.start, "end": self.end}

    @classmethod
    def from_jsonable(cls, data: dict) -> "WordTiming":
        return cls(word=data["word"], start=data["start"], end=data["end"])


@dataclass
class Shot:
    """One continuous piece of footage at its exact real timestamps.

    This replaces two parallel lists-of-lists — spans in one, clip paths
    in another — that the assembler zipped back together. A shot knowing
    its own clip is why the assembler no longer has to.
    """

    start: float
    end: float
    segment_index: int
    clip_path: Path = None
    # An animated scene rather than library footage: played from its
    # start (it's timed to the words), never a random window of it.
    scene: bool = False

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Voiceover:
    """The narration, its timings, and the actual samples.

    `samples` travels in memory rather than being re-read from
    audio_path: re-decoding a lossily-encoded file back into
    frame-accurate samples near its exact end is unreliable, and there's
    no reason to when the real samples are already here.
    """

    audio_path: Path
    word_timings: list
    samples: object          # numpy (n, channels) float array
    fps: int

    @property
    def duration(self) -> float:
        return len(self.samples) / self.fps


@dataclass
class RenderPlan:
    """Everything one video needs, accumulated stage by stage.

    Stages are `fn(plan) -> plan`. Fields are None until the stage that
    produces them has run, so the plan doubles as a record of how far a
    job actually got.
    """

    channel: ChannelConfig
    seed: Seed
    out_dir: Path = None
    stem: str = None
    script: Script = None
    voiceover: Voiceover = None
    shots: list = field(default_factory=list)
    # Set when the footage library had to reuse a clip because it ran out
    # of distinct matches. Surfaced on the finished video rather than
    # buried in a log — repeated footage within one video is exactly the
    # mass-production signal that puts monetization at risk.
    footage_repeated: bool = False
    # True when clips were chosen without scoring because the matching
    # call failed. The render still completes; the video is flagged so
    # nobody publishes it thinking it had the usual treatment.
    footage_degraded: bool = False
    # How many shots were filled after footage fetching ran out, without
    # any clip scoring at or above the confidence bar for them.
    footage_unconfident: int = 0
    # Where the title card was spliced into the narration (0 = in front of
    # it) and how long it runs; 0 seconds when there is no card. Narration
    # time t is video time t before the card and t + title_card_seconds
    # after it.
    title_card_at: float = 0.0
    title_card_seconds: float = 0.0
    # Animated scenes (pipeline.scenes.stage): [{first, last, clip}] for
    # the stretches of segments they cover. Stock footage fills the rest.
    scene_clips: list = field(default_factory=list)
    # Scenes that were planned but fell back to stock footage, and notes
    # on anything imperfect in the ones that were made. Shown on review.
    scenes_fell_back: int = 0
    scene_notes: list = field(default_factory=list)
    # Credits for public-domain artwork and CC BY music (pipeline.artwork, sound).
    art_credits: list = field(default_factory=list)
    # The director's choice for each segment (pipeline.director), for review.
    visual_plan: list = field(default_factory=list)
    # The publish gate's verdict for this render (core.publish_gate).
    gate: dict = None
    # The offending text when a segment reads like a description of a line
    # rather than a line — see `script_gen.placeholder_text`. Held as the
    # text itself, not a bool, so the review screen can quote it.
    script_suspect: str = ""
    # Set by the originality check at the end of a run (see
    # pipeline.similarity). Carried on the plan so the caller can surface
    # it without re-running the comparison.
    similarity: object = None
    # False on background threads, which have no terminal to read from.
    # Only the CLI ever sets this True, and only the CLI acts on it.
    interactive: bool = True

    @property
    def video_path(self) -> Path:
        return self.out_dir / f"{self.stem}.mp4"

    @property
    def audio_path(self) -> Path:
        return self.out_dir / f"{self.stem}_audio.mp3"

    @property
    def meta_path(self) -> Path:
        return self.out_dir / f"{self.stem}_meta.txt"

    @property
    def description_path(self) -> Path:
        return self.out_dir / f"{self.stem}_description.txt"

    @property
    def segments(self) -> list:
        return self.script.segments if self.script else []

    def shots_for_segment(self, index: int) -> list:
        return [s for s in self.shots if s.segment_index == index]
