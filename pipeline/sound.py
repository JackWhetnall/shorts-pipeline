"""
The sound under the voice: a music bed that ducks when anyone speaks, and
small effects on the moments an animated scene moves.

Effects are synthesised here rather than downloaded: a pop, a whoosh, a
tick, a soft chime and a clink. No licence, no files, identical every
time, and quiet enough to feel like the animation's own sound rather than
decoration. They're placed on the exact moments a scene element appears,
draws, is highlighted or lands (from each scene's saved JSON).

Music comes from the channel's own folder (channels/<key>/music/), or the
shared music/ folder, and is never generated. It runs under the whole
video including the outro, fades in and out, and is ducked under speech:
a level measured from the narration itself, so it rises in the pauses and
the outro and sits well under every word. See decision 038.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np

from core.logging_setup import get_logger
from core.paths import CHANNELS_DIR, PROJECT_ROOT

log = get_logger(__name__)

SHARED_MUSIC_DIR = PROJECT_ROOT / "music"
MUSIC_SUFFIXES = (".mp3", ".wav", ".m4a", ".ogg", ".flac")

DUCK_UNDER_SPEECH = 0.35      # music gain while someone speaks, relative to its level
ATTACK, RELEASE = 0.08, 0.45  # seconds to duck, and to come back up
MUSIC_FADE_IN, MUSIC_FADE_OUT = 0.6, 1.8


# --- effects ---------------------------------------------------------------

def _envelope(n: int, fps: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(n) / fps
    return np.minimum(1.0, t / max(attack, 1e-4)) * np.exp(-t / max(decay, 1e-4))


def synth(kind: str, fps: int) -> np.ndarray:
    """One effect as a mono float array, peak exactly 1."""
    wave = _raw(kind, fps)
    return wave / (np.abs(wave).max() or 1.0)


def _raw(kind: str, fps: int) -> np.ndarray:
    rng = np.random.default_rng(7)                 # the same sound every time
    if kind == "pop":
        n = int(0.12 * fps); t = np.arange(n) / fps
        freq = 880 * np.exp(-t * 18) + 320           # a quick downward chirp
        wave = np.sin(2 * np.pi * np.cumsum(freq) / fps)
        return wave * _envelope(n, fps, 0.002, 0.035)
    if kind == "whoosh":
        n = int(0.42 * fps); t = np.arange(n) / fps
        noise = rng.standard_normal(n)
        # A sweeping low-pass: a running mean whose window shrinks as it goes.
        out = np.empty(n); acc = 0.0
        for i in range(n):
            a = 0.02 + 0.25 * (i / n)
            acc += a * (noise[i] - acc)
            out[i] = acc
        shape = np.sin(np.pi * np.clip(t / (n / fps), 0, 1)) ** 2
        return out / (np.abs(out).max() or 1) * shape
    if kind == "tick":
        n = int(0.03 * fps)
        return rng.standard_normal(n) * _envelope(n, fps, 0.0005, 0.006)
    if kind == "chime":
        n = int(0.9 * fps); t = np.arange(n) / fps
        wave = sum(a * np.sin(2 * np.pi * f * t) for f, a in ((1320, 1.0), (1980, 0.4), (2640, 0.2)))
        return wave / 1.6 * _envelope(n, fps, 0.004, 0.28)
    if kind == "clink":
        n = int(0.18 * fps); t = np.arange(n) / fps
        wave = np.sin(2 * np.pi * 2400 * t) + 0.6 * np.sin(2 * np.pi * 3700 * t)
        return wave / 1.6 * _envelope(n, fps, 0.001, 0.05)
    raise ValueError(kind)


# Which effect each scene action makes, and how loud relative to the others.
ACTION_SOUNDS = {"appear": ("pop", 0.9), "draw": ("whoosh", 0.55), "highlight": ("chime", 0.45),
                 "wiggle": ("tick", 0.6), "exit": ("whoosh", 0.35)}
MIN_GAP = 0.12                 # two effects closer than this: keep the first


def scene_cues(plan) -> list:
    """[(narration seconds, effect, gain)] for every scene in the video."""
    cues = []
    for clip in getattr(plan, "scene_clips", None) or []:
        spec = Path(clip["clip"]).with_suffix(".json")
        if not spec.exists():
            continue
        scene = json.loads(spec.read_text(encoding="utf-8"))
        start = plan.script.segments[clip["first"]].start
        for action in scene.get("actions") or []:
            at = start + float(action.get("at", 0))
            if action.get("do") in ACTION_SOUNDS:
                kind, gain = ACTION_SOUNDS[action["do"]]
                cues.append((at, kind, gain))
            elif action.get("do") == "stack":
                # One clink as each copy lands (the runtime's own timing).
                span, n = float(action.get("dur") or 2), int(action.get("count") or 5)
                fall = min(0.7, span / n * 1.4)
                cues += [(at + i * span / n + fall, "clink", 0.7) for i in range(n)]
    cues.sort()
    kept = []
    for cue in cues:
        if not kept or cue[0] - kept[-1][0] >= MIN_GAP:
            kept.append(cue)
    return kept


def add_effects(track: np.ndarray, fps: int, cues: list, level: float) -> np.ndarray:
    """`cues` in track seconds. Mixed in place, mono effects to every channel."""
    cache = {}
    for at, kind, gain in cues:
        sound = cache.setdefault(kind, synth(kind, fps))
        i = int(at * fps)
        if i >= len(track):
            continue
        piece = sound[: len(track) - i] * gain * level
        track[i:i + len(piece)] += piece[:, None]
    return track


# --- music -----------------------------------------------------------------

def music_tracks(channel_key: str) -> list:
    folders = [CHANNELS_DIR / channel_key / "music", SHARED_MUSIC_DIR]
    for folder in folders:
        found = sorted(p for p in folder.glob("*") if p.suffix.lower() in MUSIC_SUFFIXES) \
            if folder.exists() else []
        if found:
            return found
    return []


def speech_envelope(voice: np.ndarray, fps: int) -> np.ndarray:
    """0-1 per sample: how much someone is speaking, smoothed so the music
    ducks quickly and comes back up gently."""
    hop = int(0.02 * fps)
    mono = np.abs(voice).mean(axis=1) if voice.ndim > 1 else np.abs(voice)
    frames = len(mono) // hop + 1
    padded = np.pad(mono, (0, frames * hop - len(mono)))
    rms = np.sqrt((padded.reshape(frames, hop) ** 2).mean(axis=1))
    active = (rms > max(0.01, rms.max() * 0.06)).astype(float)
    smooth = np.empty(frames); level = 0.0
    up, down = hop / fps / ATTACK, hop / fps / RELEASE
    for i, a in enumerate(active):
        level += (up if a > level else -down) if a != level else 0.0
        level = min(1.0, max(0.0, level))
        smooth[i] = level
    return np.repeat(smooth, hop)[: len(mono)]


def music_bed(track_path: Path, length: int, fps: int, channels: int,
              voice: np.ndarray, level: float) -> np.ndarray:
    from pipeline.audio import decode_audio_file

    music = decode_audio_file(str(track_path), fps=fps, nchannels=channels)
    if len(music) == 0:
        return np.zeros((length, channels))
    reps = int(np.ceil(length / len(music)))
    music = np.concatenate([music] * reps, axis=0)[:length]
    peak = np.abs(music).max() or 1.0
    music = music / peak
    t = np.arange(length) / fps
    total = length / fps
    fade = np.minimum(1.0, t / MUSIC_FADE_IN) * np.clip((total - t) / MUSIC_FADE_OUT, 0, 1)
    duck = 1.0 - (1.0 - DUCK_UNDER_SPEECH) * speech_envelope(voice, fps)
    return music * (level * fade * duck)[:, None]


def mix(voice: np.ndarray, fps: int, channel, plan, to_track_time) -> np.ndarray:
    """The finished soundtrack: `voice` (the whole video's narration with
    its card silences) plus music and effects, per the channel's settings.
    `to_track_time` maps narration seconds to track seconds (a title card
    in front shifts everything after it)."""
    sound = channel.sound
    out = voice.astype(float).copy()
    if sound.effects and getattr(plan, "scene_clips", None):
        cues = [(to_track_time(t), kind, gain) for t, kind, gain in scene_cues(plan)]
        out = add_effects(out, fps, cues, sound.effects_level)
    if sound.music:
        tracks = music_tracks(channel.key)
        if tracks:
            pick = random.Random(plan.stem).choice(tracks)
            log.info(f"  [sound] music: {pick.name}")
            out += music_bed(pick, len(out), fps, out.shape[1], voice, sound.music_level)
        else:
            log.info("  [sound] no music: add tracks to channels/<key>/music or music/")
    peak = np.abs(out).max()
    if peak > 0.98:                                  # never clip: scale the whole mix down
        out *= 0.98 / peak
    return out
