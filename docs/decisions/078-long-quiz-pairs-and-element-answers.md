# 078 — A long quiz's two versions go out one or the other; symbols only for element questions

**Status:** active. Changes Pub Quiz Buzz (frozen, decision 075) at the
owner's request; its frozen check is unchanged by it.

## What happened

The owner, 7 Oct:

> "Ancient History: Impossible Difficulty Quiz video has the answer Ra - but
> it is pronounced weirdly because it is the same as Ra the chemical
> element. is there a way to limit this pronunciation switch for elements
> to be ONLY elements"

> "publishing both the answers immediately and answers at the end of the
> round versions would be reusing content ... approving both means that it
> is going to send both out. and i cant discard one without it counting as
> a discard for the analytics ... it would be good to properly "pair" these
> videos ... do some analytics to see which style does better. another
> option is to have a separate sister channel that posts just one style"

Both versions of Quiz Night 1 had been approved and queued (10 and 17 Oct).

## Decisions

**A two-letter answer is spelled out as a symbol only when its question is
about elements** (`quiz.element_respellings`): the question mentions a
symbol, an element, chemistry, the periodic table or atomic numbers. A
question naming a symbol ("the symbol Ra") is spelled as before. The
respelling still applies to the whole round when it applies, so a round
asking both radium's symbol and the sun god would spell both; rare enough
to leave.

**Remake can voice a video again line by line** (Remake page, "Voice again
any line the voice would now say differently"): the video's own script,
with each unchanged line's recording reused from the voice cache, so only a
line like the Ra answer is paid for again. "Remake as is" keeps the whole
voice track, so it couldn't pick up a pronunciation fix.

**A long quiz's two versions are a pair** (`core.long_pairs`):

- Approving one sets the other aside (`gallery.set_aside`,
  `set_aside_for` in its publish sidecar, written only when set): out of
  Review and the queue, not a discard, so discard figures are untouched.
- Approving the other later swaps them; taking the chosen one out of the
  queue brings both back to Review.
- One never goes out once its other version has: approving it is refused,
  and the publisher sets it aside if it somehow comes due.
- Review says which version it is, what approving does, and which one is
  suggested for the episode. Suggestions alternate (answers as you go on
  odd episodes, at the end on even ones) so both styles get published.
- The Videos tab lists set-aside versions in their own section, with
  "Publish this version instead".
- Insights compares published long quizzes by style: views, % watched and
  minutes watched, averaged.

Quiz Night 1's at-the-end version was set aside, keeping the answers-as-you-
go version (episode 1's suggestion) for Sat 10 Oct.

**No sister channel for the other style.** YouTube's spam policy covers
"the repeated posting of the same or similar content across one or more
channels", and its inauthentic-content policy looks at effectively
identical renders on several channels. The two versions share their
questions, voice and board; posting one on each of two channels is the
cross-channel case, more visible than both on one. Publishing one version
per quiz and alternating the style is how to compare them safely.
