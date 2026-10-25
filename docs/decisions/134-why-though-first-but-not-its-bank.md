# 134 — Why, Though? first for its month, never for its bank; storyboards rechecked

**Status:** active. Replaces 133's "voice by date" and refines 131. Adds to
133's storyboard reads.

## What the owner said (25 Oct)

> i do want Why Though to take priority when there isnt enough credit for
> the month. however, if there is enough credit for the month, then all the
> months videos should be made. what i dont want to happen is Why Though
> having the whole month made plus the three premade videos prioritised over
> another channel's videos that need to be published this month

> yes lets make sure the storyboards checks work properly.

## Voice: the month in priority order, the bank after everyone's month

**Decision 133 overcorrected.** It voiced whatever was due soonest,
whichever channel it was for. When credits were short, that took away the
priority the owner wants Why, Though? to have. Decision 131 had the
opposite gap: Why, Though? kept nothing back for anyone. So once its own
slots were covered, it could voice films for its bank out of credits that
another channel needed for this month's slots.

**The rule now (`voice_quota.reserve_for`):**
- **A video for one of the channel's own slots before the reset** keeps
  back what the channels ahead of it in the priority need for theirs, as
  in 131. When credits are short, Why, Though?'s month comes first, then
  Pub Quiz Buzz's, then Minute Pastor's.
- **Once a channel's slots before the reset are covered,** a video it makes
  is made ahead, for its bank. That video keeps back what every other
  channel needs for its month.
- **Teasers owed** count as a need for the channels behind. They don't make
  a bank film count as one of the month's own videos.

**With enough credits for the month,** every channel's check passes, so the
whole month is made. Whatever is left then goes to the bank.

**On 25 Oct:**
- Why, Though? had every slot before 7 Nov covered, so a film of its own
  would be made ahead;
- that film would keep back 1,811 credits for Pub Quiz Buzz's one open slot
  and Minute Pastor's 13 open slots.

## The storyboard checks, run for real

The six films passed before the frame checker existed had been read only as
contact sheets of forty. `python -m core.newsroom recheck <channel> <film>`
puts an approved storyboard back through both reads. It does this only
while no video has been made from that storyboard.

**t0029 (thunder), run first and watched:**
- **The frame checker** redrew 7 of 71 pictures:
  - two "air" pictures drawn as a river in a canyon;
  - clouds with faces;
  - runners missing;
  - a reused bolt where the line needed a new one;
  - sound not shown where the line was about it;
  - the Sky Watcher awake where the line has her asleep.

  It left scene 3's blank face, because the line didn't mention faces.
- **The continuity editor** redrew 6 pictures:
  - the blank face in scene 3, and scene 67, which reuses it;
  - four repeated compositions.

  It approved the board but flagged scene 46: two Sky Watchers in one
  picture. A first redraw had kept the fault, and it wasn't allowed a
  second.
- **In all:** 14 pictures redrawn, about $0.24, and about 183,000
  subscription tokens.

**What changed from it:**
- Both roles now treat a blank face as a fault, whatever the line says.
- A redraw that kept its fault may be redrawn once more, with a sharper
  note. No picture is redrawn a third time. Scene 46 was redrawn that way.
- The other five films (t0018, t0028, t0030, t0032, t0034) go through both
  reads in the next newsroom run.

**No automatic check on these redraws.** The image-check calls need an API
key. Claude Code's environment deliberately has none, so the subscription
pays for the roles. So the roles' own look at each redraw is the check.
