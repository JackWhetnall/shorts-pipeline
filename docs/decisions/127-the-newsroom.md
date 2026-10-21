# 127 — The newsroom: roles that can send work back or scrap it

**Status:** active for Why, Though? (`documentary.newsroom`). Other
documentary channels still use the API stages of decision 086. The overseer
(decision 094) becomes two of the newsroom's roles.

## What the owner said (21 Oct)

> At the moment we have one agent that runs that is entirely in charge of
> the video's output, but nothing that checks whether it is actually going
> to be good before it gets made. If we instead treat this as a journalism
> company we could have various agents: one that finds a good topic … one
> that receives this pitch … and works out if it is viable … a script
> writing agent … another agent who checks it and edits it … at no point
> is there any verification that topic X will actually result in a good
> script, each part of the process assumes that the previous or next part
> is going to deal with whatever is made.

They also said:
- **Limits:** "it of course needs to be less than the weekly limit per week
  of activity, and can be run overnight so as to avoid hitting my hourly
  limits - and staggered if needed";
- **Pace:** two films a week, "as this still hits 52 videos a year and allows
  time for improvements";
- **Scope:** Why, Though? only.

## What was there

The API pipeline had checks, but none could stop a film:
- **The pitch scored its own angles** and always chose one.
- **The critic was the writer's own model at low effort,** rewriting at most
  two chapters.
- **The overseer read the script only after it was written,** and could only
  fix lines.

So a weak topic went all the way to pictures and voice. The first films kept
10–14% of viewers, against about 30% typical. The Mars film lost half its
viewers in eight seconds, while its opening restated its title.

## Decision

**Roles.** Each is a subagent (`.claude/agents/newsroom-*.md`) on the
owner's Claude subscription:

| Role | Who | Verdicts |
|---|---|---|
| pitch | scout | the question, the true answer, demand from a YouTube search, 6–9 beats, the angle, the risks |
| commission | commissioning editor | commission, rework once, or scrap |
| proof | writer | the outline and the whole first chapter |
| proof review | script editor | go, rework twice, or scrap |
| draft | writer | the whole script |
| edit | script editor | edits lines; pass, rework twice, or scrap |
| facts | fact checker | every claim and card, checked against real sources |
| pictures | picture editor | every picture planned together |
| packaging | packaging editor | title, thumbnail and description, from the finished script |
| final | managing editor | pass (it's drawn), back once, or scrap |
| storyboard, teasers | picture editor, teaser editor | the overseer's checkpoints 2 and 3 |
| bank | scout | stocks the topic plan |

**The proof is what checks a topic.** A topic is accepted only after its
outline and first minute have been written and an editor who didn't write
them has passed them. Answering the owner's point, a topic now has to
produce a good script before the rest is written.

**The desk** (`core/newsroom.py`) does four things:
- hands out what's due, the film nearest done first;
- briefs each role with the same instructions the API stages use, so
  nothing earlier decisions taught is lost (`pitch.prompt`,
  `outline.prompt`, `script.instructions`, the editor's critic, fact and
  card rules, the picture editor's rules);
- briefs each role with the channel's published films: views,
  click-through, share watched, share kept at 30 seconds, and what was said
  where viewers left;
- holds the work it gets back to rules a model can't argue with:
  - demand evidence and at least five beats;
  - no score under 6 commissioned, passed or sent on;
  - rework limits;
  - each chapter at least 85% of its length;
  - the outline's retention rules;
  - the title rules;
  - the picture editor's counts.

**Demand.** `python -m core.newsroom demand` searches YouTube for 4–20 minute
videos and reports views, age, the channel's subscribers and views per
subscriber. That costs 101 quota units a search, with at most 25 a day.

**Where it hands over.** A passed film's angle, outline and script are
approved by the newsroom. The autopilot then draws and voices it as before.
It never writes a newsroom channel's films (`auto_films.NEWSROOM`), and the
scheduler doesn't pitch them ahead. A scrapped film leaves the plan with its
reason.

**Limits.** Work is counted in points: a draft is 3, a proof or an edit 2,
anything else 1. A film takes about 15. The caps are 4 points a session and
36 a week.
- **Sessions:** two, at 23:00 and 04:00 (the `newsroom` scheduled task),
  five hours apart, so each falls in its own five-hour window.
- **Pace:** at two films a week, each film has three nights or more.
- **Usage:** each assignment's token use is recorded (`spent`), so the
  points can be retuned against the real weekly limit. The first scout
  assignment used 118,000 tokens for three pitches.

**Cadence.** Why, Though? publishes films on Tuesday and Saturday.

**Cost.** A film's Claude spend was about $0.80, of which about $0.55 was
writing and planning. That part moves to the subscription. Pictures, voice,
teaser writing and title variants stay on the API.

## Found on the first live run

The scout's three pitches came back with real search numbers.
- **"Why is the sky blue"** is crowded with big channels. "Why isn't the sky
  violet" pulls on its own.
- **A namesake.** A small channel already named "Why Though?" (Dr. Matt
  Agnew) turned up in the results.
- **A conflicting rule.** The channel's opening rule asks for the question in
  the viewer's words first. That conflicts with what the retention data
  shows, so the writer and script editor are told that the first sentence
  must still land the surprising fact. The rule itself is the owner's to
  change.
