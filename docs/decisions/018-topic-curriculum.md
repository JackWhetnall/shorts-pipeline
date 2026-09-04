# 018 — A syllabus, not a bag of topics

**Status:** active

## What was wrong

A topic channel had `topics: ["…", "…"]` and picked one at random. Three
failures, in ascending order of seriousness.

The same topic could come up twice. Nothing put easy before hard, so a
maths channel could open on an obscure lemma while "what a percentage
actually means" went unmade. And at two videos a day a hand-written list
is gone in a fortnight.

## The instinct to generate a thousand topics up front

It is right about ordering and wrong about generation.

A thousand usable topics is 40-60k output tokens. That is not one
response, so batching is unavoidable whatever the design claims. And a
list written on day one is written with no information — by video 200 you
know which topics got discarded and why, and the remaining 800 were fixed
before any of that existed.

But ordering genuinely does have to be decided globally. Choosing "what
next" one video at a time cannot produce accessible-before-specialist,
because each local decision has no view of the arc.

## Two layers

**The outline.** One call: 20-30 units in teaching order, each with a
title, a summary, a level and a target size. This is where the pedagogy
lives.

The decisive property is that it is *reviewable*. Twenty-five unit titles
are something a person reads in two minutes and says "no, fractions
before algebra" about. A thousand topics are not; they would be approved
by scrolling, which is not approval.

**The topics.** One call per unit, written as you approach needing them.
Each call gets the whole outline (so a unit knows its place in the arc and
does not restate unit 4 in different words) and every title already used
in its own and earlier units, so it cannot repeat one.

Not the whole syllabus of titles: that prompt would grow without bound as
the channel runs, and a unit cannot repeat what has not been written yet.

## Measured

An eight-unit maths syllabus, generated for real:

```
1. [foundation ] Numbers We Already Use     fractions, percentages, negatives
2. [foundation ] Shapes and Space           angles, area, symmetry
3. [foundation ] Patterns and Puzzles       sequences, magic squares
4. [intermediate] Chance and Data           probability, averages, graphs
5. [intermediate] Algebra and Functions     variables, equations, graphing
6. [advanced   ] Structures in Mathematics  primes, modular arithmetic, sets
7. [advanced   ] Calculus and Change        rates, limits, integration
8. [specialist ] Deep Mathematical Ideas    infinity, topology, open problems
```

That is the property that was asked for. The outline cost $0.008; a unit
of topics $0.010. A full 25-unit, 1000-topic plan is 26 calls and lands
under a dollar, spread across the eighteen months it takes to use.

Within unit 1 the topics came out ordered too — what a fraction means,
equivalent fractions, fractions to decimals, what percent means — each
with a concrete angle for the script generator ("show a pizza split into
slices").

## Repetition is prevented twice

The prompt states it, and `add_topics` drops any title already in the
syllabus regardless of what the model returned. "Asked not to" is not a
guarantee, and a duplicate topic is the exact failure this whole system
exists to prevent — it is also, per the project's monetization
constraints, the visible signature of mass production.

## A discarded video returns its topic

`pending` → `used` when a video is made → `published` when it goes out.
Discarding a video puts its topic **back to pending**.

A take that did not work is not a topic that has been covered. Without
this, every discard leaves a permanent hole in the syllabus that nothing
would ever surface.

## Claiming, and why not in `fetch_seed`

`fetch_seed` is documented as free of side effects, because it is called
repeatedly while someone rerolls. So the claim happens at the top of
`generate`, the first moment a video is definitely being made.

Queueing five videos captures the same "next" topic in all five seeds. A
claim that finds its topic already taken therefore moves to the next
pending one, so five queued videos are five different videos rather than
one made five times. A deliberately chosen topic is still honoured when
it is genuinely free.

## Running out

The one failure mode of an ordered finite list is reaching the end of it.
`fetch_seed` raises with a message naming the fix rather than silently
falling back to the random list — a silent fallback would undo the whole
design without ever saying so. The remaining count and a runway in days
are on the channel dashboard and the plan page, and flagged below thirty
pending, because that warning is only useful in advance.
