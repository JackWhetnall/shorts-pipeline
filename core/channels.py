"""
Channel configuration: a validated schema, not a dict of dicts.

What this replaces: nine separate DEFAULT_* dictionaries merged onto
`**fields` by a function that checked nothing. A channel missing its
`voice` surfaced as a KeyError several layers deep inside TTS, minutes
into a render that had already paid for a script. A colour stored as a
JSON list had to be hand-converted to a tuple on the way in because PIL
wants a tuple. And because settings saves rewrote the COMPLETE entry,
any field the setup wizard could set also had to appear on the settings
form or a later save silently erased it — a trap the old docs described
at length rather than removed.

All three go away here. Fields are declared once with their types and
defaults; `load_channels()` validates and names both the channel and the
field when something is wrong; and `to_sparse_dict()` writes back only
what actually differs from the defaults, so a form that doesn't know
about a field can no longer clobber it.

`channels.json` carries a `version` so a future field rename has
somewhere to hook a migration. Version 1 (a bare {key: entry} mapping,
what this project wrote until now) is detected and upgraded in memory on
read, then persisted in the new shape on the next write — no manual
migration step, no flag day.

Key order in the file IS display order in the web UI, so every read and
write here preserves it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path

from core.errors import ConfigError
from core.paths import CHANNELS_JSON_PATH

SCHEMA_VERSION = 2

# ElevenLabs voice ids: 20 alphanumeric characters.
VOICE_ID_RE = re.compile(r"^[A-Za-z0-9]{20}$")

CONTENT_MODES = ("static_corpus", "topic")
CTA_KEYS = ("patreon", "merch", "affiliate")


class _MappingLike:
    """Lets a config dataclass be read like the dict it replaced.

    Templates iterate `pacing.items()` to render a form field per setting,
    which is genuinely the right thing for a form that should grow a row
    whenever a setting is added. Supporting that costs three methods and
    keeps the schema's type-checking, validation and defaults — the
    alternative was either staying a bare dict or hand-listing every
    field in the template and forgetting to update it.
    """

    def items(self):
        return [(f.name, getattr(self, f.name)) for f in fields(self)]

    def keys(self):
        return [f.name for f in fields(self)]

    def __getitem__(self, name):
        try:
            return getattr(self, name)
        except AttributeError as exc:
            raise KeyError(name) from exc

    def get(self, name, default=None):
        return getattr(self, name, default)


@dataclass
class Pacing(_MappingLike):
    """Timing and rhythm. A reflective quote channel wants long, lingering
    shots; a jokes channel wants a tight setup/pause/punchline beat. That
    difference is entirely these numbers — no code branches on format."""

    pause_after_first_segment: float = 0.7
    pause_after_citation: float = 0.5
    pause_between_segments: float = 0.4
    max_shot_seconds: float = 5.0
    crossfade: float = 0.5
    outro_seconds: float = 3.0
    caption_max_group_size: int = 4
    caption_pause_gap_threshold: float = 0.25
    # static_corpus: analysis segments beyond the quote itself.
    # topic: total segments.
    segment_count: int = 3


@dataclass
class Style(_MappingLike):
    """Caption and outro visuals."""

    # A key from core.fonts, not a filename: the same typeface ships
    # under different names across platforms, and a channel set up on one
    # machine has to still render on another.
    font_face: str = "arial_bold"
    font_size: int = 68
    base_color: str = "#FFFFFF"
    highlight_color: str = "#FFD400"
    stroke_color: str = "#000000"
    stroke_width: int = 4
    outro_bg_color: tuple = (10, 10, 14, 255)
    outro_title_color: str = "#FFFFFF"
    outro_subtext_color: str = "#FFD400"

    def __post_init__(self):
        # JSON has no tuples, PIL won't take a list. Normalising here
        # means neither the storage layer nor the renderer has to know.
        if isinstance(self.outro_bg_color, list):
            self.outro_bg_color = tuple(self.outro_bg_color)


@dataclass
class Cta(_MappingLike):
    enabled: bool = False
    text: str = ""


@dataclass
class EndScreen(_MappingLike):
    """An optional second card after the branding outro. `enabled` gates
    only whether the video segment renders — each CTA's own flag is what
    means "actively promoted", and is read by the description generator
    too. So a link can be promoted in the description without spending
    video seconds on it, or the reverse."""

    enabled: bool = False
    duration_seconds: float = 3.0
    ctas: dict = field(default_factory=lambda: {
        "patreon": Cta(text="Support us on Patreon"),
        "merch": Cta(text="Check out our merch"),
        "affiliate": Cta(text="Shop our picks below"),
    })

    def __post_init__(self):
        defaults = {
            "patreon": "Support us on Patreon",
            "merch": "Check out our merch",
            "affiliate": "Shop our picks below",
        }
        resolved = {}
        for key in CTA_KEYS:
            raw = self.ctas.get(key)
            if isinstance(raw, Cta):
                cta = raw
            else:
                raw = raw or {}
                cta = Cta(enabled=bool(raw.get("enabled", False)),
                          text=(raw.get("text") or "").strip())
            # An empty text falls back to the default rather than
            # rendering a blank card — the old form-parsing code resolved
            # this by hand at every save site instead.
            cta.text = cta.text or defaults[key]
            resolved[key] = cta
        self.ctas = resolved


@dataclass
class Monetization(_MappingLike):
    """Plain config, pasted in by hand. This project never creates a
    Patreon page, merch store, or Amazon Associates account on anyone's
    behalf. affiliate_links is a list of {"label", "url"}."""

    patreon_url: str = ""
    merch_url: str = ""
    affiliate_links: list = field(default_factory=list)


@dataclass
class Socials(_MappingLike):
    """Where this channel actually lives. Informational — nothing in the
    render path reads these."""

    youtube_url: str = ""
    tiktok_url: str = ""
    instagram_url: str = ""


@dataclass
class ChannelConfig:
    key: str
    channel_display_name: str = ""
    content_mode: str = "topic"
    voice: str = ""
    style_prompt: str = ""
    outro_subtext: str = "Subscribe for more"
    output_dir: str = ""
    # static_corpus only: a key in pipeline.quote_source.SOURCES.
    source: str = ""
    # topic only: the pool a seed is drawn from.
    topics: list = field(default_factory=list)
    # Imagery this channel must never show, however well a clip otherwise
    # scores. The footage library is shared across channels, so a clip
    # can be a strong thematic match and still be completely wrong for
    # one audience.
    avoid_imagery: list = field(default_factory=list)
    # ElevenLabs' own voice_settings.speed. 1.0 = normal.
    speed: float = 1.0
    pacing: Pacing = field(default_factory=Pacing)
    style: Style = field(default_factory=Style)
    monetization: Monetization = field(default_factory=Monetization)
    socials: Socials = field(default_factory=Socials)
    end_screen: EndScreen = field(default_factory=EndScreen)
    archived: bool = False
    # Launch-checklist items marked done by hand. Some steps (Patreon's
    # signup flow) are annoying enough that "noting I'm skipping this"
    # beats leaving it red forever.
    manual_checklist_overrides: list = field(default_factory=list)

    def __post_init__(self):
        if not self.output_dir:
            self.output_dir = f"output/{self.key}"
        if not self.channel_display_name:
            self.channel_display_name = self.key.replace("_", " ").title()

    # Templates and older call sites index channels like dicts. Jinja
    # already falls back from subscript to attribute access, but Python
    # callers don't, and supporting both kept this refactor from having
    # to land in one atomic commit.
    def __getitem__(self, name):
        try:
            return getattr(self, name)
        except AttributeError as exc:
            raise KeyError(name) from exc

    def get(self, name, default=None):
        return getattr(self, name, default)

    def validate(self) -> None:
        """Raises ConfigError naming the channel and the field. Called on
        every load, so a malformed channel fails at startup with a
        readable message instead of mid-render with a KeyError."""
        where = f'Channel "{self.key}"'
        if self.content_mode not in CONTENT_MODES:
            raise ConfigError(
                f"{where} has content_mode {self.content_mode!r}, which isn't recognised. "
                f"It must be one of: {', '.join(CONTENT_MODES)}."
            )
        if not self.voice.strip():
            raise ConfigError(f"{where} has no voice set. Add an ElevenLabs voice ID in its settings.")
        # ElevenLabs voice ids are 20 alphanumeric characters. Checking the
        # shape catches a placeholder typed to get past a required field —
        # which otherwise surfaces as an API error minutes into a render,
        # after a script has already been paid for.
        if not VOICE_ID_RE.match(self.voice.strip()):
            raise ConfigError(
                f'{where} has {self.voice.strip()!r} as its voice, which is not an '
                f"ElevenLabs voice ID. Pick one in the Voice Lab and apply it."
            )
        if not self.style_prompt.strip():
            raise ConfigError(f"{where} has no style prompt. That's what tells the AI how to write for this channel.")
        if self.content_mode == "static_corpus" and not self.source.strip():
            raise ConfigError(f'{where} reads from a fixed source but no source is set (for example "bible").')
        # A topic channel needs somewhere for topics to come from: either a
        # syllabus or the flat list. Checked in that order because a channel
        # with a syllabus should not also have to keep a redundant list.
        if self.content_mode == "topic" and not self.topics and not self._has_curriculum():
            raise ConfigError(
                f"{where} generates from topics but has neither a topic plan nor a "
                f"topic list. Make a topic plan, or add topics in its settings."
            )
        if self.pacing.segment_count < 1:
            raise ConfigError(f"{where} has a segment count below 1. It needs at least one segment.")
        if self.speed <= 0:
            raise ConfigError(f"{where} has a speech speed of {self.speed}. It must be greater than 0.")
        self._validate_output_dir(where)

    def _has_curriculum(self) -> bool:
        # Imported here: core.curriculum imports core.paths, and a module
        # cycle at import time is worse than a local import.
        from core import curriculum
        return curriculum.exists(self.key)

    def _validate_output_dir(self, where: str) -> None:
        """The output directory must be a folder of this channel's own.

        This is not hypothetical. The create form used to pre-fill the box
        with "output/" + the key, and on the new-channel page the key is
        empty at render time — so submitting it unchanged pointed the
        channel at the output ROOT, and its gallery showed every other
        channel's videos as its own.
        """
        from core.paths import OUTPUT_DIR, PROJECT_ROOT

        raw = (self.output_dir or "").strip().replace("\\", "/").rstrip("/")
        if not raw:
            self.output_dir = f"output/{self.key}"
            return
        resolved = (PROJECT_ROOT / raw).resolve()
        if resolved == OUTPUT_DIR.resolve() or resolved == PROJECT_ROOT.resolve():
            raise ConfigError(
                f'{where} has its output directory set to "{self.output_dir}", which '
                f"is the folder every channel writes into. Its gallery would show "
                f"every other channel's videos. Use output/{self.key}."
            )
        self.output_dir = raw

    @property
    def output_path(self) -> Path:
        from core.paths import PROJECT_ROOT
        return PROJECT_ROOT / self.output_dir


# --- (de)serialisation ------------------------------------------------

_NESTED = {
    "pacing": Pacing,
    "style": Style,
    "monetization": Monetization,
    "socials": Socials,
    "end_screen": EndScreen,
}


def _build_nested(cls, raw: dict):
    if cls is EndScreen:
        return EndScreen(
            enabled=bool(raw.get("enabled", False)),
            duration_seconds=float(raw.get("duration_seconds", 3.0)),
            ctas=raw.get("ctas") or {},
        )
    known = {f.name for f in fields(cls)}
    unknown = set(raw) - known
    if unknown:
        # Not fatal: an old field left behind by a previous version
        # shouldn't stop the app from starting. It's dropped on next save.
        pass
    return cls(**{k: v for k, v in raw.items() if k in known})


def channel_from_dict(key: str, raw: dict) -> ChannelConfig:
    known = {f.name for f in fields(ChannelConfig)} - {"key"}
    kwargs = {k: v for k, v in raw.items() if k in known and k not in _NESTED}
    for name, cls in _NESTED.items():
        kwargs[name] = _build_nested(cls, raw.get(name) or {})
    return ChannelConfig(key=key, **kwargs)


def _to_plain(value):
    if is_dataclass(value):
        return {f.name: _to_plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    return value


def _sparse(value, default):
    """Recursively strip anything equal to its default. Returns None when
    the whole value is default (the caller then omits the key)."""
    if is_dataclass(value) and is_dataclass(default):
        out = {}
        for f in fields(value):
            sub = _sparse(getattr(value, f.name), getattr(default, f.name))
            if sub is not None:
                out[f.name] = sub
        return out or None
    if isinstance(value, dict) and isinstance(default, dict):
        out = {}
        for k, v in value.items():
            sub = _sparse(v, default.get(k))
            if sub is not None:
                out[k] = sub
        return out or None
    plain = _to_plain(value)
    return None if plain == _to_plain(default) else plain


def channel_to_sparse_dict(channel: ChannelConfig) -> dict:
    """Only what differs from the defaults.

    This is what removes the wipe-on-save trap. Saves used to write every
    field, so a form missing an input for some field wrote that field's
    empty value over real data. A sparse write can only ever change what
    it actually carries.
    """
    reference = ChannelConfig(key=channel.key)
    out = {}
    for f in fields(channel):
        if f.name == "key":
            continue
        sub = _sparse(getattr(channel, f.name), getattr(reference, f.name))
        if sub is not None:
            out[f.name] = sub
    # Always written even when it matches the derived default: these two
    # identify the channel, and a config file where they're invisible is
    # much harder to read by hand.
    out["channel_display_name"] = channel.channel_display_name
    out["content_mode"] = channel.content_mode
    return out


# --- file access ------------------------------------------------------

def read_raw(path: Path = None) -> dict:
    """{key: entry} in file order, whichever schema version is on disk.

    Version 1 was a bare mapping of channels at the top level. Version 2
    wraps that under "channels" alongside a "version". Detected by shape,
    so nobody has to run a migration.
    """
    path = path or CHANNELS_JSON_PATH
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "channels" in data and "version" in data:
        return data["channels"]
    return data


def write_raw(entries: dict, path: Path = None) -> None:
    path = path or CHANNELS_JSON_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": SCHEMA_VERSION, "channels": entries}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def load_channels(path: Path = None, validate: bool = True) -> dict:
    """{key: ChannelConfig} in file order.

    Re-read every time rather than cached: the web app saves and then
    immediately renders, and a stale module-level copy is exactly the bug
    that behaviour used to cause.
    """
    channels = {}
    for key, raw in read_raw(path).items():
        channel = channel_from_dict(key, raw or {})
        if validate:
            channel.validate()
        channels[key] = channel
    return channels


def save_channel(channel: ChannelConfig, path: Path = None) -> None:
    """Write one channel, preserving every other entry and the file's key
    order (which is the web UI's display order)."""
    entries = read_raw(path)
    entries[channel.key] = channel_to_sparse_dict(channel)
    write_raw(entries, path)


# --- shared derivations -----------------------------------------------

def resolve_active_ctas(monetization: Monetization, end_screen: EndScreen) -> list:
    """Which monetization CTAs are actually live: switched on AND pointing
    at something real.

    One definition, called by both the end-screen renderer and the
    description generator, so the video and its description can never
    disagree about what's being promoted. An enabled-but-empty CTA is
    skipped rather than rendering a blank line.
    """
    active = []
    ctas = end_screen.ctas

    if ctas["patreon"].enabled and monetization.patreon_url:
        active.append({"type": "patreon", "text": ctas["patreon"].text,
                       "url": monetization.patreon_url})
    if ctas["merch"].enabled and monetization.merch_url:
        active.append({"type": "merch", "text": ctas["merch"].text,
                       "url": monetization.merch_url})
    if ctas["affiliate"].enabled and monetization.affiliate_links:
        active.append({"type": "affiliate", "text": ctas["affiliate"].text,
                       "links": monetization.affiliate_links})
    return active
