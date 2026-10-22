# 130 — The newsroom audited, and its board

**Status:** active. Follows decisions 127–129.

## What the owner asked (22 Oct)

> go through it and audit it completely, firstly making sure that it is
> solid and effective at what it aims to do, also analysing places for
> increased output, such as places another agent would be a benefit, or
> parts that can be reused. also make sure that the newsroom has a good
> output screen in the app … a flowchart style display that shows the
> process and where it is up to, and also showing what is expected to be
> completed next time it runs. it should be mostly visual rather than text
> based

They put the weekly limit at about 3,000 points and asked for 120 points a
session.

## What the audit found, and what changed

**Solidity:**
- **No lock on the ledger.** The ledger (`newsroom.json`) was read and
  written by every command with no lock, so two roles handing in at once
  could undo each other's record. It now has a lock file (`locked`), taken
  around handing out work, handing it in, recording usage, and the search
  cache.
- **Reviews wrote into the film's record.** Storyboard and teaser reviews
  logged into the film's production while the app may be writing the same
  file. Those summaries now stay in the ledger only, and the three older
  films' stray entries were moved out.
- **A stuck film came back forever.** A film whose step could never be
  accepted was handed out again every session. After two rejected
  assignments it's held, and shows red on the board with a **Try again**
  button (`held`, `release`).
- **Interrupted work showed as failed.** A storyboard cut short by an app
  restart is resumed, not lost. The board shows it as waiting, not red.

**Effectiveness:**
- **A test audience** (`newsroom-test-audience`) runs between the packaging
  and the final read. Three cold viewers meet the title and thumbnail and
  hear the first hundred seconds. They say who clicks and at which scene
  each would leave. The managing editor reads their verdicts and sends the
  film back when two of three scroll past or leave early. Retention in the
  first minute is the channel's measured weakness, and only a cold read
  tests it.
- **The scout hears the editors' verdicts** on recent pitches and proofs
  (`_pitch_verdicts`), so it stops pitching what keeps being sent back.
- **The analyst reads the newsroom's own record:** reworks, line edits,
  fact fixes, picture changes and the test audience. A writer's habits show
  there long before viewers' numbers do.
- **Stronger models for the judging roles.** The writer, script editor,
  managing editor and commissioning editor run on Opus. The rest stay on
  Sonnet.

**Output:**
- **Caps:** 120 points a session and 1,500 a week, half the owner's
  estimate of the weekly limit. The bank of six films in hand still slows
  the newsroom once films are waiting.
- **Parallel work:** a session runs up to three assignments at once, each
  for a different film (`PARALLEL`). The lock makes that safe.

**Reuse:**
- **Sources.** The scout's sources travel with the pitch to the writer and
  the fact checker, so research isn't done twice.
- **Searches.** A YouTube search made in the last week is answered from the
  ledger, using no quota.

**Considered, not built yet:**
- **A thumbnail editor** that looks at the drawn thumbnails. It needs a way
  to redraw a thumbnail with notes first, or it can only complain.
- **Newsroom-written teasers.** They cost about 5 cents a film on the API
  and already pass the teaser editor.

## The board

The **Newsroom** tab (`/channels/<key>/newsroom`, `core.newsroom.board`)
shows:

- **Four tiles:**
  - **Next run:** the time, the countdown, and a pip for each step it should
    get through, film by film (`plan_next` simulates the session's points,
    assuming each verdict goes the film's way);
  - **This week:** the points used, as a ring, and the tokens;
  - **Voice:** films left in the allowance. It goes red when empty, as it
    is until 7 November;
  - **Analyst:** the findings by how sure they are. The text appears on
    hover.
- **Every film as a flow.** Its eleven newsroom steps, then the studio's four
  (storyboard, video, your look, out):
  - each step is an icon in a state colour: done green, up next gold,
    working with a spinning gold edge, expected next run dashed gold,
    waiting on you solid gold, stopped red;
  - a badge marks what changed: sent back, lines edited, facts fixed,
    pictures changed, a new title, how many of the three test viewers
    clicked;
  - hovering a step shows one card with who did it, its verdict, scores and
    the changes.
- **Groups:** films are grouped into in the newsroom, in the studio, out and
  scrapped.
- **Refresh:** the board redraws every thirty seconds while it's open and
  nothing is hovered.
