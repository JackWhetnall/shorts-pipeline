# 003 — Verify every synthesized segment locally

**Status:** active

## Decision

Each synthesized segment is transcribed with a local `faster-whisper`
model (`small.en`) and diffed word-for-word against the intended text.
A mismatch retries synthesis.

## Why

This catches a different failure from the alignment check that sits
beside it. `looks_glitched` reads ElevenLabs' own alignment metadata for
a backward time jump, a repeated phrase, or too many words — but it is
blind to a synthesis artifact *inside* a word that doesn't shift any
timestamp. Transcribing the real rendered audio with a model that had
nothing to do with generating it catches that class too.

Local rather than a cloud ASR API, so a QA check doesn't add a third paid
vendor. `small.en` rather than `base.en` because the smaller model
mis-transcribed uncommon proper nouns (hearing "Aesop" as "Asop"), and
names are core content for a quote pipeline, not an edge case.

## Rejected

An audio-envelope self-similarity check, comparing energy envelopes
across the clip to catch a duplicated chunk. Validated against ten real
syntheses of known-good text, it flagged all ten. Real speech's natural
rhythm correlates with itself too readily at this timescale for a cheap
envelope check to distinguish "duplicated content" from "person talking
normally". The transcript check covers what it was for, by comparing
words rather than waveform shape.

## A bug this had

`revert_pronunciation_overrides` originally did a case-*sensitive*
`startswith`, but the transcript comparison lowercases everything first —
so the revert silently never fired on that path. Whisper "correcting" the
respelled "Jobe" back to "Job" then read as a genuine mismatch and
triggered a paid retry on perfectly good audio. Now case-insensitive and
case-preserving, with a regression test.
