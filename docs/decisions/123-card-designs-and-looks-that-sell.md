# 123 — Cards of each channel's own, cuter paper, and a cheeky channel that teases

**Status:** active. Revises the looks and the exposé kind of decision
[122](122-two-channels-two-kinds-of-film.md).

## What the owner said (20 Oct)

**The cards.** The two new channels' cards were "basically identical"
to everyone else's: "still things like 'Title, X vs Y', and the whole
point is that these are supposed to be entirely distinct channels".

**The looks.** The art "is lacking a bit". The owner believed, and asked
for research to test it, that "more cartoony, cute styles are better.
Rounded figures and more comical and casual styles than old school
picturebook style images."

**History's Bottom Drawer** had "completely missed the mark":
- It was meant to be "cheeky, naughty, and titillating", not "gaudy old
  school postcards and over the top expressions".
- The model was "an anime (though not japanese styled) that people
  watch simply because it has good looking characters that arent afraid
  to not wear a lot".
- The test: "would a bored 18-year-old boy want to click on this video
  based on the title and visuals alone - and then stay for the rest of
  the video because it is interesting". It should be "not meant to be
  actually explicit".
- "Never sexualised" had been "the exact opposite" of the brief.

## What the research found

**Cute and rounded wins in the "all day" niche.**
- The two biggest "What did ancient humans do all day?" videos have 14M
  and 450k views. Both use a rounded, simple, comical cartoon character
  in flat bright colour. Copies of that exact style are now appearing.
- In the lab, the "baby schema" (a round face, a big head, big eyes) is
  rated cuter and lights up the brain's reward centre, in adult and
  object faces as well as infants' (Glocker et al., 2009).
- The owner's belief holds: cute, rounded and comical, in a look of the
  channel's own.

**For the cheeky channel, glamorous stylised animation beats realistic
AI glamour.**
- Animated mythology built on good-looking stylised characters gets
  millions of views: Gods' School 9.1M, My Story Animated's "Queen of
  the Underworld" 7.1M, See U in History 4.4M, Shorts at 1.2–3.8M.
- Realistic AI "beautiful woman in a Roman dress" Shorts are everywhere,
  at 500 to 8,000 views.

**Where the lines are.**
- **YouTube** age-restricts, which costs most of a video's reach, when
  breasts or bottoms are the focal point, when a pose is "intended to
  sexually arouse", or for clothing unacceptable in public, such as
  lingerie. Animation counts the same as film.
- **The image model** sets its own line. A first look worded "dressed on
  the revealing side" had two of its three style frames blocked as
  sexual at output. Worded "stylish, fitted clothes of their time and
  place (period swimwear at the beach, draped togas, off-the-shoulder
  gowns, shirtless men at the baths)", every test picture drew. They
  showed swimwear, a winking Roman bather and shirtless men arguing.

## Decision

**Card designs** (`pipeline/documentary/card_designs.py`):
- `scenes.art.card_design` picks a set of shapes for every kind of card.
  It isn't a recolour.
- **Glass** stays the default and is byte-identical to before.
- **Time card** (Clocking In):
  - a punched clock card with a red rubber stamp;
  - a two-column ledger;
  - a typed order pinned with a brass split pin;
  - a duty rota and a ticked duty list;
  - a paper tag on the map.
- **Scandal sheet** (History's Bottom Drawer):
  - a starburst under a black headline ribbon;
  - two taped notes with a heart between them;
  - a clipping swiped with highlighter;
  - notes pinned on a string and a heart-bulleted list;
  - a lipstick ring on the map.
- Chapter titles follow the design: a red-stamped time on a paper tag,
  or a black ribbon with a pink edge.
- Film settings offer the design.

**Clocking In's look:**
- a flat stop-motion cartoon of cut paper, never clay or felt, with
  chunky rounded shapes in bright card;
- grown-ups with huge round heads, stubby limbs, dot eyes and big
  eyebrows, comically deadpan.

**History's Bottom Drawer's look:**
- a glossy Western 2D animated series, not Japanese anime: polished cel
  shading and warm rim light;
- glamorous, good-looking grown-ups, clearly in their twenties to
  forties, with smirks and winks, in stylish fitted period clothes;
- a new palette: hot pink, lipstick red and champagne gold on deep plum,
  with Impact headlines;
- its avoid list is now YouTube's actual triggers and nothing more:
  - nudity;
  - underwear worn on a body;
  - framing on breasts or bottoms;
  - sexual poses;
  - anyone who looks under twenty;
  - children;
  - beds.

**The exposé kind is rewritten** for "naughty, suggestive, never
explicit":
- The pitch carries the owner's eighteen-year-old test. Titles tease
  with innuendo but no vulgar words.
- The thumbnail is one of the film's good-looking characters, framed on
  face and figure.
- The narrator flirts and teases.
- Real people are told straight, and an invented good-looking cast of
  the time carries the glamour.
- Out: sex acts, sex work, fetishes, and anyone under eighteen.

## Fixed on the way

Pictures drawn at once that share their references make the same
combined reference sheet. Each wrote the same part file, and on Windows
the second rename failed (`keyframes.combine`). Each now writes its own
part file and keeps whichever sheet landed.
