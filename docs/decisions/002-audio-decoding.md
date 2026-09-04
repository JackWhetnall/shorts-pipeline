# 002 — Decode audio with a direct ffmpeg call

**Status:** active

## Decision

`pipeline/audio.decode_audio_file` shells out to ffmpeg once, linearly.
moviepy's `AudioFileClip` / `iter_chunks` is never used for decoding.

## Why

Narration had a persistent, deterministic stutter — every video, not an
occasional glitch.

It was never ElevenLabs. moviepy's `FFMPEG_AudioReader.buffer_around`
streams a clip through an internal rolling buffer, and its recentring
logic has an off-by-one that duplicates one sample almost every time the
buffer recentres — roughly every two seconds of audio.

Confirmed by diffing moviepy's decode of a real narration file against a
plain ffmpeg decode of the same file: identical up to a point, then
moviepy's had one extra sample, shifting everything after it by one.
Across a full track that's dozens of evenly spaced insertions.

The reason this took so long to find is instructive: the corruption
happened while decoding *our own output*, not while generating it, so
retrying synthesis changed nothing and every investigation aimed at the
vendor.

A single linear pass has no seek or recentre step to get wrong. Verified:
two independent decodes of the same file are now bit-identical.

## Consequence

Everything in the audio path works on raw sample arrays rather than
moviepy `AudioClip`s, which also avoids that library mishandling clips
with different channel counts.
