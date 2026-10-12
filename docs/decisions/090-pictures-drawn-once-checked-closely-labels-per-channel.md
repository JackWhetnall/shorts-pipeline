# 090 — Pictures drawn once and checked closely; labels per channel; titles swapped free

**Status:** active. Amends 088 (depth) and 086 (angle page).

## What happened

On 12 October the owner found the first Why, Though? film "much much
better", and listed what still wasn't right:
- the depth was "still distorting shapes in a slightly sickening way";
- the bottom-left place labels looked like "a default label that is
  shared between all channels";
- the title sounded "meant to be captivating but actually isn't", and
  the Angle page's numbers (6.6, 51) weren't explained;
- a drill had a face and a character had three arms;
- the same Earth cutaway was drawn many times when it "only needed to
  be generated once".

## Decisions

**Depth off by default** (`documentary.depth: False`). The code stays,
and a channel can switch it on in Settings ("Depth on camera moves").

**Labels are a channel's own** (`documentary.captions`).
- The choices are "corner" (the old lower-left band), "tag" (a small
  pill in the channel's accent colour, top left) or "none".
- One Day In History keeps the corner; Why, Though? has none.
- The setting is in Settings, with the kind of film.

**A repeated picture is drawn once** (`stills.repeats`).
- Before a storyboard is drawn, one Haiku text call (about a cent)
  reads the directions and names the scenes whose picture an earlier
  one would serve unchanged.
- To count as a repeat, a scene needs the same subject, pose, place,
  framing, light and cast as the earlier one.
- A reuse is never of another reuse, and never the scene just before,
  so the picture doesn't look held.
- The repeated scenes get a copy, and the camera moves over it
  differently.
- On the drill film it found 8 of 78, the Earth cutaway among them.
  One false match, a dusk scene with the crew paired with an empty
  daytime one, led to light and crowd being added to the rule.
- Recorded as `stills_reused`.

**Faults looked for closely** (`stills.flaws`, after the usual check).
- The ten-at-a-time check sees small pictures and missed both faults.
- A second look, six pictures at a time at 1024 px, looks only for:
  extra or missing limbs, faces on things that aren't characters, and
  one character drawn twice.
- Haiku was tried first: nine false alarms in ten (a drill's round
  teeth read as eyes) and the arms missed. The usual model found the
  real faults (a copied engineer, a merged arm and, once told to look
  at every tool, the drill's face), with no false alarms. About 15
  cents a film.
- The main check also now names faces on objects.

**Another angle's title, free** (`production.packaging`,
`production.retitle`).
- Choosing another angle after the outline remakes the film; the
  button now says so.
- "Use title only · $0" takes another angle's title and thumbnail
  words and keeps the film's promise, script and pictures.
- For a made film, it rewrites the stored title and the thumbnail's
  words over the same picture.

**The Angle page's numbers, labelled.**
- The score shows as "6.6/10". It is (curiosity × 2 + familiarity +
  clarity + payoff) ÷ 5, minus 1 for each problem.
- The title length shows as "51 chars", red over 55, the most a phone
  shows.
- Problems are a red pill.
