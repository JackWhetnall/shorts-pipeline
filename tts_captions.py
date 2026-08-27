"""
Generates the voiceover AND word-level caption timings in one pass.

edge-tts streams "WordBoundary" events as it synthesizes, giving exact
start times for every word — so there's no separate alignment/Whisper
step needed for captions.

The script is spoken as three separate segments (quote, reference,
reflection) synthesized individually and stitched back together with
silence in between. That gives real, controllable pauses — quote, pause,
reference, pause, reflection — instead of relying on punctuation to
create a natural-sounding cadence.
"""

import asyncio
from pathlib import Path

import edge_tts
import numpy as np
from moviepy.editor import AudioFileClip
from moviepy.audio.AudioClip import AudioArrayClip

PAUSE_AFTER_QUOTE = 0.7
PAUSE_AFTER_REFERENCE = 0.5

# Default chunk size moviepy's readers are built around — large deviations
# (e.g. reading a whole clip in one giant chunk) confuse the underlying
# ffmpeg reader's rolling buffer and produce out-of-bounds reads.
_CHUNKSIZE = 50000


def _read_soundarray(clip: AudioFileClip, fps: int):
    """
    Equivalent to clip.to_soundarray(fps=fps), but avoids moviepy's
    to_soundarray calling np.vstack/np.hstack directly on a generator —
    modern numpy rejects that. We materialize the chunks ourselves first.
    """
    chunks = list(clip.iter_chunks(chunksize=_CHUNKSIZE, fps=fps, quantize=False, nbytes=2))
    if not chunks:
        return np.zeros((0, clip.nchannels))
    stacker = np.vstack if clip.nchannels == 2 else np.hstack
    return stacker(chunks)


async def _tts_segment(text: str, voice: str, out_path: str):
    """Synthesize one segment, returning its word timings (seconds, relative
    to the start of this segment)."""
    communicate = edge_tts.Communicate(text, voice, boundary="WordBoundary")
    word_timings = []

    with open(out_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10_000_000
                duration = chunk["duration"] / 10_000_000
                word_timings.append({
                    "word": chunk["text"],
                    "start": start,
                    "end": start + duration,
                })

    return word_timings


async def _synthesize(parts: dict, voice: str, out_audio_path: str):
    segments = [
        (parts["quote"], PAUSE_AFTER_QUOTE),
        (parts["reference"], PAUSE_AFTER_REFERENCE),
        (parts["reflection"], 0.0),
    ]

    out_path = Path(out_audio_path)
    seg_paths = [out_path.with_name(f"{out_path.stem}_seg{i}.mp3") for i in range(len(segments))]

    # Build the final track as a raw sample array rather than compositing
    # moviepy AudioClips — moviepy's CompositeAudioClip mishandles mixing
    # clips with different channel counts (real speech vs. synthetic
    # silence), so we do the concatenation ourselves.
    arrays = []
    all_timings = []
    offset = 0.0
    fps = None
    nchannels = None

    try:
        for i, (text, pause) in enumerate(segments):
            timings = await _tts_segment(text, voice, str(seg_paths[i]))
            clip = AudioFileClip(str(seg_paths[i]))
            fps = fps or clip.fps
            arr = _read_soundarray(clip, fps)
            clip.close()

            if arr.ndim == 1:
                arr = arr.reshape(-1, 1)
            if nchannels is None:
                nchannels = arr.shape[1]
            elif arr.shape[1] != nchannels:
                arr = np.repeat(arr.mean(axis=1, keepdims=True), nchannels, axis=1)

            arrays.append(arr)
            for t in timings:
                all_timings.append({
                    "word": t["word"],
                    "start": t["start"] + offset,
                    "end": t["end"] + offset,
                })
            offset += len(arr) / fps

            if pause > 0:
                arrays.append(np.zeros((int(pause * fps), nchannels)))
                offset += pause

        final_array = np.concatenate(arrays, axis=0)
        final_clip = AudioArrayClip(final_array, fps=fps)
        final_clip.write_audiofile(out_audio_path, codec="libmp3lame", logger=None)
        final_clip.close()
    finally:
        for seg_path in seg_paths:
            seg_path.unlink(missing_ok=True)

    return out_audio_path, all_timings


def generate_voiceover(parts: dict, voice: str, out_audio_path: str):
    """
    Sync wrapper — call this from the main pipeline.

    parts: {"quote": ..., "reference": ..., "reflection": ...} as returned
    by script_gen.generate_script.
    Returns (audio_path, word_timings) where word_timings is a list of
    dicts: {"word": str, "start": float_seconds, "end": float_seconds}
    """
    return asyncio.run(_synthesize(parts, voice, out_audio_path))


if __name__ == "__main__":
    demo_parts = {
        "quote": "The quick brown fox jumps over the lazy dog.",
        "reference": "Aesop 1:1",
        "reflection": "Simple words, said plainly, still land.",
    }
    cache_dir = Path(__file__).parent / "cache"
    cache_dir.mkdir(exist_ok=True)
    path, timings = generate_voiceover(
        demo_parts,
        "en-US-GuyNeural",
        str(cache_dir / "test.mp3"),
    )
    print(path)
    print(timings[:5])
