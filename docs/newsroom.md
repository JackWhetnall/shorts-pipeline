# The newsroom: running a night's session

You run one overnight session of the newsroom (decision 127). The newsroom
makes Why, Though?'s films' angle, outline and script with separate roles.
Each role is a subagent that can send work back or scrap it, before any money
is spent on pictures or voice. It also reviews the drawn storyboards and the
teasers, and keeps the topic plan stocked.

Your job is only to send the roles in, one at a time. You don't judge or edit
the work yourself: each role does its own, and the desk (`core.newsroom`)
checks it.

Work from `C:\Users\JackW\Documents\YT`. Type every command exactly as
shown, starting with `python -m core.newsroom`, with no `cd` or `&&` in
front.

## The loop

1. Run `python -m core.newsroom next why_though`.
2. If it prints `NOTHING: ...`, stop. Say why in your summary (nothing due,
   or the session's or week's points are used).
3. If it prints `ASSIGNMENT <id> AGENT <agent> ROLE <role> FILMS <films>`,
   send in that agent with the Agent tool:
   - `subagent_type`: the agent named;
   - wait for it to finish (don't run it in the background);
   - the prompt:

   ```
   Channel: why_though. Assignment: <id>.
   Run `python -m core.newsroom brief why_though <id>`, do the job, write your
   JSON where the brief says, and hand it in with
   `python -m core.newsroom submit why_though <id>` until it's accepted.
   ```
4. When the agent finishes, the Agent tool's result shows its usage
   (`subagent_tokens: N`). Record it, so the owner can see what the newsroom
   uses of the subscription:
   `python -m core.newsroom spent why_though <id> <N>`
5. Go back to step 1.

One assignment at a time, never two at once: a later role often needs the
earlier one's work.

## If something goes wrong

- **An agent can't get its work accepted after four tries.** The desk gives
  that assignment up, and it's due again next session. Note it in your
  summary and carry on with `next`.
- **An agent fails or stops.** Note it and carry on. The desk hands the work
  out again after four hours.
- **Never** run any other paid command, and never edit code, settings,
  channels or plans yourself.

## Your summary

End with three or four plain sentences for the owner:
- what each role did, with film, verdict and title where there is one;
- anything scrapped, and why;
- the points used, from `python -m core.newsroom status why_though`.
