# 124 — History's Bottom Drawer follows Emily on time trips

**Status:** active. Replaces the exposé format of decisions
[122](122-two-channels-two-kinds-of-film.md) and
[123](123-card-designs-and-looks-that-sell.md) on this channel; the
exposé kind stays in the app.

## What the owner said (20 Oct)

The second storyboard missed again:
- **The look was wrong:** "still random retro art rather than just a
  normal cartoon".
- **Fine pictures were removed:** "the removal of perfectly fine images
  because an image of romans in literal bikinis is, according to you,
  'too much'"; "stop being overly cautious when this is the exact point
  of the channel".
- **The film failed the test:** it opened on "a man talking about a
  matchbox and showing pictures of bikinis on mannequins", which "does
  not pass the 'would a bored 18-year-old boy want to click on this'
  test, not by a long shot".
- **Money was spent without asking:** "if you think you need to change
  what I am asking, tell me first before spending my money".

**The new idea:**
- The channel has a conventionally attractive but shy female main
  character, who explores a different interesting yet titillating
  concept in each video.
- She is the focus. She "discovers" the facts as she goes, time-travel
  style: a question, a journey through the eras, trying things as she
  goes, and home again with recap revelations.

**The owner chose style D** from four samples (4.5 cents): a modern
YouTube story-animation look of clean flat vector shapes, flat colour
and big expressive faces. They named her Emily, after the voice "Emily –
Soft & Sweet". They added:
- **More than clothes:** "it might be eg saunas and onsens and things
  around the world (with parts tastefully obscured by water or steam)".
  The format mustn't be constrained to clothes.
- **Several voices:** her, a narrator, and other characters "only when
  there is a real character of value (eg Reard would fit) and not just a
  random throwaway line".
- **No fixed beats:** no forced peak embarrassment or "did we miss
  something?" in every film. "It should just be a journey and discovery
  that she goes through. Ending back at home with recap revelations is
  good."

## Decision

**A new kind of film, the time trip** (`kinds.py`):
- **Opening:** the star, today, in a moment that raises a cheeky question.
  She asks it aloud, and the bottom drawer of an old chest of drawers
  pulls her into the past. The drawer is the channel's name.
- **The stops:** three to six, one chapter each. The narrator sets the
  time and place, she sees and joins in, one true fact surprises her,
  and she's pulled on.
- **Home:** back in the present, changed, summing up in her own words.
- **No fixed beats:** no twist or embarrassment peak is required.
- **The rules:** titillating, never explicit. Where people really bathed
  or swam with little or nothing on, it's shown that way and hidden by
  steam, water, towels or framing. Everyone is an adult.
- **Checks:** a story underneath for its pictures, which stay with her in
  each place, but fact-checked like a film that teaches
  (`kinds.fact_checked`).
- **Dialogue:** its own rules (`kinds.DIALOGUE`). She talks all the way
  through, about a third of the scenes. Real people speak only where
  they matter, and the narrator takes the rest.

**A recurring star:**
- The channel's animation cast is put first in every outline's cast in
  the channel's exact words, and in every setting
  (`outline.with_recurring`). Emily is drawn from one sheet in every
  film.
- `documentary.voices` fixes a recurring character's voice. Emily is
  always Emily – Soft & Sweet. Everyone else still gets a voice of their
  own for each film, never the narrator's (Katie).

**The channel:**
- style D;
- a brief built around Emily;
- an avoid list cut to visible nudity not hidden by steam, water, a towel
  or clothing, anyone who looks under twenty, children, writing and gore;
- 21 planned films in four series: the beach, glamming up, bathing (Roman
  thermae, Finnish sauna, Japanese onsen, the Ottoman women's bath Lady
  Mary Wortley Montagu wrote about in 1717, the Russian banya, spa
  towns), and falling for history (dating, kissing, scandalous dances,
  Casanova, Cleopatra, Venice's masks, love potions).

**Voices in the app:**
- The Voice Lab and Settings listed only premade voices, so neither the
  Voice Library voices chosen for the new channels nor the account's own
  voices could be heard there.
- They now list the account's voices and a shortlist of library voices
  (`config/voice_library.json`) with their free ElevenLabs previews.
- A shortlisted voice can't be test-voiced until it's added to the
  account. A channel draft offers only voices that can speak now.

**Working rule, from the owner:** no picture is removed or toned down
unless the owner asks or the image model refuses it. A change to what
they asked for is raised before any money is spent.
