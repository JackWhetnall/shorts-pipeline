# 069 — Credits, not characters; spare voice spent before it resets

**Status:** active. Corrects 025's arithmetic.

## What happened

On 5 October the owner had 18,272 of 30,000 ElevenLabs credits left, two
days before the allowance reset, and asked:

> "it is ideal to not waste this usage, so when it gets close to a reset
> day, unused credits should be used to automatically create videos more
> frequently than the current rate. ideally this would be calculated to
> generate videos that last the longest timeframe, ie fills all the gaps
> in the upload schedule up to the latest possible date."

Working out what a video costs turned up a bigger problem. The app's log
counts characters; ElevenLabs counts credits. ElevenLabs' own history of
the account's last 100 requests showed 7,629 characters of
`eleven_turbo_v2_5` taking 1,527 credits, exactly 0.2 a character. Every
comparison in the app treated a character as a credit:

- the "is there room?" check before each voiceover;
- the scheduler's check before starting a video;
- the APIs page's "about 24 videos left";
- the settings page's monthly estimate;
- the Money page's warning that the allowance wouldn't cover a month.

So the app thought the allowance five times smaller than it was. That was
also why the log and the counter "disagreed fourfold".

## What was decided

**Credits per character are measured, not assumed.** `voice_quota` reads
ElevenLabs' history at most daily. Each item says what it moved the counter
by, and the rate is that over its text's length, for the voiceover model
only. The rate is kept between restarts; if it can't be read, the last
measurement stands, and with none at all a character counts as one credit
(the cautious answer). `require_room`, `has_room_for`, `summary` and the
settings estimate all convert characters to credits with it. The cost log
still records characters.

**Money's voice warning is the schedule's need in credits.** That's each
channel's videos a month times its typical credits a video, against the
allowance. It replaced the pace over the last week, which can be a burst:
5 October's pace came from a week of remakes and tests.

**Spare voice** (`core.spare_voice`, a scheduler duty):

- **When.** It starts in the last 3 days before the allowance resets
  (ElevenLabs reports the date).
- **The plan.** Every scheduled channel's upcoming slots not already
  covered (by videos queued, waiting in Review or being made) are put in
  one list in date order, and filled in that order. Every slot gets a
  video, with no gaps, up to the latest date the spare reaches. When the
  next one won't fit, later slots are still tried, so a cheaper channel's
  video uses what's left rather than letting it go. The first slots in
  that order are the ones the scheduler would fill anyway, so nothing is
  counted twice.
- **Limits:**
  - the credits left, less two of the dearest channel's videos for
    retries and long quizzes;
  - the time before the reset, one video at a time, at the measured
    length of videos made ahead (30 minutes until three have been timed);
  - the Claude credit, never taken below a reserve of two weeks of the
    schedule's own spending (at most $3 in all if the balance hasn't been
    entered);
  - 90 days ahead at most.
- **Running it.** Each tick, if nothing else is being made, it starts the
  video for the earliest slot in the plan. It's made ahead at batch
  prices, with a note saying why. The plan is worked out again every tick
  from live state, so an estimate that was off corrects itself.
- **Where it shows.** On Today (under Running by itself) and on Money,
  with a switch in Money's assumptions. Running low in those days is on
  purpose, so Today doesn't warn about it.

On 5 October the plan was 72 videos (47 Pub Quiz Buzz, 25 Minute Pastor),
filling every slot to Sat 28 November, for about $7.10 of Claude.

## What it means for the owner

- **Review.** The videos go to Review like any other. Seventy-odd made in
  two days is a review backlog, worked through as the slots come up. A
  channel with a backlog makes no new videos until it's reviewed down,
  and that's what carries the stock into the next month.
- **The PC** has to stay awake through the window.
