# 050 — A question bank, written and checked ahead of any round

**Status:** active. Rounds now come from here first; the fact store (049)
and writing from scratch are fallbacks.

## What happened

The owner looked at rounds built on stored facts: "these are facts, not
quiz questions". Wikidata holds who, where and when; a pub quiz asks the
largest, the only, the first, the collective noun, the thing everyone
half knows. They asked for a database of proper quiz questions with
difficulty rankings, and suggested gathering them from free quiz sites
(Peacock Quizzes, Paul Cooper's blog, Nerdsip, Pub Quiz Questions HQ,
r/CasualUK).

## Why not the sites

Their terms were read before anything was taken:

- Pub Quiz Questions HQ's terms say "You must not: Republish material…
  Reproduce, duplicate or copy material".
- Peacock Quizzes offers its questions "free to use for your own pub quiz
  or events", with copyright kept. A monetised channel isn't that.
- Nerdsip and the blog state no licence (full copyright by default), and
  Reddit's terms bar scraping for commercial use.
- In the UK, database right protects taking a substantial part of a
  collection, whatever the status of single facts.

Republishing any of them would also be the reused content YouTube
demonetises, when the channel's case rests on originality (CLAUDE.md).

The facts in a question are free to use, and so is the style. The owner
chose to build our own bank in that style.

## What was decided

**The bank** (`pipeline/facts/bank.py`, tables in `facts/facts.db`).
Each question is stored once with:
- its answer and accepted alternatives, and a one-line note for the host;
- a level (1-10, on the channel's scale, set by its writer), a shape
  (superlative, only, name, origin, number, first...) and an area;
- tags for every category it fits;
- a status: checked, or rejected;
- per-channel use: a question is asked once per channel.

**Writing:**
- Batches of 25 for one category, one area and one level.
- Each category is split once into areas ("Science" becomes eighteen),
  and each batch goes to the area with fewest questions near that level.
  That keeps the bank broad without showing the writer the whole bank:
  it sees only that area's existing answers, which keeps the prompt small
  as the bank grows.
- The prompt describes classic pub-quiz shapes and bans dry lookups, with
  no example questions to copy. British English throughout.

**Checking:**
- Every question goes through the independent fact check once
  (`quiz.verify`, which lists every right answer before judging).
- A question that fails is kept, marked rejected, so it's never written
  again.
- Local checks drop:
  - repeats (the same answer, however written: "The Pacific" and
    "Pacific Ocean"; and a question about the same thing);
  - malformed questions ("What is the general term for... called?").

**Rounds:**
- A text round takes unused checked questions near its level: one per
  answer, a spread of shapes and areas, none repeating what the channel
  asked before the bank, none clashing.
- The writer then only writes the hook, intro, lead-ins, spoken answers,
  sign-off and titles, and keeps the questions word for word.
- They're already checked, so there is no second check.
- When the bank is short, the round falls back to stored facts, then to
  writing from scratch.

**Keeping it stocked:**
- The hourly background run tops up any category and level with fewer
  than 20 unused questions for a channel, shortest first.
- It writes at most 6 batches a run and no more than $1.50 a day on the
  bank, counted from the cost log's `bank_` operations.
- The Facts page shows the bank per category and has a "Write more
  questions now" button.
- `tools/manage_facts.py bank-write`, `bank-stock` and `bank-show` do the
  same from the command line.

## Measured

Three Science batches:
- **Levels:** near 2, 4 and 8 came back spread from 1 to 9.
- **Checks:** 73 of 75 passed. The two rejected were genuinely arguable:
  hurricane or typhoon; continental drift or plate tectonics.
- **Examples:** the most common gas in the atmosphere, Earth's only
  natural satellite, HMS Beagle, the coelacanth, "crepuscular", the
  Keeling Curve.
- **Cost:** about a third of a cent a question, written and checked, so
  2,000 cost about $7.
- **A round from the bank:** 1.5 cents (writing the host's lines only),
  against about 4 to 8 cents to write and check a round.

## Revised: the bank first, always

A Fiendish Geography round came back as ten obscure facts: the highest
peak of Euboea, the rock of a Philippine volcano, mostly mountains and
islands, "extremely difficult". The bank had only 2 unused Geography
questions near Fiendish, so the round fell back, all or nothing, to the
fact store, where three things went wrong at once:
- the fallback never tried to write bank questions;
- fact levels were ranks across *every* fact in a category, so Fiendish
  meant its obscure end;
- nothing kept a round of facts off one kind of thing.

Now:
- **A round the bank can't supply writes bank questions first:** three
  batches of 12, each to the category's least-stocked area, so the round
  has several areas to draw on. About 10 cents, once, and it stays in
  the bank. Facts are the last resort.
- **Fact levels span only the best-known 40%** of a category's facts;
  the rest sit at 10 (`levels.FAMOUS_SHARE`).
- **A round of facts takes at most two about one kind of thing**, read
  from the subject's description ("mountain in Greece").
- **The channel's own scale runs a notch lower**, so every level is a
  notch easier. It was Easy 2, Medium 4, Hard 5.5, Tricky 6.5, Fiendish 8,
  Impossible 9; it's now 1.5, 3, 4.5, 5.5, 6.5 and 8. It's a channel
  setting, not code.

Checked again, Fiendish Geography came from the bank: the first European
to sight the Pacific, the Gulf flags with a zigzag edge, the Challenger
Deep, Machu Picchu's rediscoverer. Six areas, 1.5 cents.

## Tried and rejected

- **Copying free quiz sites.** See above.
- **Records computed from Wikidata's figures** (largest country per
  continent, longest river, largest moon of each planet). The data
  misled:
  - historical empires counted as countries, and prehistoric lakes as
    lakes;
  - Greenland was filed under Europe (through Denmark), and Australia was
    missing from Oceania;
  - Mount Logan came out as North America's highest (it's Denali);
  - the river query timed out.

  The writer's superlatives, checked, were better.
