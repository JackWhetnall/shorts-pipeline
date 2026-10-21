# 126 — A star's clothes said in every picture, and voices found by label

**Status:** active. Follows decision
[124](124-emily-time-trips.md) (Emily's time trips).

## What the owner said (21 Oct)

On the Emily storyboard:

> there are still a couple of continuity errors, mostly around clothing -
> and especially at the roman section where theyre in togas despite it
> being about the bikinis there. also there is a point where the
> matchbox image switches back to a previous scene. otherwise it looks
> good.

On voices:

> it would be nice to be able to filter the voice lab by gender and
> nationality; it is hard to browse at the moment. im not sure Katie is
> quite right; are there other ones (british woman) that could work
> better?

## What was wrong with the storyboard

Twenty-three of the 79 pictures had a continuity error.

- **Roman section.** Emily and the Roman women were in togas and long
  dresses in five pictures (scenes 65 and 67–71), at a stop that is
  about the mosaic's two-pieces. The two pictures that did show
  athletes had modern sports bras and gym shorts.
- **Matchbox close-up.** The close-up of Réard's matchbox (scene 41)
  was filed under the 1920s beach setting, so the Paris pool chapter
  cut back to the previous chapter's beach for one picture.
- **Reused pictures.** Two scenes reused an earlier picture: scene 15
  reused 7 and scene 26 reused 17. Each brought back the outfit of the
  earlier moment, a striped two-piece when she should have been soaked
  in wool, and the wool when she should have been in Kellerman's suit.
- **Outfit drift elsewhere.**
  - She wore a blouse and straw hat where she should have been in
    Victorian wool.
  - A sailor dress, a white top and a green suit appeared where she
    should have been in the 1920s tank suit.
  - A plain white bikini and a floral sundress appeared where she should
    have been in Réard's newsprint two-piece.
- **Off-model or strangers.** One stranger appeared in an empty frame,
  and one Emily was off-model.

**The cause.** Every picture is drawn on its own. Emily's sheet is her
face only (decision 124), so what she wears is whatever that one
direction says. Where a direction didn't say, the image model dressed
her, and everyone around her, in the era's usual clothes. That means
togas in Rome. The picture check didn't look for it.

## Decision

**For this film:**
- The two reused scenes have pictures of their own.
- The matchbox close-up is at the pool.
- Four directions name the clothes.
- All 23 pictures were redrawn as one job, each with a note saying what
  she and the others wear. That cost about $0.75, and the film's ceiling
  was raised once to $14.

**For later films:**
- **A time trip's directions name the clothes.** Every direction showing
  her says what she's wearing, in the same words all through a stop. So
  does every direction showing people whose clothes the story is about
  (`kinds.SCRIPT_DIRECTION["time_trip"]`).
- **The picture check looks for it.** When a recurring star is in the
  pictures being checked, the check also asks whether she wears what the
  shot says, and whether anyone wears clothes the shot rules out
  (`keyframes.STAR_CHECK`). Only when a star is present, so other
  channels' checks are unchanged.
- **Several pictures can be redrawn as one job.** The production page's
  redraw takes repeated `scene` and `note` pairs. A continuity pass is
  then one job and one check instead of one each.

**Voices:**
- Every voice in the Voice Lab carries ElevenLabs' gender, accent and
  age labels. The account's voices get them from their `labels`, and
  shortlisted library voices from the library's own fields.
- The page filters by gender, accent and category.
- `voice_lab.search_library` searches the Voice Library by the same
  labels, most used first. It's a free listing.
- Eight British women were shortlisted as alternatives to Katie for the
  narrator, chosen to sound distinct from Emily's soft, sweet voice:
  Verity, Evelyn, Zoe, Tamsin, Imogen, Amelia, Leona G and Cate. Each can
  be heard free from its preview, and needs adding in ElevenLabs before a
  test reading.
