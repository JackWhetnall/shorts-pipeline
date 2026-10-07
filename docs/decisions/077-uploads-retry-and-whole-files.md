# 077 — Uploads retry a temporary failure; saved files are never interleaved

**Status:** active.

## What happened

On 7 October the owner: "the app is stuck saying 'The app was updated since
it started and is restarting...', and the automatic uploads didnt happen".
Three separate things, found in the app's log:

- **The upload.** Pub Quiz Buzz's 18:00 upload on 6 Oct got
  `500 Internal error encountered` from YouTube, a failure on Google's side.
  Every failed upload was treated alike: the video was taken out of the queue
  and sent back to review, so it was never tried again and the slot went by.
- **A damaged plan.** At 04:41 on 7 Oct, Pub Quiz Buzz's topic plan
  (`config/curricula/pub_quiz_buzz.json`) was left with 38 characters of an
  older copy after its own end. Two saves at the same moment had both
  written one shared temporary file (`.json.tmp`), interleaving. Every read
  of the plan then failed, which stopped Pub Quiz Buzz's spare-voice
  videos, plan top-ups and storyboards.
- **The "stuck" message** was from 18:33 on 6 Oct: "Write the outline" was
  pressed while the app waited to restart onto new code, which it does only
  once nothing is being made, about an hour later then. The page kept the
  message in its address, so refreshing it on 7 Oct showed it again. The
  message said "try again in a minute", which wasn't true.

## Decisions

- **A temporary upload failure is tried again** (`publish_queue.transient`):
  HTTP 408, 429, 500, 502, 503, 504, or a dropped connection. The video
  stays queued and its slot stays due, so the next check, five minutes
  later, tries again, up to `RETRY_TRIES` (6) checks. Only then, or at once
  for a real refusal (quota, permissions, a bad file), does it go back to
  review as before. A YouTube error now carries its HTTP status.
- **Every save of a plan or a production is written through its own
  temporary file** (`core.paths.write_atomically`), one writer at a time
  per file within the app, and a replace that Windows refuses for a moment
  (a reader holding the file) is retried. A reader sees the old file or the
  new one, never a mix.
- **The restart message says what it waits for**: the video being made now.
- The damaged plan was repaired by keeping its first, complete copy (all 90
  entries); the damaged file is kept in `cache/`. The bounced video,
  approved before, was put back in its queue.

## Not done

- Two saves at the same moment can still lose one of the two changes
  (each loads, changes and saves the whole plan); the file is whole either
  way. A lock around each change, or one database, would settle it.
