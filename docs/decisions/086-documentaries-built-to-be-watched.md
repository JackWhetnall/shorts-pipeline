# 086 — Documentaries built to be watched

**Status:** active. Amends 074 (documentaries in stages), 076 (long-form
settings) and 079 (narration pauses).

## What happened

On 11 October the owner asked for research into what makes YouTube
videos succeed, a critique of the first History Unmystified film (Lincoln
and the Gettysburg Address) against it, and the code changes that would
make films "more likely to be successful", with low costs. The review is
the "Hit Video Playbook" artifact
(https://claude.ai/artifact/3sDCyDjUR8WyjobZyn6Vkg). Then:

> "history unmystified is just a name ... i wouldnt focus too hard on the
> factuals; viewer numbers and retention is more important. yes make all
> the necessary code changes. also then create and configure a new
> channel, and schedule a video for it to prove the concept"

The Lincoln film's problems were all ones a viewer meets before or early
in the video:
- **Title:** 62 characters, opening on a label.
- **Thumbnail:** the opening still with all nine words of the title over
  it, and Lincoln under 3% of the frame.
- **Opening:** a date and the weather.
- **Background:** 43% of the film before the speech its title promised.
- **Script:** long written sentences, and "small" nine times.
- **Pictures:** one kind, each held 14.8 seconds.
- **Pace:** narration at 118 words a minute.

Writing was $0.22 of the film's $6; pictures and voice were the rest. So
the cheap lever was the plan and the script, and the visible one was
pace.

## Decisions

Most of these are documentary-only and leave Minute Pastor and Pub Quiz
Buzz untouched. The exceptions are covered in the last two sections.

**The angle comes first** (`pipeline/documentary/pitch.py`, a new first
production stage, "Angle"):
- One call, about two cents, gives six angles. Each has a title, a
  thumbnail idea (a subject, and four words at most), a promise, the
  first line and the question only the ending answers.
- Each is scored, curiosity counting double. A title over 55 characters,
  or one opening on a label, loses a point per problem.
- The best is chosen unless the owner picks another. Picking another
  makes later stages stale.
- Films started before this carry on: their outline stands in for the
  angle (it's marked approved, "legacy").

**The outline keeps the promise and is built for retention.**
- It now has a `promise`, `open_loops` and a `turn` per chapter.
- The cold open lasts a minute at most and raises the loops.
- Background comes only where needed, at most a fifth of the film and
  never before minute two.
- The stakes rise again between minutes three and six.
- The payoff comes in the last fifth.
- Chapter titles are things people search for.
- A motif appears in at most one scene in five.
- `outline.problems` checks the cold open, turns and loops; the outline
  is written once more if it breaks them.

**Scenes have a medium:**
- **Drawn**, as before.
- **A museum painting** (`media.painting`, via `pipeline.artwork`, set
  whole into the frame over a blurred copy, credited). This needs the
  channel's paintings setting on.
- **An animated card** (`cards.py`): number, versus, quote, timeline,
  list, or a map that zooms to the place with its country picked out
  (Natural Earth, already cached). Cards are drawn in the channel's
  theme and given the stills' grade. They cost nothing.

A painting that can't be found, or a card that won't build, is drawn
instead. The storyboard records what each scene really is (`shown`).

**The script is written for the ear:**
- About 150 words a minute (`WORDS_PER_SECOND` 2.4 → 2.5).
- Sentences of about 15 words.
- Something specific in every scene, and loops kept open until answered.
- The first scene speaks the angle's first line.
- The first sentence of the description holds the search words.

**An editor's pass** (`editor.py`, about five cents):
- Checks with no model: average sentence length, the shorts' AI-phrase
  list, worn-out words, the opening against the angle, two cards in a
  row.
- One critic call scores chapters for momentum, specificity and voice.
- Up to two of the worst chapters are rewritten with those notes. The
  notes are kept as `edits` and shown as a pill.

**Several shots from each still** (`shots.py`):
- A Haiku vision call names up to two framings per still (where, and how
  close). It runs for eight stills at a time, and the result is cached by
  file and modification time.
- A scene is cut about every 5.5 seconds: the whole picture, then each
  framing, each with its own move.
- The screen changes roughly every five seconds without drawing more
  pictures. If the call fails, the scene holds one shot and the report
  says so.

**Pace:** sentence gaps 0.45 → 0.32 s, chapter gap 1.6 → 1.1 s.

**A designed thumbnail** (`thumbs.py`):
- One picture is drawn for the purpose from the angle's thumbnail idea,
  in the film's look and with the cast's sheets, about four cents.
- The subject goes on the left, with up to four words big on a dark
  panel.
- Test & Compare variants change one setting at a time through the
  existing recipe (`thumbnail_variants.render_long` hands documentaries
  to `thumbs.render_variant`).

**A scorecard** (`core/scorecard.py`): the hit recipe measured on the
film. These show as pills on the Video stage:
- title length
- thumbnail words
- whether it opens on its promise
- pictures in the first 30 seconds
- the longest hold
- pictures a minute
- words a minute
- kinds of picture
- length

**Viewers by scene and lessons** (`core/retention.py`, `core/lessons.py`):
- `core.audience` fetches each documentary's retention curve
  (`audienceWatchRatio` by `elapsedVideoTimeRatio`) with its other
  figures.
- The production sidecar now records each scene's start and end, so the
  biggest drops are named by scene on the production page.
- A week after a film goes out, one Haiku call turns its drops and its
  30-second figure into at most two lessons. They are kept in
  `channels/<key>/lessons.json` (moved by a rename with the channel's
  folder) and read by the angle, outline and script writers.
- The list is capped at eight, and the owner can edit it on Productions.

**Teasers** carry the film's promise and open question.

**A channel can make its own films** (`core/auto_films.py`,
`documentary.auto_make`, off by default):
- The scheduler starts the next stage at batch prices and approves each
  ready stage up to the storyboard, marked "autopilot" in the history.
- It works on one film at a time, never more than `documentary.ahead`
  made and waiting, and never a video the month's voice can't cover.
- A failed stage is retried once, then left for the owner.
- The finished video always waits for the owner's look. Once approved,
  its teasers are written and made.
- This is not `core.autopilot`, which decides whether a finished short
  is published unseen.

**Settings:** the long-form settings page gains paintings, "Makes its
own films" and "Films waiting for a look". The scene-length hint became a
tooltip.

## Not done, and why

- **No fact-check stage.** The owner put retention before accuracy. The
  writers still get the existing "nothing invented as fact" line.
- **No cast members tied to dates** (Lincoln's 1858 beard). That is
  accuracy too, and the cost of a variant is a sheet per era.
- **Topic demand from YouTube search** wasn't built. It needs a
  connected channel and quota, and the lessons loop is the better signal
  once films are out.

## The proof

A new channel, **One Day In History** (`one_day_in_history`):
- **Format:** second person and present tense, one ordinary day in a
  real place and year, hour by hour.
- **Look:** old-master oils in Dutch genre-scene light, with real period
  paintings mixed in.
- **Voice:** a different narrator from History Unmystified's.
- **Settings:** 14-minute films, two teasers each, Saturday-evening long
  slots, thumbnail tests on.

Its first film, *A Day in Plague London, 1665*, was made through every
stage.

Making it found five things, now fixed:
- **The angle's top score named nothing.** The best-scored angle, *The
  Morning Your Master Doesn't Come Down to the Ovens*, never said
  "plague", "London" or "1665". A title (or its thumbnail words) that
  names none of the plan entry's subject words now loses a point
  (`pitch.subject_words`). The film became *The Baker Who Wasn't Allowed
  to Flee the Plague*, with "EVERYONE ELSE RAN" on the thumbnail.
- **A chapter titled "Cold Open: ..."** would have shown in YouTube's
  chapter list. `outline.chapter_title` strips "cold open", "chapter N"
  and dashes.
- **The Met retired its search API on 1 October 2026.** It now answers
  410, so every painting search had come back empty, for shorts too. It
  moved to the paginated v1.1.
- **The painting picker took mood over period.** It picked Munch (1893)
  and an American portrait (1721) for 1665. It's now told the film's
  time and place and shown each work's date, and refuses another century.
  It then chose a drawn street scene of about 1600 and declined the
  other scene, which was drawn instead.
- **One still held 12.7 seconds** in the Lincoln re-cut, because the
  vision model named no framing. A scene too long to hold now gets the
  middle of the picture, a little closer.
- **The narrator was faster than planned.** At speed 1.0 he ran at 174
  words a minute (2.9 a second, pauses included), so a film planned at
  14 minutes came out at 10.9. The script now plans at each channel's
  measured rate (`script.words_per_second`, from its latest films'
  reports, scaled to its voice's speed now), and this channel's voice is
  at 0.95.

The renderer was first tried on the Lincoln film without new voice (its
lines were cached). It cut 121 shots from 50 stills, 9.9 pictures a
minute against about 4. The scorecard named what's left: 119 words a
minute (its voice is at 0.9) and one kind of picture. With the angle, outline, script and storyboard approved the way
`auto_films` approves them, it waits in review. "Makes its own films" is
then on, so the next film starts once this one has had its look
(`ahead` 1).
