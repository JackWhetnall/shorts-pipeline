# 061 — Questions imported from the Open Trivia Database and pub-quiz websites

**Status:** active. Widens the question bank of [050](050-question-bank.md),
which chose to write every question ourselves.

## What happened

The bank held 1,527 questions, all written by the model, and was badly
lopsided by difficulty. Every named category had under ten unused
questions at Easy and Medium, and dozens at the hard levels: asked for
easy questions, the writer wrote ones the rater then judged hard. Rounds
kept finding the bank short.

The owner wanted thousands of questions: "the open trivia database, plus
thousands more from quiz websites, and then any gaps have questions
generated (and difficulty-checked) as well". Scraping websites was raised
with them as a risk: most such sites' terms forbid it, and copied
question sets are what YouTube's reused-content rules target. They chose
all three sources anyway. The importer is built to keep that risk as small
as it can be.

## What was decided

**Two steps** (`pipeline/facts/intake.py`), so nothing is spent until
wanted:
1. **Gather** raw questions into an `intake` table:
   - **Open Trivia DB** (`sources/opentdb.py`): its ~5,300 verified
     questions, multiple choice only, leaving out video games, anime,
     comics, board games, gadgets and computers. Its API allows one call
     every 5 seconds, so it takes about 10 minutes, and it's free. When
     fewer than 50 are left in a category the API says "token spent", not
     "not enough", so the rest are taken at smaller sizes.
   - **Websites** (`sources/web.py`): the pages in
     `config/quiz_sources.txt`. Rules for reading them:
     - **robots.txt is obeyed**, including any crawl delay; a site that
       says no is skipped (Reddit does);
     - at most one page every 4 seconds;
     - only the same site, and only pages that look like quiz pages, up
       to 60 per site.

     Haiku reads each page's questions and answers out (about 3 cents
     a page, long pages being read in parts). The page's own wording is never kept in the bank.
2. **Process** them, 25 at a time, within a budget:
   - drop what the bank already has;
   - **rewrite each in our own words** as a question read aloud (Haiku),
     dropping ones that need options, are true/false, are video-game or
     American trivia, or whose answer may have changed;
   - the usual local checks (malformed, gives its answer away,
     repeats);
   - fact-check them (Sonnet, medium effort: these were checked by
     people once already, and the rewrite keeps the fact);
   - rate them with the bank's own rater;
   - store them with their source and origin;
   - file them under every category they fit (`scope.file_new`).

   About $2.50 per 1,000 raw questions. Progress is kept per item, so a
   stopped run carries on.

**The scheduler processes up to $3 a day**, before it writes any new
questions itself. The Facts page shows each source's counts and has
the buttons: read Open Trivia DB, read the websites, and process up to
a chosen amount now.

**Credit:** Open Trivia DB is CC BY-SA 4.0. Any round using one of its
questions adds a credit line to the video's description.

**Easy questions written ourselves** now come with the rater's own
reference points ("four in five British adults would get this right"),
because "level 2" alone produced questions rated 4 to 6.

## What was rejected

- **Keeping a site's wording.** Rewriting keeps the fact and not the
  site's expression of it. This matters for copyright, and for YouTube's
  rules on unoriginal content.
- **Ignoring robots.txt** to read Reddit's thread: Reddit disallows it.
- **The Haiku-sorts, Sonnet-checks filing for imports**, which would cost
  four times as much at this scale (see 060).

## Later the same day: one call per batch

A trial of the steps above (100 questions, $0.35) showed two problems:
- **Haiku's rewrites kept questions that only work with options.** "Which
  soft drink was introduced before the others?" got past the fact check.
- **The separate fact check was the biggest cost.**

Processing is now **one Sonnet call per 25 questions**. It rewrites,
judges whether the answer is certainly right and the only one, rates the
difficulty against the rater's own reference points, and files the
question into the rounds it fits. That's about $1.20 per 1,000 raw
questions instead of $3.50, with better wording. Judging its own rewrite
is acceptable here because nothing is being written to hit a level: the
bias that made an independent rater necessary for written batches doesn't
arise.

New local checks:
- a rewrite that still mentions "these", "the following" or "the others"
  is dropped;
- a website's question reworded less than 80% from the original is
  dropped. Open Trivia DB's licence allows close adaptation.

Batches are now claimed before they're worked on. The app's hourly run
and a run by hand once processed the same rows side by side, paying
twice. The first trial's questions were taken out again and put back
through the new pipeline; of the old pipeline's output, one question
leaned on its options and was rejected.
