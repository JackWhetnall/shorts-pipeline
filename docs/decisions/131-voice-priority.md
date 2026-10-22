# 131 — Voice goes to Why, Though? first when credits are short

**Status:** active.

## What the owner said (23 Oct)

> prioritise why though films when credits are short. then the quiz
> channel. then minute pastor. however, if the maths in the Money -> Voice
> page are correct, then having ~2 videos a week on Why Though at ~1,600
> credits, ~7 for minute pastor at ~100 and ~8 for the quiz channel at
> ~300, that makes 6100 per week, which is about 25,000 per month - so we
> should have plenty, right? i assume the reason we are short is because
> of discarded videos

## What the numbers say

**The owner's sum is right.** Worked out the Voice page's way over a month
of slots, the channels need:
- Why, Though?: about 12,700 credits;
- Pub Quiz Buzz: about 7,650;
- Minute Pastor: about 5,050.

That's about 25,400 of the Starter plan's 31,545, leaving about 6,000
spare.

**Where this month went.** It spent about 34,900 credits:

| What | Credits |
|---|---|
| Voicing run by hand on 11–13 Oct, during building and testing, with no channel recorded | 10,785 |
| Three Why, Though? films discarded (Velcro, Mirrors, Pen cap) | 4,299 |
| Two History Unmystified shorts with no video | 2,851 |
| Why, Though? films out or queued | 14,871 |
| The newsroom's first film, part-voiced | 735 |
| The shorts channels and the rest | about 2,350 |

About 18,000 went on work that won't recur: testing and discards. Why,
Though? also made films at 3.5 a week, building a bank of six, where two a
week is now the plan.

## Decision

`publishing.voice_priority` sets each channel's place: Why, Though? 1, Pub
Quiz Buzz 2, Minute Pastor 3. A channel without one comes after every
channel that has one.

A channel starts a new video only if the credits left still cover what
every channel ahead of it needs before the reset
(`voice_quota.reserve_for`). That need counts only the videos that fill its
publishing slots until then, and the teasers it owes, not films it would
make further ahead. Worked out the Voice page's way, it's cached for five
minutes.

**The two places this applies:**
- the scheduler's check before making a short (`scheduler`);
- the autopilot's check before voicing a film (`auto_films`).

Spare voice already keeps back what the films in production need (decision
069). Nothing else changes for the frozen channels: what they make is the
same; when credits are short, they wait their turn.
