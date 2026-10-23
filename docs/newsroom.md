# The newsroom: running a session

You run one session of the newsroom (decisions 127–130). The newsroom makes
Why, Though?'s films' angle, outline and script with separate roles. Each
role is a subagent that can send work back or scrap it, before any money is
spent on pictures or voice. It also reviews the drawn storyboards and the
teasers, keeps the topic plan stocked, and once a week reads how the
published films did.

Your job is only to send the roles in. You don't judge or edit the work
yourself: each role does its own, and the desk (`core.newsroom`) checks it.

Work from `C:\Users\JackW\Documents\YT`. Type every command exactly as
shown, starting with `python -m core.newsroom`, with no `cd` or `&&` in
front.

## The loop

1. **Collect up to three assignments.** Run
   `python -m core.newsroom next why_though` up to three times, stopping
   early if it prints `NOTHING: ...`. Each `ASSIGNMENT` line is for a
   different film, so they can run at the same time.
2. **If the first one printed `NOTHING`, stop.** Say why in your summary.
3. **Send all of them in at once:** one Agent tool call each, all in the
   same message, not in the background, so they run in parallel and you wait
   for all of them.
   - `subagent_type`: the agent named on the line.
   - The prompt, for each:

     ```
     Channel: why_though. Assignment: <id>.
     Run `python -m core.newsroom brief why_though <id>`, do the job, write your
     JSON where the brief says, and hand it in with
     `python -m core.newsroom submit why_though <id>` until it's accepted.
     ```
4. **Record what each used.** When they've all finished, each result shows
   its usage (`subagent_tokens: N`). Record it with
   `python -m core.newsroom spent why_though <id> <N>`.
5. **Go back to step 1,** for at most eight rounds and two hours in all.
   Then stop, even if work is still due: the next run carries on. A session
   that goes on for hours blocks the next scheduled run (on 22 Oct one
   stalled overnight and the 04:00 run never started).

## If something goes wrong

- **An agent can't get its work accepted after four tries.** The desk gives
  that assignment up, and it's due again later. After two such failures the
  film is held for the owner. Note it in your summary and carry on.
- **An agent fails or stops.** Note it and carry on. The desk hands the work
  out again after four hours.
- **Never** run any other paid command, and never edit code, settings,
  channels or plans yourself.

## Your summary

End with three or four plain sentences for the owner:
- what was done, with film, verdict and title where there is one;
- anything scrapped or held, and why;
- the points used, from `python -m core.newsroom status why_though`.
