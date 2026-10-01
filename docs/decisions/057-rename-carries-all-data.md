# 057 — Renaming a channel carries all its data

**Status:** active.

## What happened

On 1 Oct the owner renamed the quiz channel (The Pub Quiz Round to Pub Quiz
Buzz) and it then showed no topics and no videos.

A channel's key is the name its data is filed under, and the data is
spread over a dozen places. The rename moved only three: its config entry,
its assets folder and its output folder. Everything else stayed filed
under the old name, where nothing would look for it:
- the topic plan, 96 videos' worth, which also carries the channel's name
  inside the file and saves to the file that name gives;
- the question memory, so no question would have been caught as a repeat;
- the originality history, with each video's path;
- the cost log (706 records), the fact and question "used" records in the
  fact store, footage owned, YouTube token, job records, previews.

Nothing was lost. It was all still on disk under the old name, and a
backup was taken before anything was moved.

## What was decided

`core/channel_data.py` moves all of it (`migrate(old, new)`), and the
rename calls it as its last step:
- each store moves independently, so one failure doesn't strand the rest;
- anything already filed under the new name is joined, not overwritten,
  and a file that would be overwritten is left where it is and reported;
- running it again changes nothing more;
- paths stored in the data to the channel's output folder are rewritten;
- problems are shown on the channel's page, saying nothing is lost.

The data was moved for this rename by running it by hand. Counts were
checked against the backup: 16 topics, 96 subtopics, 16 written scripts,
7 video links, 14 rounds of question memory, 18 videos, 220 used records.

**The rule going forward:** anything new that stores data per channel must
be added to `channel_data.migrate`, with a case in
`tests/test_channel_data.py`. (The cost log keyed its records by
`channel_key` where the discard log used `channel`; the first version of
this checked the wrong one and the check against real data caught it.)

## What was rejected

- **Making the key permanent and the name a label**, so a rename never
  moves anything. It's the better design, but the key is in every
  URL, folder and file name already, and changing that is a bigger and
  riskier change than moving the data.
- **Refusing to rename a channel that has data.** It would have been safe,
  and not what was wanted.
