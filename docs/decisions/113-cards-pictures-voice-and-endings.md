# 113 — Cards that earn their place, pictures that stay with their line, softer not whispered, endings that close

**Status:** active.

## What the owner saw (18 October)

- **Cards that didn't belong:**
  - "Times it let go: 0", "What decided it: 1 hemisphere", "Altitude at
    tasting: 0 m";
  - "by the mile" on a number card;
  - versus cards comparing two descriptions ("built and worked smoothly"
    against the same; "red octagon" against "no convention");
  - "300 per square inch" twice in the Velcro film, under a title saying
    "Ten Thousand Hooks Per Inch";
  - the year 1913 shown as "1,913".
- **A picture that didn't fit its line.** In the Velcro film, a run of
  spacecraft-cabin scenes cut to a climbing harness in a gear shed, then
  back to the cabin.
- **A plainly wrong layout.** In the airline food film, plane seats
  faced the windows.
- **Whispered lines** came across as creepy.
- **Endings that didn't close the film:** "Look at your shoe. A weed is
  still holding on." and "Order the tomato juice."

## Why

- **The script writer's only rule for cards** was that they should be
  "rare". Nothing reviewed cards afterwards except the fact check, which
  never saw the title.
- **The count-up animation** formatted every number with thousands
  separators.
- **The picture editor's balance rule** allowed no more than six pictures
  in a row in one setting, and fixed a long run by moving pictures to
  one-off "pictures of the idea". That broke a cabin sequence with an
  unrelated cutaway.
- **The flaw check** looked for anatomy and faces, but not for things
  arranged wrongly.
- **`[whispers]`** was one of the script's delivery cues.
- **The last-line rule (decision 092)** asked for "a concrete image",
  never a "so next time". That produced riddles.

## Decision

**Cards:**
- **Written better.** The script writer is told what earns a card:
  - a number that is striking on its own, with its unit;
  - or a versus of two parallel values of the same thing, in the same
    unit, where the difference is the point.

  It's never a 0 or a 1, never a non-number, never two descriptions,
  never a figure twice, and years have no comma.
- **Reviewed together** (`editor.review_cards`). After the repeat pass
  and before the fact check, one call looks at all of a film's cards,
  each with its lines either side and with the title and thumbnail words.
  Each failing card is fixed when a good card is there to be had, or
  shown as its picture otherwise. A contradiction with the title is
  noted, never "fixed" by changing the card: the narration is the
  authority. Code then keeps only the first card of any figure shown
  twice.
- **The title too.** The fact check now reads the title and thumbnail
  words, and can correct either. The script stage writes the correction
  into the film's packaging and its history.
- **Numbers count up as written:** "1913" stays "1913", and "12,262"
  keeps its comma. The film card's own page strips the separator after
  each frame the shared count-up script draws, by wrapping `__start` and
  `__seek`. The shared script itself is untouched: a first try that
  changed it altered the frozen channels' boards byte for byte, and the
  frozen suite caught it.

**Pictures:**
- **Rule 4 for the picture editor:** a picture shows what its line is
  about. While the narration stays in a place, the pictures stay there.
  A long run there is broken by other views of the place, never by
  leaving it. A cutaway belongs only where the narration turns to an idea
  the place can't show.
- **Longer runs allowed:** the run limit rose to nine (explainer) and ten
  (story).
- **The flaw check** looks for things plainly wrong in real life too:
  plane seats facing the windows, numbers out of order on a clock.

**Voice:** `[whispers]` is no longer offered. Any whisper cue is voiced
as `[softly]` (`tts.soften`).

**Endings:**
- **The new rule:** the last line closes the film by carrying its
  answer, plainly enough to make sense on its own. It may tie the answer
  to the viewer's life ("Next time you see a Velcro shoe…").
- **How it's checked:** the check first writes down the film's answer to
  its title, then keeps a last line only if that line says it. It names
  only causes the narration names.
- **The overseer's checklist** says the same.

## Tried on four films before shipping

**The first version of the card review was wrong in three ways:**
- it changed the Velcro card to "10,000" to match the wrong title;
- it removed 5 of the clock film's 6 cards, including the north/south
  comparison the film turns on;
- its ending for the airline food film blamed "gravity".

These are now covered by rules:
- the narration is the authority;
- a clean either-way comparison is allowed;
- fixing beats removing;
- the same unit on both sides of a versus;
- only the narration's causes in an ending.

**On the second pass:**
- Velcro kept 300 and dropped the 0, "by the mile" and the duplicate.
- The clock film kept its north/south card, and its ending became
  "Clocks turn clockwise because that's the way shadows fell on sundials
  north of the equator."
- The stop-sign ending became "Octagon so you'd know it from any angle,
  red because red finally stopped fading: that's the sign nobody
  invented, and everybody obeys."
