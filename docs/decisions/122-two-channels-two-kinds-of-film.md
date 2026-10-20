# 122 — Two new channels, and a kind of film for each

**Status:** active. Builds on the kinds of film of decision
[089](089-explainers-gentler-depth-fitting-sound.md) and the topic rules of
[118](118-films-that-work-by-ear.md).

## What the owner asked for

On 20 Oct the owner asked for two new channels as proofs of concept:
- set up now, before the Partner Programme thresholds double;
- "completely distinct from existing channels, including art style,
  voice, info cards, script style and cadence";
- researched against what already works on YouTube, in a niche that
  isn't oversaturated;
- a storyboard for each one's first film, with no ElevenLabs voice and
  no fal.

The two ideas:
1. **"What did they do all day":** an explainer about a time and role
   in history, not a "day in the life" story like One Day In History.
   Stop-motion paper cutouts.
2. **The cheeky bits of history:** the invention of the bikini, how a
   princess was bathed and dressed for her wedding, what people did
   before clothes. Titles to make a bored eighteen-year-old click, but
   never far enough to break YouTube's or the image model's rules.

## What the research found (20 Oct)

**"What did X actually do all day" is the most-copied AI history title
on YouTube.**
- Searches for pirates, Roman soldiers, samurai and medieval monks each
  return a dozen uploads from the last two weeks, mostly with tens or
  hundreds of views.
- Narrower angles are copied within days. Ten Vindolanda-letter videos
  went up in a month, and ten Egyptian "sick note" videos.
- The demand is real, though. "What Did Ancient Humans Actually Do All
  Day?" has 14M views in a month, and several cavemen versions have
  1.5–2.7M.
- Lighthouse keepers have proven interest (3.1M and 7.7M views on
  lighthouse videos) and almost no "all day" explainers.

So the topic alone can't set the channel apart. The look, the voice, a
fixed structure of its own, and real evidence have to.

**The cheeky niche is far quieter.**
- The bikini's history tops out at 103k views. Its nuclear-test name has
  a handful of uploads under 200 views.
- Getting-dressed history is wanted: "Getting Dressed as a Medieval
  Queen" has 752k views, and dress-history videos have 2.4M and 7M.
- Wedding-night videos have demand, but YouTube's advertiser guidelines
  limit ads on "educational discussion of intimate experiences" and on
  sexualised titles and thumbnails. "Comedic intent does not make highly
  sexualized content suitable." Comedic innuendo without vulgar terms,
  and bikinis at a pool, keep full ads.
- So the channel is bodies, bathing, toilets, clothes, scandal and
  courtship, never sex.

**Names.**
- **Clocking In** is unused for history. The owner's "what did they do
  all day" stays as the question each film answers.
- "Cheeky History" is taken. **History's Bottom Drawer** is clear. A
  bride kept her trousseau in the bottom drawer; it's where the bits
  people hide away live.

## Decision

**Two more kinds of film** (`pipeline/documentary/kinds.py`), so neither
channel shares Why, Though?'s mystery-and-payoff shape:

- **`working_day`:** a job explained across one working day.
  - A cold open, then the job advert: who did the job, why, and the pay.
  - Then the day in order, each chapter titled like a time sheet
    ("5 a.m.: Muster"). Each covers the task, how it was done, the
    number, how we know, and one human detail.
  - "The part nobody tells you" in the middle, then pay day.
  - Third person, present tense, never casting the viewer as the worker
    (which is One Day In History's voice). A deadpan time-and-motion
    narrator.
- **`expose`:** gossip with receipts.
  - The polite version, then the bottom-drawer truth.
  - Behind the closed door step by step, with the receipts, then a twist
    that turns the joke around.
  - It ends on where it's hiding in the viewer's drawer today.
  - Cheeky, never crude. The kind's own rules say exactly what is out:
    - sex acts, wedding nights, sex work, fetishes, explicit content;
    - nudity as the subject;
    - anyone under eighteen in anything about bodies, undressing or
      romance;
    - sexualised titles.
  - Its pictures keep everyone decently dressed for where they are.

Both are explainers underneath (`kinds.family`). They're fact-checked,
held to an explainer's opening and given its picture rules. Settings
offer all four kinds.

**Clocking In** (`clocking_in`):
- **Voice:** Tom, "Light Northern British", from the ElevenLabs Voice
  Library: a dry Yorkshire/Lancashire voice billed as "along the lines of
  Alan Bennett". Speed 0.95.
- **Film:** 10 minutes, 8-second scenes, chapter titles on.
- **Look:** cut paper jointed with brass split pins, on stop-motion twos
  with the stepped camera of decision 121.
- **Cards:** a manila time-card with ruled lines, a time-clock red
  accent, Consolas and Bahnschrift. Tag labels.
- **First film:** the Victorian lighthouse keeper.

**History's Bottom Drawer** (`historys_bottom_drawer`):
- **Voice:** Katie, "Relatable & Humorous", a witty British woman,
  chosen over a sultry voice so the cheek stays in the words. Speed 1.05.
- **Film:** 8 minutes, 6-second scenes.
- **Look:** a vintage British seaside comic postcard, with bold ink, flat
  retro colour, halftone dots, and rosy, decently dressed grown-ups.
- **Avoid list:** nudity, underwear worn on a body, cleavage, children
  and beds.
- **Cards:** postcard cream with halftone dots, pillar-box red and
  seaside blue, Arial Black and Georgia.
- **First film:** the bikini, named after a nuclear test and sold in a
  matchbox, and worn by Roman women 1,600 years earlier.

**Both channels:**
- Publishing, the autopilot and the overseer are off.
- Neither voice is in the account yet (TASKS.md), and nothing is voiced.
- Each has a hand-written opening plan of 14 to 17 films in 3 or 4
  series, kept clear of the flooded titles.

## Not done

- No voice, no video, no teasers. The storyboards stop at the stills.
- The two voices haven't been heard in a film. Their library previews
  are the test.
