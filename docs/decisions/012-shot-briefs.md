# 012 — Shot briefs, and a rubric that scores editing

**Status:** active. Supersedes the scoring bands in
[004](004-semantic-footage-matching.md).

## The problem

Footage matching never worked well. Library clips scored low against
almost every segment, and — the damning part — clips fetched *specifically
for* a segment were scored as unsuitable for the very segment that
searched for them. The confidence bar was lowered from 7 to 6 to 5 to
compensate, which never fixed it.

## The cause

Two things, and they compounded.

**Keywords were abstract.** Measured across every video this project has
generated: 172 keywords, 116 unique. Of those, **74 (63%) appear nowhere
in any of the 264 clip descriptions.** Not "poor match" — the words do not
occur. They are things like:

> integrity · dignity · conviction · empathy · clarity · courage ·
> awakening · humility · desperation · accountability

Nothing films an abstract noun. Meanwhile clip descriptions are intensely
literal: *"Dark wooden prayer beads coiled on a polished wooden table,
with a closed leather-bound Bible at the edge of frame."* The matcher was
being asked to bridge "conviction" to that, on every segment, forever.

**The rubric forbade the only kind of match available.** Its bottom band
read:

> **1-4:** the same general theme or mood ONLY, with no real connection to
> the specific subject. This band is a MISS, not a soft yes.

For reflective narration there *is* no specific subject to depict. So by
its own rules the rubric was correct to score everything 1-4 — and the
threshold was then lowered to overrule it. That also explains the fetched
clips being rejected: you search "hoping", get a person at a window, and
the rubric calls it mood-only. The download was fine; the scoring was
wrong.

The rubric had been written as though matching footage to a product demo.
Background footage under reflective narration is *supposed* to be
evocative.

## The decision

**Every segment carries a shot brief** — one literal, filmable sentence
describing what should be on screen — produced by the script generator
alongside the words, while it still has the passage in front of it. It
costs nothing extra: the call is already happening. Keywords become
concrete terms drawn from that brief.

Retrieval and matching both run against the brief, never the spoken line.
Both sides of the comparison are then literal, which is what BM25 and the
model are each good at.

**The rubric asks one question:** *would a competent editor cut to this
clip here?* Bands penalise **contradiction** (a clip that fights the
narration) and **inertness** (a clip nobody would notice), and explicitly
do not penalise abstraction or familiarity. A calm ocean under a calm line
is an editor making an easy correct choice, not a failure.

## Measured effect

Same library, same segments, old query versus new, top BM25 hit:

| Spoken line | Old top hit | New top hit |
|---|---|---|
| "…a song could outlast generations and still carry a warning" | an **ambulance** (matched "warning") | Egyptian hieroglyph carvings |
| "God isn't surprised by human failure" | a woman with black hair | a **white pillar candle** |
| "worth sitting with… something honest" | hands with red-painted nails | **calm water at dawn** |
| "Doubt… is often the road into it" | a man in dark clothing | **a country road POV** |

BM25 scores roughly doubled (−5 to −12 became −13 to −23), meaning far
stronger lexical evidence rather than a near-random pick.

## The threshold

Left at 5, but it now means something different. Under this rubric 5-6 is
"right feeling, nothing works against the line" — where most usable b-roll
genuinely sits — rather than "a weak stretch". Raise it to 6 once there is
discard-reason data showing footage complaints have dropped; that data
did not exist when this was written and is the reason the problem went
unnoticed for so long.

## Also fixed here

The response schema carried `minItems`/`maxItems` equal to the segment
count. The API rejects array bounds other than 0 or 1 and returned a 400
on every generation. The count is now stated in the prompt and verified in
code, which warns rather than failing a run that has already paid for a
script.
