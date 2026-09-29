"""
The generation models animation can use: what each costs, what it can
do, and how to ask it for a picture or a shot.

The best model changes every few months, and has done twice while this
project has existed (Sora 2 was shut down on 24 September 2026, a month
after MiniMax H3 Max went to the top of the image-to-video arena). So
the model is a channel setting and an entry here, never code spread
through the pipeline. Adding one is a new entry and, if its request
differs, a new `shape`.

Prices are declared rather than fetched, like core.costs, and were
checked on PRICES_CHECKED. `estimate` is what budgeting uses before
anything is spent; what is recorded afterwards is the real bill where
the provider reports one (OpenAI's token usage) and this table where it
doesn't (fal bills by the second).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

PRICES_CHECKED = "2026-09-29"

# How far a generated shot may be sped up or slowed down to land exactly
# on the narration. Within this, a change of speed can't be seen in
# stylised animation (and on twos or threes, not at all).
RETIME_MIN, RETIME_MAX = 0.8, 1.25

QUALITY_LABELS = {
    "draft": "Draft: lower resolution, cheapest",
    "standard": "Standard: sharp on a phone",
    "high": "High: full 1080p",
}


@dataclass(frozen=True)
class VideoModel:
    """An image-to-video model: a first frame and a prompt in, a shot out."""

    key: str
    label: str
    endpoint: str                   # the fal endpoint
    shape: str                      # how its request is built: see request()
    durations: tuple                # seconds it can make, ascending
    resolution: dict                # quality -> the model's own resolution value
    price: dict                     # quality -> USD per second generated
    note: str = ""
    # True when the model takes a last frame as well as a first.
    last_frame: bool = False

    def seconds_for(self, shot_seconds: float) -> int:
        """The cheapest length this model can make that retimes onto a
        shot of `shot_seconds`: sped up at most RETIME_MAX, or trimmed
        when even the shortest is too long."""
        for d in self.durations:
            if d * RETIME_MAX >= shot_seconds:
                return d
        return self.durations[-1]

    def cost(self, seconds: float, quality: str) -> float:
        return round(seconds * self.price.get(quality, self.price["standard"]), 4)

    def request(self, prompt: str, image_url: str, seconds: int, quality: str,
                seed: int = None, last_image_url: str = None) -> dict:
        if self.shape == "minimax":
            body = {"prompt": prompt, "image_url": image_url, "duration": int(seconds),
                    "resolution": self.resolution[quality],
                    # Our prompts are written for the shot; the model's own
                    # rewriting leans live-action and adds dialogue.
                    "prompt_expansion_mode": "disabled"}
            if last_image_url and self.last_frame:
                body["end_image_url"] = last_image_url
        elif self.shape == "veo":
            body = {"prompt": prompt, "image_url": image_url, "duration": f"{int(seconds)}s",
                    "resolution": self.resolution[quality], "aspect_ratio": "9:16",
                    "generate_audio": False}
        else:
            raise ValueError(f"unknown request shape {self.shape!r}")
        if seed is not None:
            body["seed"] = int(seed)
        return body

    @staticmethod
    def video_url(result: dict) -> str:
        video = (result or {}).get("video") or {}
        return video.get("url", "") if isinstance(video, dict) else ""


@dataclass(frozen=True)
class ImageModel:
    """A picture model that takes reference images: keyframes, style
    frames and cast sheets."""

    key: str
    label: str
    provider: str                   # "openai"
    model: str
    quality: str = "medium"
    # A portrait frame with two or three references, for budgeting. The
    # 2.5 models measured $0.015-0.03 each (29 Sep 2026: ~280 output
    # tokens, 1-3k input tokens of references).
    estimate: float = 0.03
    note: str = ""


VIDEO_MODELS = {
    m.key: m for m in (
        VideoModel(
            key="h3_max", label="MiniMax H3 Max",
            endpoint="minimax/h3-max/image-to-video", shape="minimax",
            durations=tuple(range(5, 16)),
            resolution={"draft": "480P", "standard": "768P", "high": "1080P"},
            price={"draft": 0.05, "standard": 0.08, "high": 0.16},
            last_frame=True,
            note="First in the image-to-video arena (Sep 2026). Holds a character and a "
                 "style best; 5-15 second shots."),
        VideoModel(
            key="veo31_lite", label="Veo 3.1 Lite",
            endpoint="fal-ai/veo3.1/lite/image-to-video", shape="veo",
            durations=(4, 6, 8),
            resolution={"draft": "720p", "standard": "1080p", "high": "1080p"},
            price={"draft": 0.03, "standard": 0.05, "high": 0.05},
            note="About half the price, noticeably plainer motion; 4, 6 or 8 second shots."),
    )
}

IMAGE_MODELS = {
    m.key: m for m in (
        ImageModel(key="gpt_image_flare", label="GPT Image 2.5 Flare", provider="openai",
                   model="gpt-image-2.5-flare",
                   note="OpenAI's everyday image model: fast, first-rank quality."),
        ImageModel(key="gpt_image_sunburst", label="GPT Image 2.5 Sunburst", provider="openai",
                   model="gpt-image-2.5-sunburst",
                   note="Same price, slower, holds fine detail. Used for style frames "
                        "and cast sheets whichever is chosen for keyframes."),
        ImageModel(key="gpt_image_2", label="GPT Image 2", provider="openai",
                   model="gpt-image-2", note="The previous generation."),
    )
}

DEFAULT_VIDEO_MODEL = "h3_max"
DEFAULT_IMAGE_MODEL = "gpt_image_flare"
# The one-off pictures a channel's look rests on get the careful model.
BIBLE_IMAGE_MODEL = "gpt_image_sunburst"


def video_model(key: str) -> VideoModel:
    return VIDEO_MODELS.get(key) or VIDEO_MODELS[DEFAULT_VIDEO_MODEL]


def image_model(key: str) -> ImageModel:
    return IMAGE_MODELS.get(key) or IMAGE_MODELS[DEFAULT_IMAGE_MODEL]


@dataclass
class Estimate:
    """What a video's animation should cost, before anything is spent."""

    shots: int
    seconds: float                  # of finished animation
    generated: float                # seconds of video paid for
    video_usd: float
    image_usd: float
    other_usd: float = 0.05         # storyboard and the two checks
    notes: list = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(self.video_usd + self.image_usd + self.other_usd, 2)


def estimate(seconds: float, mean_shot: float, video: VideoModel, image: ImageModel,
             quality: str, new_elements: int = 1) -> Estimate:
    """A video with `seconds` of animation cut every `mean_shot` seconds:
    what it should cost. Used by the settings page's price line and by
    the stage before it commits to anything."""
    shots = max(1, round(seconds / max(1.0, mean_shot)))
    each = seconds / shots
    generated = shots * video.seconds_for(each)
    return Estimate(
        shots=shots, seconds=round(seconds, 1), generated=float(generated),
        video_usd=video.cost(generated, quality),
        image_usd=round((shots + new_elements) * image.estimate, 2))


def fit(shot_seconds: float, generated: float) -> tuple:
    """(speed, used): play `generated` seconds at `speed` (1.2 = faster)
    and use the first `used` seconds of source to fill `shot_seconds`."""
    if generated <= 0 or shot_seconds <= 0:
        return 1.0, 0.0
    speed = min(RETIME_MAX, max(RETIME_MIN, generated / shot_seconds))
    used = min(generated, shot_seconds * speed)
    return round(speed, 4), round(used, 3)


def mean_shot_seconds(pace: int) -> float:
    """The pace slider as an average shot length: 7.5s at 0 (lingering),
    5.5s in the middle, 3.5s at 100 (quick cutting)."""
    return round(7.5 - 0.04 * max(0, min(100, int(pace))), 2)


def whole(seconds: float) -> int:
    return int(math.ceil(seconds - 1e-6))
