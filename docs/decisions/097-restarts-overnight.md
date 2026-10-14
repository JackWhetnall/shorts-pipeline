# 097 — A restart overnight

**Status:** active.

## What happened

At 00:14 on 14 October, Windows restarted the PC for an update ("Operating
System: Upgrade (Planned)"). The machine then sat at the sign-in screen
until 09:46. The app and Claude only start when someone signs in, so
nothing ran for nine and a half hours, and the overseer's runs from 00:30
to 07:30 never happened.

## What was found

**Nothing was damaged.**
- Every JSON file under `config/`, `cache/` and `channels/` reads.
- Every line of the cost log reads.
- No temporary files were left behind. The only damaged file is the
  quiz plan already known from 7 October.

**No film had work cut short.** The night's film (t0003) had finished
its script at 23:09 and was waiting for the overseer. The overseer's
23:31 run stopped after two commands, without a summary, so the script
was still waiting at the restart.

**Restarting mid-stage would have gone wrong, though, in three ways:**
1. **A stage could stay "working" for good.** `run_stage` marks a stage
   working until it finishes or fails. A restart does neither. Jobs
   already became "interrupted" at startup, but the production didn't:
   the autopilot skips a working stage, so that film would have stopped
   for good, and an owner's edit would have been refused as "busy".
2. **A damaged film record would have been replaced by a blank one.**
   `production.load` returned a blank film for unreadable JSON. The next
   save would have overwritten the real record, and the autopilot would
   have paid to make the film again from its angle.
3. **Saved files could be cut off.**
   - Drawn pictures were written straight to their final name, so a
     cut-off picture would later have been treated as drawn.
   - Job records were written the same way.
   - The atomic write never flushed to disk before renaming.

## Decision

- **`production.recover_interrupted`** runs at startup (`web/__main__`),
  after the job records are reloaded.
  - Every stage still marked working becomes failed, with "Stopped
    part-way: the app or the PC restarted." and an `interrupted` flag.
  - The film's history records it.
- **The autopilot restarts an interrupted stage** in the channel's hours,
  without using up the one retry a real failure gets. Whatever it had
  already paid for is picked up again:
  - pictures already drawn;
  - voiced lines;
  - Claude and OpenAI batches, which are journalled.
- **An unreadable film record is never replaced.** `load` raises a
  `ProductionError`. `all_for` logs the error and skips that film, so the
  rest of the channel still works and the file stays as it was.
- **`write_atomically` flushes the file to disk before renaming it**, and
  accepts bytes.
  - Pictures, from single calls and from batches, go through it.
  - Job records go through it too.

## What the code can't do

Windows decides when it restarts. The owner set
`NoAutoRebootWithLoggedOnUsers`, which stops automatic restarts while
someone is signed in. Windows doesn't apply every policy on every
edition, so TASKS lists the settings that keep a night's work going
regardless:
- Active hours covering the night.
- Automatic sign-in after an update. The app's logon task then starts it
  again.
- Claude opening at sign-in, for the overseer.
