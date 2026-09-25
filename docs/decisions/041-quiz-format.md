# 041 — A quiz format, fact-checked; settings in one place; plans that top themselves up

**Status:** active.

## What happened

The owner asked for a pub-quiz channel to test how well a new channel sets
itself up. Each video would be ten questions on one category at one
difficulty (easy up to "impossible"), with:

- each question's whole text on screen while it's read;
- the numbers 1 to 10 down the left, filling with answers as they're
  revealed;
- about four seconds of clock, then the answer (repeated when it's short,
  sometimes in context);
- no footage and no pictures for answers;
- a chilled, friendly host.

Nothing in the pipeline could make this. Every video was a script read
over footage and graphics, and the draft had no way to describe any
other shape.

## What was decided

**A channel has a format** (`format`: "narrated" or "quiz", with a `quiz`
section for questions, countdown, answer pause and the difficulty
ladder).

**A quiz is a pipeline branch, not a separate pipeline**
(`pipeline/quiz.py`):

- the script stage writes a round;
- voiceover, checks, publishing and the originality check work as
  before;
- the visuals stage films one board for the whole video instead of
  directing segments;
- assembly draws no captions (a new `captions_enabled` style switch).

The countdown is silence after each question: `Segment.pause_after`, a
general per-segment override of the channel's pacing.

**The board is one seekable template page** timed from the real
voiceover:

- the kicker and difficulty chip;
- the question card: intro, each question, then "How many did you get?";
- the numbered list, with the current row outlined;
- a draining ring with a big digit per second.

Its effects (a woody tick each second, a chime at the reveal) are exempt
from the sparse-effects limits, because the clock is the point.

**A wrong answer is the one mistake a quiz can't survive**, so every round
is fact-checked by a second call before it is voiced:

- questions it doesn't pass are rewritten once, and the rewrite is told
  the round's other answers so it can't give one away;
- anything still failing is recorded on the script and holds the video
  at the publish gate.

The first version of the check agreed with every answer, including "J is
the only letter in no element symbol", which is false (Q is absent too,
since Uuq became flerovium). A checker that reads the proposed answer
first anchors on it. The check now has to:

- write out its working;
- list *every* correct answer (going through the whole set for any
  "only/first/largest" question);
- only then give a verdict, at high effort.

Its schema's field order enforces this, and a test pins it. Made to work
this way, it caught the error and also flagged "the Nile" as disputed.
It costs about 3 cents a round.

**Rounds are written to fit a Short.** The first round was 370 words.
With ten five-second silences that made a 3:37 video, and YouTube treats
only videos up to 3:00 as Shorts. The writer now gets a word budget: the
target length minus the fixed clock time, at 2.5 words a second, which
is about 240 words for 150 seconds. Any video over 3:00 is held at the
publish gate, for every format. Shorter rounds also save voice: about
1,150 characters, so the 30,000-character Starter plan covers about 26
quizzes a month.

**The topic plan is categories × difficulties, written by rule.** The
draft proposes categories and a difficulty ladder. Accepting writes
every category at every difficulty (15 × 5 = 75 quizzes) for free, with
no outline or subtopic call. Categories take turns (round-robin, random
order). When fewer than 30 are left, another round of each is added.

**The originality check compares a quiz's questions, not its patter.**
"Question four" is in every round, and would have made each quiz look
like a copy of the last. The history records each quiz's questions, and
the writer is told what this category has already asked.

## Found while setting it up

- The draft chose a narrator speed of 1.02, and the review page's field
  stepped in 0.05, so "Create this channel" silently did nothing. The
  browser flags that only with a small bubble by the field. Speed and
  countdown fields now step finely. A test checks that every drafted
  number is one its field accepts.
- A channel's topic plan only ever had its first topic written, so a
  hands-off channel stopped dead when that topic ran out. The scheduler
  now tops up running channels' plans when they run low (the next topic
  for a narrated channel, one call; another round for a quiz, free).
- The publishing plan, graphics and music were edited on the dashboard
  with their own Save buttons, beside the settings page. They are now
  settings sections, and the dashboard summarises them.
- The settings sidebar never stuck, because `--sticky-top` was defined
  as itself.
- A browser kept the old stylesheet after an update, so static files now
  carry a version.
- Music suggestions for the quiz were cinematic and moody, because the
  ranking prefers what sits quietly under narration. This is still open.

## Tried and rejected

- **A separate quiz pipeline.** It would duplicate voice, checks, the
  gate, publishing and history, all of which apply unchanged.
- **Showing answers as pictures.** The owner asked for none.
- **Model-written subtopics for a quiz.** Category × difficulty is
  exactly the plan, and a rule writes it for nothing.
