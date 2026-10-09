# 083 — Thumbnail tests: rotated for shorts, Studio for long videos, a recipe that learns

**Status:** active, off per channel until switched on (Settings,
Publishing, "Test thumbnails"). Builds on 082.

## What happened

The owner asked for thumbnails to be tested, with Insights showing which
did better. They also wanted the losers adjusted "to see what it is about
A that works; then continue comparisons in future". Given YouTube's
limits (082), they chose both methods: shorts rotated by the app, long
videos through Studio's Test & Compare.

## Decisions

**A thumbnail is drawn from a recipe** (`pipeline/thumbnail_variants.py`)
of four settings:
- text size;
- accent: the stamp's colour on a short, the mark and badge on a long
  quiz;
- background: the look's own, dark or an accent;
- tilt.

The default recipe adds no CSS, so variant A of a short is its opening
screen as the video shows it. Variants are rendered as pages, so B and C
can each differ from A in exactly one setting.

**Each round tests three:** A, the channel's recipe as it is, and B and
C, one change each. The result is a coordinate search
(`core/thumbnail_tests.py`):
- **B or C wins:** its change is kept, and the next round pushes the
  same setting another step, beside a fresh change elsewhere.
- **A wins:** the changes tried were worse. Their steps halve (to a
  quarter at least), a losing option is set aside, and other settings
  come up.

**Shorts are rotated by the app.**
- A short joins the channel's open round when it goes out, up to 6
  shorts a round.
- It keeps A for two days, while most of its views are subscribers'.
  Then it shows A, B and C for three days each, twice.
- Each short starts the cycle at a different variant, so a video's age
  doesn't favour one.
- Click-through comes from the Reporting API's daily reach report
  (`core/reach.py`, about two days behind). Days a thumbnail changed on
  are left out.
- A round is judged once all its shorts have finished and their figures
  are in.
- It needs 300 impressions per variant, and the winner 8% ahead. Short
  of that, it's "too few impressions to tell" or "no clear winner;
  keeping the recipe".

**Long quizzes use Studio's test.** A long video's page makes the three
(free) to download. The owner adds them to Test & Compare in YouTube
Studio and ticks the winner it names, which feeds the same search.
Studio judges by share of watch time, all three at once, which is
better than any rotation, but it can't be driven by the app.

**Insights** shows each testing channel's best recipe so far, and its
last eight rounds: what each variant changed, its click-through and
impressions, and the winner or the verdict.

**Running it:** a scheduler duty, for channels with tests switched on
and YouTube connected:
- reach reports fetched a few times a day;
- each short in rotation put on the variant it's due;
- finished rounds judged.

If the Reporting API isn't switched on in Google Cloud, Today says so
with a link.

## Not covered

- **Documentaries.** Their thumbnail is a still with the title. The same
  recipe could apply; not done yet.
- **Whether the API applies a thumbnail to a Short** is still to be seen
  (082). If it doesn't, rotation for shorts does nothing visible and
  should be switched off; long videos are unaffected.
