# 045 — Quizzes that never run out, never clash, and say symbols right

**Status:** active. Extends 043 and 044.

## What happened

Before publishing the quiz channel daily, the owner asked four things.

1. Will chemical symbols always be pronounced right?
2. Will Hard Maths #3 and later rounds follow on by themselves when a
   category runs out?
3. Is anything stopping clashing questions ("the capital of France"
   beside "the most populous city in France") appearing together?
4. Could a round that went into a mixed long quiz reappear in, say, a
   "Science: easiest to hardest" one?

## What was decided

**Symbols by rule.** Two-letter chemical symbols in an answer, or asked
about ("the symbol Fe"), are respelled as letter names ("ay you"),
overriding whatever the writer listed. Symbols that are everyday words
(He, In, As, At, Be, No) are left alone, because respelling every "In"
in a round would wreck it. Single letters already read as letters.

Every channel also has its own pronunciation list in settings, used
whenever it speaks. A quiz round's own respellings win where both have
one.

**Rounds never run out.** When a category has nothing waiting, or the
channel has nothing waiting at all, the next round is added on demand, by
rule and for free. `fetch_seed` does this itself: it's the one side
effect it allows, because the only alternative is an error. The question
bank keeps each new round clear of everything asked before, in every
category.

**No clashes, within a round or a long video.** Two questions clash if:

- they share an answer;
- one's answer appears in the other's question;
- or they're nearly the same question (only judged when there are enough
  distinct words to judge; two short questions share their few words by
  chance).

A clashing question in a round is replaced, like one that failed the fact
check. A long quiz won't combine rounds that clash with each other.

**Long quizzes:**

- A new mode, one category from its easiest level up
  (`category:<name>`).
- A per-channel limit on how many long videos a round may appear in
  (`quiz.longform_round_reuse`, default 1). Least-reused rounds are
  picked first, and never twice in one video.

The owner's example is a round from a mixed quiz coming back once in a
single-category one. That is mild overlap, and fine at 2. YouTube's
inauthentic-content rules are about a channel whose videos look
mass-produced and alike; the more rounds are reused, the more that
describes this channel.

## Tried and rejected

- **Leaving the next round to the scheduler.** It only runs for channels
  that publish themselves, so a manual pick errored.
- **Respelling every element symbol.** Everyday words are symbols too.
