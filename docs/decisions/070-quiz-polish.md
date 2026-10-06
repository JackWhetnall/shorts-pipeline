# 070 — Quiz polish: the countdown's audio, picture rounds, the host's lines

**Status:** active.

## What happened

On 6 October the owner listed what still jarred in Pub Quiz Buzz:

> "there is an audio artefact sometimes where the first sound of the
> answer is spoken before the timer starts"

> "the rounds like flags are marked as similar - but they are by design"

> "better to have no elaboration than just a repeat of the question"

> "halfway there... wait, i mean number 8" / "science now... actually
> this is geography"

And every intro said keep tally, and every sign-off asked for the score
in the comments.

## Decisions

**The question is not told the answer.** Each line is voiced with its
neighbours as context (`previous_text`/`next_text`) so the intonation
carries across joins. For a question, the next line is the answer, and
the engine sometimes started saying it in the tail. The 0.25 s pad after
the last word kept that sound, and the countdown starts right there. A
line followed by a held pause (one second or more) is now voiced with no
next line, and cut 0.08 s after its last word with a short fade. A long
quiz cuts the same spans from the shorts, so it's fixed there too.

**A picture question's words are what it pictures.** "Which country's
flag is this?" is the same every time by design. The originality check
now reads a picture question as its subject only, so different flags
are different rounds and the same flags asked again are still a repeat.

**The host's lines are checked, not just asked for.** The prompt says it
(and no longer gives "Beijing. Beijing is the capital of China." as an
example to follow). It was already in the channel's own brief, and the
lines still came, so they are checked locally, for nothing:

- A lead-in that corrects itself ("wait", "I mean", "actually"), says
  another question's number, or puts a milestone in the wrong place
  ("halfway" away from the middle, "last one" before the last) becomes
  a plain "Question eight." One that says neither its number nor a true
  milestone does too: the viewer keeps count by it.
- An answer whose extra words are all the question's ("Louis the
  Fourteenth, he was called the Sun King") is cut to the answer as the
  host first said it. A number, or more than one new word, counts as a
  real addition. On the 21 rounds written ahead at the time, every one
  it caught (51) was a rehash; none were real additions.

Rounds written ahead before the check get it when they're made.

**Intros and sign-offs are shown back.** The writer sees the channel's
last eight of each and is told to vary them. Keeping score is only
sometimes asked for. The sign-off makes at most one ask, rotated: score,
next category, send to a mate, subscribe or follow, or none.
