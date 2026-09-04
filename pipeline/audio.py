"""
Raw audio helpers.

Decoding goes through one direct ffmpeg subprocess call, never moviepy's
AudioFileClip/iter_chunks. That path streams through an internal rolling
buffer whose recentring logic has an off-by-one, duplicating one sample
almost every time it recentres — roughly every two seconds of audio.
Confirmed by diffing moviepy's decode of a real narration file against a
plain ffmpeg decode of the same file: identical up to a point, then one
extra sample, shifting everything after it.

Across a full narration track that's dozens of evenly spaced insertions,
audible as a persistent stutter. It was 100% reproducible and completely
unaffected by retrying synthesis, because the corruption happened while
decoding our own output rather than while generating it. A single linear
pass has no seek or recentre step to get wrong.

Everything here works on raw sample arrays rather than moviepy AudioClips
because compositing clips with different channel counts (real speech
against synthetic silence) is mishandled there too.
"""

from __future__ import annotations

import subprocess

import imageio_ffmpeg
import numpy as np

from core.errors import PipelineError

DEFAULT_SAMPLE_RATE = 44100
DEFAULT_CHANNELS = 2


def decode_audio_file(path: str, fps: int = DEFAULT_SAMPLE_RATE,
                      nchannels: int = DEFAULT_CHANNELS) -> np.ndarray:
    """Decode to a (samples, channels) float array in [-1, 1]."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    result = subprocess.run(
        [ffmpeg, "-i", str(path), "-f", "s16le", "-acodec", "pcm_s16le",
         "-ar", str(fps), "-ac", str(nchannels), "-loglevel", "error", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise PipelineError(
            f"ffmpeg failed to decode {path}: {result.stderr.decode(errors='replace')}",
            user_message="An audio file couldn't be read back after being generated.",
        )
    samples = np.frombuffer(result.stdout, dtype="int16").astype(np.float32)
    return (samples / 32768.0).reshape(-1, nchannels)


def silence_array(seconds: float, fps: int, nchannels: int) -> np.ndarray:
    return np.zeros((int(seconds * fps), nchannels))


def apply_fade(arr: np.ndarray, fps: int, fade_in: float = 0.0,
               fade_out: float = 0.0) -> np.ndarray:
    """Linear fade in/out in seconds, on a copy.

    Splicing separately-encoded segments with hard cuts leaves an audible
    click wherever the waveform isn't near zero at the seam — and every
    seam here is a sentence boundary, which is exactly where it was
    reported. A few milliseconds of fade removes it regardless of cause.
    """
    arr = arr.astype(np.float32, copy=True)
    n = len(arr)
    if fade_in > 0:
        samples = min(int(fade_in * fps), n)
        if samples:
            arr[:samples] *= np.linspace(0, 1, samples, dtype=np.float32).reshape(-1, 1)
    if fade_out > 0:
        samples = min(int(fade_out * fps), n)
        if samples:
            arr[-samples:] *= np.linspace(1, 0, samples, dtype=np.float32).reshape(-1, 1)
    return arr


def match_channels(arr: np.ndarray, nchannels: int) -> np.ndarray:
    """Coerce an array to `nchannels`, mixing down to mono first when
    widening. Segments occasionally come back mono where others are
    stereo; concatenating those without this raises a shape error deep in
    numpy rather than anywhere informative."""
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    if arr.shape[1] == nchannels:
        return arr
    return np.repeat(arr.mean(axis=1, keepdims=True), nchannels, axis=1)
