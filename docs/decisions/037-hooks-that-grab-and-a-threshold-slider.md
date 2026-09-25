# 037 — Hooks that grab, scripts that sound human, and the animation slider as a threshold

**Status:** active. Revises the hook half of
[036](036-hooks-landings-and-real-props.md) and the slider in
[035](035-scenes-in-the-pipeline.md).

## What happened

The owner judged the first hook, "You lean a ladder against a wall…",
terrible, and they were right. A hook must grab attention instantly;
asking a question isn't enough. They also flagged the closing line
"That's the whole trick, three sides, one equation" as obviously
AI-written, not how a person talks on TikTok.

They also clarified what the animation slider means. It is not "use
animations X% of the video". It is a threshold for how much a specific
segment has to need an animation before it gets one:

- fully to the stock end means stock every time;
- fully to the other end means animated every time;
- just off the stock end means animate only the segments that really
  need it.

## What was decided

### Hooks

036's rules described a curiosity gap, and the model filled that in with
polite scene-setting. The rules are now about stopping a scroll:

- lead with the most surprising, concrete thing in the video, or its
  sharpest consequence;
- prefer a statement to a question;
- make it concrete (a real object, number, person or moment);
- keep it under about 10 words;
- make it understood instantly, on first hearing.

Scene-setting and textbook openers are banned by name: "picture…",
"imagine…", "have you ever", "did you know", "how do you find…".

The writer first drafts five hooks in `hook_candidates`, each by a
different route: the counter-intuitive claim, the real-world
consequence, a startling number, the stakes, the common wrong belief, a
real mystery, and a vivid mid-action line. It then opens with the one a
stranger would stop for.

### Sounding human

`HUMAN_VOICE_GUIDANCE` asks for talk rather than writing, and lists the
AI tells, including:

- "that's the whole trick";
- "here's the thing";
- "it's not X, it's Y";
- "let that sink in";
- rhetorical triplets;
- slogan-shaped closing lines.

The landing is now the concrete payoff (the answer, the number, the
click), then stop. It is never a summary or a moral.

A deterministic detector (`script_gen.ai_tells`) catches the commonest
tells and setup openings. It triggers the same single rewrite that
placeholder text already did, about a penny. The first version missed
four tells in the second round of previews: "that's the whole rule",
"that's the whole snowball", "that's not a trick, it's…" and "Paul
isn't describing X, he's describing Y". It was widened, and there are
regression tests for each. The script check also notes machine-sounding
lines.

Measured on text-only previews (no voiceover), the hooks became:

- "Paul tells a church to kill something inside themselves."
- "Paul says one man's death means everyone else already died too."
- "A penny that doubles every day beats a million dollars, by day
  thirty."

### The slider is a threshold

The scene planner no longer receives a percentage. It scores every
segment 0-10 against a fixed rubric of how much it needs an animated
explanation:

- 10: can't be followed without seeing it;
- 7-9: much clearer with a picture;
- 4-6: helped a little;
- 1-3: footage carries it as well;
- 0: nothing to show beyond a feeling.

It is never told the slider, so the same script scores the same
whatever the channel's setting.

`need_threshold(share)` turns the slider into a bar:

| Slider | Bar | What gets animated |
|---|---|---|
| 0 | none | never animate, and no planning call is made |
| 10 | 9 | only essentials |
| 50 | 5 | anything a picture helps |
| 90 | 1 | almost everything |
| 100 | 0 | every segment |

Consecutive animated segments that build on one picture become one
scene. The settings wording now reads "When to animate instead of stock
footage", with labels running from "Always stock" through "Only when
essential" to "Always animated". The channel draft describes the same
meaning.
