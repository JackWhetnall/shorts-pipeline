# 006 — Keep the pipeline format-agnostic

**Status:** active

## Decision

Everything downstream of script generation works on a uniform contract —
a list of segments, each with text and footage keywords, plus an optional
citation — regardless of what produced it.

Two seed types: `static_corpus` (a fixed source is fetched; the
citation-bearing case) and `topic` (nothing is fixed; every segment is
generated from a topic and the channel's style prompt). What kind of
content a topic channel makes is entirely that style prompt. No code
anywhere knows what a "dad joke" is.

## Why

The first two channels are quote channels, but quotes are the first thing
built, not necessarily the long-term core. Optimising the pipeline for
the quote shape would make every later format a rewrite.

Pacing and visual style are per-channel config for the same reason: a
reflective quote channel wants slow, lingering shots while a jokes
channel wants a tight setup/pause/punchline beat, and that should be a
config difference rather than a code change.

## Deliberately deferred

Live and current-events content with fact-checking. It carries a
different kind of risk — editorial and factual liability — from anything
else here, and building it speculatively means guessing at what a
"verified news segment" actually needs. Topic-driven generation needed no
such deferral: it is the same "no source text, generate it" shape already
built.

## Watch item

Cross-channel sameness at volume. If every channel has an identical
structure, pacing and beat count, that pattern reads as mass production
on its own, independent of any single video's quality. Per-channel pacing
config helps but does not settle it.
