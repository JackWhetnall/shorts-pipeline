# 107 — Outlook, teasers with their film, Money by channel, the queue in order

**Status:** active.

## What the owner asked (16 October)

1. Teaser endings with more zing. "The full documentary on this
   channel" was clunky, and clunkier repeated, and "documentary" is
   overkill for Shorts viewers.
2. Insights should separate Shorts from long videos and link teasers to
   their film: "it's the long form video watches that matter".
3. A film's Shorts should be published close to it.
4. Money's "Getting it back" and "Partner Programme" sections should
   follow the channel dropdown. A more visual page: subscribers, watch
   hours, whether the Partner Programme is reached before the bar rises,
   projected cost and when it turns a profit.
5. The channel page's queue should be in publishing order, not shorts
   then longs.

## Decision

**1. Teaser pointers.** The full video is pointed to in a few crisp
words with some zing (examples: "The answer's in the full video", "Full
video's on the channel"). The pointer may come before the last line.
- It's always "the video", never "the documentary", and never "on this
  channel" tacked onto the end.
- No two teasers point the same way.

**2. Insights.**
- Long videos get their own table: views, watch hours, % viewed, subs,
  and their teasers (how many, and their views), with each teaser listed
  beneath its film.
- Other Shorts have a table of their own.
- Each section has its own totals and median.
- `teaser_of_video` (the film's path) is now written into each teaser's
  report. The six teasers already made were linked by hand from their
  productions.

**3. Teasers go out with their film.** In a shorts lane with teasers in
it (`publish_queue._shorts_with_teasers`):
- a teaser takes the first shorts slot after its film's own slot;
- once the film is out, its teasers go first;
- while its film isn't queued, a teaser waits and shows "After its film";
- every other short keeps its order in the slots left.

`publish_due` sends whichever video the schedule puts in the due slot.
A lane without teasers is scheduled exactly as before, and the frozen
suite passes.

**4a. Money by channel.** `money.for_channel` narrows the forecast to the
channel chosen in the header:
- its share of the month's cost (the ElevenLabs plan split by how much
  of the voice each channel's schedule uses);
- its rows, its Partner Programme progress, and its payback.

The balances stay account-wide.

**4b. Outlook** (`/money/outlook`, `core.outlook`), linked from Money:
- **The data:** YouTube Analytics day by day for the last year, split by
  `creatorContentType` into Shorts and long videos. It's read at most
  twice a day and only the latest copy is kept; it moves with a renamed
  channel.
- **The tiles:**
  - the Partner Programme date, with "Before the bar rises", "After 1
    Feb 2027" or "Off pace";
  - "Pays its way" and "All spend back";
  - the month's cost.
- **Progress bars:** subscribers and watch hours, each against the pace
  needed before 1 Feb 2027.
- **Long views from Shorts:** long-video views per 1,000 Shorts views,
  which shows whether the teasers are working.
- **Four charts,** each with a crosshair tooltip and a table:
  subscribers, long-video watch hours, long-video views a day, and spent
  against earned.
- **The projections** carry the last four weeks' pace forward in a
  straight line. Earnings start at the Partner Programme date, at the
  Money page's RPM, with views growing at their eight-week trend. Past
  three years out, a date isn't given ("Not at this pace").
- The chart colours are the reference palette's dark slots, validated
  against the app's surface.

**5. The channel page's queue** (`publish_queue.in_order`) lists shorts
and long videos together, in the order they go out.
