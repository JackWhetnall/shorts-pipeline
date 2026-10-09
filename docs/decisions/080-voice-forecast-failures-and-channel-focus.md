# 080 — The voice allowance read right, failures you can act on, and one channel per browser

**Status:** active. Corrects the forecast of 067 and the premise of 069.

## What happened

On 9 October the owner raised four things.

**A failure that couldn't be dealt with.** Today said "A Minute Pastor
video didn't finish" with a "See it" button to Activity. Activity no
longer listed it, it said nothing about why, and it couldn't be cleared.
It was 2 Kings 2:16, which stopped on 5 Oct while preparing its
background clips and was never remade.

**The voice allowance looked wrong.** Today said the voice would run out
on 4 Nov. Money explained it in a paragraph ("About 1,166 credits a day
lately"), with a tooltip that ran off the screen, and didn't say whether
its number was used or left. The owner's ElevenLabs page showed "12,972
credits / 30,000". And ElevenLabs says unused credits roll over for up to
two months, so "we don't need to panic-make videos at the end of the
month after all".

**One channel per browser profile.** The owner keeps a browser profile
per channel, signed in to that channel's social accounts, and wanted the
app in each to show just that channel.

**Stale badges.** The counts on the menu only changed on navigating:
"nothing to post" at a glance, then two to post on the next page.

## What the voice numbers really are

Read on 9 Oct from ElevenLabs' subscription endpoint (the app's source)
and checked against its own request history:
- Used this billing month (since the reset on 7 Oct at 17:28): 1,167
  credits. The history agrees: 57 requests since the reset moved the
  counter by exactly 1,167.
- Allowance: 31,545. That's the plan's 30,000 plus 1,545 rolled over.
  The day before the reset, 28,455 of 30,000 had been used, so the 1,545
  left carried over. Rollover is real on this account.
- So the "12,972 credits / 30,000" on the owner's page isn't this
  month's: it doesn't match the counter since the reset, nor the month
  before it. It's most likely a usage view over another date range. The
  app shows the subscription's own figures and says so.

The 4 Nov forecast came from one day of readings: 1,166 credits on 8 Oct,
the day the first documentary was voiced, taken as the daily rate. It
counted none of the 58 videos already made ahead.

## Decisions

**The voice is judged against what the schedule still needs**
(`money.voice_need`). For each running channel, the publishing slots
between now and the reset, less the videos already made and waiting
(queued or in review), at that channel's typical credits a video. Then:
enough, or short by how much, and only when short, the date it would run
out. On 9 Oct that was 4,025 credits (35 videos, 58 made ahead) against
30,378 left: enough. A pace is shown only from three days of readings or
more.

**Money shows figures**: used, left and the month's allowance (rollover
included, said in a tooltip), a meter of what's used, then a short list
of the reset date, what's still to voice before it, and the verdict.

**Spare voice is off by default.** Its premise, that credits left at a
reset are lost, is false on a paid plan. The setting stays for anyone
who wants it.

**Tooltips wrap and stay on screen.** Near either edge of the window
they open towards the middle (app.js) and are never wider than the
window.

**A failed video says what, when, why and what to do.** For example, "2
Kings 2:16, Mon 05 Oct, 23:33 (3 days ago). It stopped while preparing
16 background clip(s)." When the stored error is the generic one, the
last stage it reached is read from its log. Retry and Discard are right
on Today. A failure whose quote or entry has since been made is
dismissed by itself.

**The focus: one channel, or all, per browser** (`web/focus.py`, a
cookie, so each browser profile keeps its own). A switcher sits in the
header. With a channel chosen:
- Review, Queued, To post and the menu's counts show that channel only;
- the menu's "Channels" becomes "Channel" and goes straight to its page;
- Today and Activity still show everything, since something needing you
  on another channel shouldn't be hidden.

**The menu's counts poll** (`/api/nav-counts`, every 30 seconds, and
when the tab comes back into view), so To post appears when there's
something to post.
