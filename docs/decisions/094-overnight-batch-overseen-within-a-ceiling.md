# 094 — Films made overnight at batch prices, overseen, within a ceiling

**Status:** active. Builds on 086 (the autopilot) and the batch mode in
`pipeline.llm`.

## What happened

On 13 October the owner asked for:
- the cost of a film brought down without losing quality;
- whether a scheduled agent on their Claude subscription should oversee
  production;
- a spending cap that is "a rare 'something has gone fundamentally
  wrong'" and never scraps a film nearly made.

Research findings:
- **OpenAI.** The Batch API halves GPT Image 2.5's price, edits
  included.
- **Anthropic.** The Message Batches API halves Claude's price.
- **Subscriptions.** Headless Claude Code still runs on subscription
  limits; the planned move to a separate credit was paused on 15 June
  2026. Max plans include $100–200 a month of API credit; Pro includes
  none.
- **Images through a ChatGPT or Codex subscription were ruled out.** The
  model behind it is undocumented, its allowance is opaque, the consumer
  terms describe personal, non-commercial use, and the tools that
  automate it are unofficial.
- **The owner's choice:** stay on Pro, use the batch calls, and make
  films overnight.

What the salt film's $3.86 showed:
- **Pictures were $2.25.** 70% of that was reference images: about 576
  tokens each, three per picture, at $8 per million. Shrinking them to
  512 px saved nothing, because the count is fixed per image.
- **Writing and checks were about $1.60.**
- **The rate limit.** The account may send 5 input images a minute,
  which is why a storyboard took 35 minutes to draw. Batches aren't
  held to it.

## Decisions

**Pictures in batches** (`images.draw_batch`).
- A storyboard's pictures go as one OpenAI batch at half price. The
  first drawing, the redraws the picture check asks for and the redraws
  the close look asks for are each one batch.
- References are uploaded once (`purpose: vision`) and named by file
  id. Files are deleted once the results are collected.
- A run stopped mid-wait picks its batch up from the journal
  (`cache/image_batches.json`) instead of paying twice.
- A picture the batch couldn't draw comes back empty and goes to the
  stage's usual retry.
- It's used whenever the work is made ahead (`llm.in_batch_mode`), which
  the autopilot's jobs are. Outside batch mode nothing changes.
- The checks between rounds now run side by side (`llm.run_together`),
  one batch round instead of seventeen.

**Claude at batch prices** was already in place for jobs made ahead
(`jobs._made_ahead`).

**A ceiling per film** (`core.film_budget`).
- **Labelling.** Every cost record now carries the film it was for
  (`job_context.set_production`, set by `run_stage`). It's the plan
  entry's id, so renaming a channel doesn't strand it.
- **The level.** The ceiling is twice the channel's usual film: the
  median of its last five made films, $3.50 until it has two, and never
  under $5.
- **Where it applies.** It's checked before every paid Claude and image
  call made for a film, and before each stage.
- **What happens.** A film that reaches it pauses, keeping everything:
  the stage fails with the reason, and nothing already made is thrown
  away. The production page shows "$x of $y" and, when paused, "Allow $z
  more", which raises the ceiling by one usual film.

**Overnight, and overseen** (`documentary.hours`, `documentary.overseen`).
- **Hours.** The autopilot starts stages only in the channel's hours
  ("22-8" runs past midnight). Approvals can happen at any time.
- **Overseen.** An overseen channel's script and storyboard wait as
  "ready". The autopilot approves the angle and the outline as before.
- **The overseer.** A scheduled Claude session (the desktop app's
  `film-overseer` task, hourly 23:30–07:30) reviews whatever waits. It
  runs on the owner's subscription, not the API, using
  `python -m core.overseer` to read the script, edit lines, directions,
  cards and the description, make numbered storyboard sheets, redraw
  pictures, approve, and leave the owner notes. The notes show on the
  production page.
- **Its brief** is `docs/overseer.md`: the checklist from what these
  sessions caught by hand. It may approve only the script and the
  storyboard; the video is the owner's. Its commands are allowed in
  `.claude/settings.json`.

**Why, Though?** is turned on:
- `auto_make`, `overseen`, hours 22-8;
- up to 3 films waiting for a look;
- publishing enabled, but nothing can be posted, since YouTube isn't
  connected and the hand-offs are off.

What this needs from the owner:
- the PC awake and the app open overnight;
- each finished film looked at in the morning.

**Expected cost:** about $1.80 a film (pictures about $1.10, Claude
about $0.70), down from about $3.50, with the same models, references
and checks.
