# 118 — Films that work by ear; the overseer keeps the topic bank

**Status:** active. Builds on the explainer of decision
[089](089-explainers-gentler-depth-fitting-sound.md), the picture editor of
[092](092-pictures-planned-as-a-set.md) and the overseer of
[094](094-overnight-batch-overseen-within-a-ceiling.md).

## What the owner said

- **Mirrors** were a poor choice for Why, Though?. The film relies on
  pictures being visually accurate, and the image generation can't
  guarantee that.
- **The stop sign** turns on "particular stages of a shape and colour
  design that the images dont quite get right at every step". The owner
  wouldn't have made it.
- **In the pen cap film**, the narration has the cap "stuck if it is
  lodged in a sideways position", but the picture doesn't show it
  sideways. The topic was poor anyway: its title says the hole isn't
  there to save your life, and the answer is that it is, by making
  choking survivable.
- **Good examples** are the salty rivers and the tickling films.
- "Visual errors like this kill the validity and trustworthiness of the
  whole channel, so ideally we need to stop them from occurring at all."
- "We need to make the overseer create new topics and subtopics when the
  topic bank is running low", consistent with how the channel explains
  things and what it can do well.

## Why it happened

- **The prompts asked for it.** The outline told the writer to "show,
  don't caption: the picture adds what the words can't". The explainer
  wanted the cold open's proof "shown", the mystery "solved in one clear
  picture", and pictures of "things side by side at their real scale".
- **Nothing chose films for what the pictures can do.** The plan's
  writer was the generic syllabus writer, and nobody topped up a plan
  once its topics were filled. Why, Though?'s plan said "running low"
  with no unfilled topic, so nothing happened, and it was draining.

## Decision

**Each kind of channel's rules for what it can make well**
(`kinds.TOPIC_FIT`):
- the answer works by ear, for someone listening with their eyes shut;
- the pictures only illustrate, since the image model can't be trusted
  with exact shapes, positions, angles, directions, stages, layouts,
  counts, text, maps or diagrams;
- the question has an honest answer that the title doesn't contradict;
- the subject is familiar, with a surprising true answer.

The owner's own examples, good and bad, are in it.

**Whoever chooses films is given those rules:**
- the plan's writer, for a documentary channel only
  (`curriculum_gen._fit`, in `write_subtopics` and `extend_outline`);
- the overseer.

**Every stage of a film is told the words carry it** (all documentary
channels):
- **The outline:** pictures illustrate and set the mood; nothing depends
  on one being exact.
- **The explainer's shape:** its proof is said, not shown; the mystery is
  solved in plain words; nothing is "side by side at scale".
- **The script:** the narration works with your eyes shut. It never
  points at the picture or needs it to show an exact detail, and a
  picture's direction never asks for one.
- **The pitch:** an angle works by ear, and a title never claims what
  the answer contradicts or walks back.
- **The picture editor** (rule 5): a picture whose point is a precise
  detail is redirected to one that stays true however it's drawn.
- **The picture check** (`stills.FLAWS`): a detail the description
  states, drawn differently, is a fault to redraw.
- **The overseer's checklist:** item 10 for the script, and a bullet for
  the storyboard.

**The overseer keeps the topic bank** (`core.overseer topics`,
`add-topic`, `add-subtopics`, `skip-subtopic`).
- `status` says when a channel's bank is running low (under
  `curriculum.LOW_WATER_MARK`, 30 waiting).
- On those nights it does three things:
  - reads the plan sheet: the channel's rules, every waiting subtopic,
    the films made with their views and how much was watched, and what
    was skipped;
  - skips waiting subtopics that clearly break the rules;
  - adds one topic of eight to twelve subtopics.
- The tool works only on a documentary channel's plan, and skips only
  subtopics still waiting.
- A topic the overseer adds is filled, so the app doesn't write its own
  subtopics for it. A topic left empty is still filled by the app's
  writer, which is now given the same rules.
- The scheduled task's prompt includes the step.

**Why, Though?'s bank was pruned now** under the owner's rules. Skipped,
and reversible on the plan page:
- mirrors, and the pen cap (the owner's two);
- toast turning as it falls;
- the letters on a keyboard;
- the Earth's tilt through the seasons;
- the tides' two bulges.

That leaves 22 waiting, so the overseer adds a topic on its next night.

## Not changed

- **Films already made.** The stop sign film is still due to go out; the
  owner decides whether it does.
- **Velcro** stays in the plan. Hooks and loops can be told by ear, and
  its last film was discarded for other reasons.

## Rejected

- **A model to judge each finished picture against its line's every
  detail.** It costs a call per picture, and a redraw of a detail the
  image model can't draw comes out wrong again. Not asking for the
  detail is the fix that holds.
- **Letting the app's own writer invent new topics when the plan runs
  low.** The owner asked for the overseer, which reads how the films are
  doing and judges fit at no API cost. The app's writer remains the
  fallback for a topic left empty.
