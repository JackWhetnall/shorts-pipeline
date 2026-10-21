# 128 — An analyst for the newsroom, and its films first

**Status:** active for Why, Though?. Follows decision
[127](127-the-newsroom.md).

## What the owner said (21 Oct)

> yes change the opening rule, and put newsroom films first
>
> also, is there a retrospective agent that looks at previous videos,
> click-through and retention etc and feeds this back to the agents
> responsible for these things eg script and thumbnails etc?

## What there was

There was only part of one. Each film got two generic lessons from its own
retention curve once it was a week old (`core.lessons`, decision 086). Every
writer reads those lessons. A clear thumbnail or title test win was noted the
same way (decision 125). The newsroom's roles saw the published films' raw
numbers.

Nothing read across films. Nothing turned the figures into advice for each
role's own work, said how sure it was, or checked whether the editors' scores
predicted how a film did.

## Decision

**An analyst.** A new role, `newsroom-analyst`, runs weekly: when a film has
had its first week since the last analysis, and at most once in six days.

It reads every published film:
- title, thumbnail words, impressions and click-through;
- share watched, share kept at 30 seconds, and every drop, with what was said
  and shown when viewers left;
- chapter titles and opening;
- the newsroom's own verdicts and scores;
- the thumbnail and title tests' figures;
- its last findings.

It hands in at most four findings each for the scout, the writer, the script
editor, the packaging editor and the picture editor. Each finding says what
to do, gives its evidence (which films, which figures) and is rated strong,
suggestive or hunch. A hunch is anything from one film or under about 50
views. The desk refuses a finding without evidence or a rating.

Every later brief opens with the latest findings for that role
(`newsroom.findings_text`). The findings are filed in the channel's folder
(`newsroom_findings.json`), with the last twelve analyses kept.

**Newsroom films first.** On a newsroom channel, the films the newsroom wrote
go out before films made the old way (`publish_queue.queued`). Other channels
keep approval order. A passed film already counts as being made, so the
autopilot draws it even while the old films fill the bank.

**The opening rule.** Why, Though?'s *How it opens a video* now reads:

> First line: the most surprising concrete fact in the film, said plainly,
> the one that makes the obvious answer wrong. Never the title's question
> again: the viewer has just read it. The question, in new words, can
> follow.

It used to ask for the question first, which is where the films lost their
viewers.
