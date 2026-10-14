# 098 — Every word on screen checked

**Status:** active.

## What happened

The first overseen film was t0003, "Why We Know Mars Better Than Our Own
Ocean Floor". Its lines were corrected from Mars being "completely
mapped" to "near-complete". The overseer then reported that several
things still disagreed with the corrected lines:
- the captions on scenes 3 ("Mars: fully mapped since 2006"), 11 and 40;
- the heading on 59, which was found in the owner's follow-up;
- the hook.

The overseer's tool couldn't edit any of them.

## Why

- **The fact check could only fix part of a card.** It could correct a
  card's value or items. Headings and captions reached it as one run of
  text, and nothing in its answer could change them.
- **A wrong card on a correct line was dropped.** A fix that rewrote no
  line was thrown away, even when the card under it was wrong.
- **The overseer had no edit for them.** It couldn't change a heading, a
  caption or the thumbnail words.
- **The hook looked like film text.** The overseer's script sheet listed
  the angle's hook next to the title. The hook is only a planning note
  for the outline and never appears in the film, but it read as if it
  did.

## Decision

- **The fact check names each part of a card** (heading, value, caption,
  items) and can correct each one. It can also correct a card whose line
  is fine. Each correction changes only the part it names.
- **The overseer can edit everything shown on screen:**
  - `--card-heading` and `--card-caption`;
  - `--thumb-words`, the thumbnail words of the angle the film goes out
    with.
- **The script sheet shows the thumbnail words.** It labels the hook and
  promise as "planning notes, never shown or spoken". The checklist in
  docs/overseer.md says the same.
- **t0003 was fixed by hand before its storyboard was drawn:**
  - captions on scenes 3, 11 and 40;
  - heading on scene 59;
  - scene 3's heading now says "mapped", not "seen".
