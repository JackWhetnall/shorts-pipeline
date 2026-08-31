"""
Shared audio-array helpers.

Decoding goes through a single direct ffmpeg subprocess call
(decode_audio_file), not moviepy's AudioFileClip/iter_chunks. That path
(moviepy's FFMPEG_AudioReader.buffer_around, used to stream a large clip in
chunks) has an off-by-one in how it recycles the tail of its internal
buffer each time the read position outgrows it — a real, deterministic bug,
confirmed by diffing moviepy's decode of a real generated narration file
against a plain ffmpeg decode of the same file: the two matched exactly up
to a point, then moviepy's version had one duplicated sample, shifting
everything after it by one sample — and it recurs roughly every time the
internal buffer recenters (every ~2 seconds of audio), not as a rare
one-off. Across a full narration track that's dozens of small, evenly
spaced insertions — audible as a persistent, deterministic stutter, not a
1%-of-the-time API hiccup, and unaffected by retrying synthesis since the
corruption happens in decoding the output, not in generating it. A single
linear ffmpeg pass has no seek/recenter step to get wrong.

Used by tts_captions.py (decoding each synthesized segment before
stitching them together with real pauses) and video_assemble.py (padding
the narration audio with silence under the outro card) — both build audio
out of raw sample arrays rather than compositing moviepy AudioClips, which
mishandles mixing clips with different channel counts.
"""

import subprocess

import imageio_ffmpeg
import numpy as np


def decode_audio_file(path: str, fps: int = 44100, nchannels: int = 2) -> np.ndarray:
    """Decodes an audio file to a (samples, nchannels) float array in
    [-1, 1] via one direct ffmpeg call — no seeking, no internal
    buffering/recentering to get wrong."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg, "-i", str(path), "-f", "s16le", "-acodec", "pcm_s16le",
           "-ar", str(fps), "-ac", str(nchannels), "-loglevel", "error", "-"]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed to decode {path}: {result.stderr.decode(errors='replace')}")
    samples = np.frombuffer(result.stdout, dtype="int16").astype(np.float32)
    return (samples / 32768.0).reshape(-1, nchannels)


def silence_array(seconds: float, fps: int, nchannels: int) -> np.ndarray:
    return np.zeros((int(seconds * fps), nchannels))


def apply_fade(arr: np.ndarray, fps: int, fade_in: float = 0.0, fade_out: float = 0.0) -> np.ndarray:
    """Linear fade in/out (seconds) applied in place to a (samples, channels)
    array. Splicing separately-encoded audio segments together with hard
    cuts can leave an audible click/stutter at each seam if the waveform
    doesn't happen to cross zero right at the cut point — a short fade
    smooths that out regardless of what's on either side of the cut."""
    arr = arr.astype(np.float32, copy=True)
    n = len(arr)
    if fade_in > 0:
        samples = min(int(fade_in * fps), n)
        arr[:samples] *= np.linspace(0, 1, samples, dtype=np.float32).reshape(-1, 1)
    if fade_out > 0:
        samples = min(int(fade_out * fps), n)
        arr[-samples:] *= np.linspace(1, 0, samples, dtype=np.float32).reshape(-1, 1)
    return arr
