# 007 — Shortlist footage before the matching call

**Status:** active

## Decision

A lexical index (SQLite FTS5, BM25) narrows the library to about 50
plausible candidates per video. Only those go to the model.

## Why

Measured against the live 264-clip library, the previous approach sent
191 KB of clip descriptions — about 52,000 input tokens — on **every**
matching call, and that call runs up to four times per video across the
fetch-and-recheck rounds. Script generation, by comparison, costs about a
thousand tokens.

So roughly 99% of Claude spend was re-describing footage already owned.
Worse, it grew on its own: auto-fetch adds clips unattended after most
renders, so each video made every future video more expensive. The
earlier note that this "scales fine to tens/low-hundreds of clips" was
correct when written, and had quietly stopped being true.

Measured after: about 10,000 tokens, a 79% reduction — and, the actual
point, a number that no longer moves as the library grows.

## Why lexical, not embeddings

It needs no new service, no API key, no index to keep warm, and nothing
extra that can go stale. And it does not have to be precise, because it
is not making the decision: it only has to get the plausible candidates
into a set of fifty that the model then reads properly. Recall matters
here; precision is the model's job.

Verified against the live library: for a segment about dawn, all 8 clips
whose descriptions actually mention dawn or sunrise appeared in the
50-clip shortlist.

## Recall safeguards

Each segment contributes its own top matches rather than one query for
the whole video, so a segment with a rare subject still gets candidates.
The shortlist is then topped up with least-recently-used clips, which
fills gaps when the lexical query finds little and keeps rotation in the
pool.

## Prompt caching, alongside

The rubric and the candidate block are stable within a video, so retry
rounds read from cache at a tenth of the input price. That is a real
saving, but it is secondary: caching makes re-sending cheaper,
shortlisting stops the thing being sent from growing.
