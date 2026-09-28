# 049 — A fact store from Wikidata, ahead of any script

**Status:** active.

## What happened

The owner asked for a facts-first question source (048's open question):

- **Facts before scripts.** Gathered separately from any script: a huge,
  consistent, topic-spanning set that can be pulled, updated, expanded
  and categorised.
- **One fact, many categories.** A fact that fits several categories is
  valid for each, but ideally not used twice.
- **New categories tag what's there.** A new category ("Harry Potter")
  tags the relevant facts already stored, and gathers new ones.
- **Built to be eaten through.** It will be used up quickly, so it has to
  be expansive and adaptable.

## What was decided

**Store** (`pipeline/facts/store.py`, `facts/facts.db`, SQLite, not in
git).
- **Entities:** the Wikidata items the store knows, with their fame (how
  many Wikipedias cover them).
- **Facts:** each is subject + property + value, stored once. A fact
  Wikidata stops stating is retired, never deleted.
- **Categories and members:** a category is defined by its members (the
  entities in it). A fact belongs to every category its subject is in, so
  it's valid for all of them and stored once.
- **Usage:** recorded per channel. A fact is asked once per channel,
  whichever category it came through. One stated both ways ("A was
  followed by B", "B follows A") counts as one fact.

**What counts as a fact** (`properties.py`):
- About 60 Wikidata properties whose values are settled: capitals,
  authors, discoverers, symbols, founders, parents, sequels. Nothing that
  changes with time (office holders, populations, rosters, records).
- **Forwards:** a fact is asked for its value only when the subject has
  exactly one value. Bolivia's two capitals can't be.
- **Backwards:** asked for its subject only where the property allows it
  and no other subject shares the value.
- **Dates:** kept only when stated to the year, so "900", meant as a
  century, is dropped.
- **Unusable values:** unknown values and values with no English label
  are dropped.

**Difficulty is measured** (`levels.py`):
- Fame is how often people read about a thing: a year of English
  Wikipedia views (Wikimedia's pageviews API), measured for each member
  as it's tagged. Earth gets 3.5 million, Mars 1.3 million, a numbered
  asteroid a few thousand.
- Counting Wikipedias was tried first and misled. Bots have written
  asteroids into dozens of them, so "221 Eos orbits the Sun" came out as
  easy as anything.
- A fact's hardness is mostly the fame of the thing its question names,
  partly its answer's, plus the property's own adjustment (a capital is
  easier than its country's fame suggests; a discoverer harder). It's
  worked out when a round is picked, from the latest views.
- **Not asked at all:**
  - things read fewer than about 15,000 times a year (their facts aren't
    even fetched);
  - an answer most of a property's facts in the category share, which
    gives itself away (nearly every asteroid orbits the Sun);
  - sequences of numbered things ("19 Fortuna came after 18
    Melpomene");
  - an answer that shares the name asked about ("Paranal Observatory" is
    on "Cerro Paranal");
  - a parent, home town or membership nobody has heard of (these
    properties need a well-known answer), and anything about deaths.
- Views are fetched fifty articles at a time from Wikipedia's API.
  Asking an article at a time ran into Wikimedia's rate limits, and one
  category's measuring took hours.
- Levels are ranks within a category, spread over the 1-10 scale. In
  Harry Potter, Easy is what every fan knows; general knowledge ranks
  every fact together.
- A round at a level draws unused facts near it, one per subject and per
  answer, with a spread of properties when the category has them.

**Categories are mapped once** (`categories.py`):
- A model proposes the sets that make up a category, by name with a
  guessed Wikidata ID. Each set is either:
  - instances of classes, optionally narrowed ("human" with occupation
    "physicist"); or
  - items linked to anchors (the Harry Potter series, its films, its
    universe).
- Every ID is checked against Wikidata's own label, or searched for by
  name. A set that finds nothing is skipped for good when first
  harvested. Checking at definition time cost a minute a set on the
  biggest classes.
- About a cent a category. General knowledge needs no mapping: it's
  every fact.

**Harvesting** (`harvest.py`):
- A category's sets are pulled a page at a time, most famous first, so
  each harvest goes deeper and the store grows as it's used.
- Every member is tagged. One already in the store counts for the new
  category at once, without being fetched again.
- Facts are pulled for members not yet fetched. Entities not pulled for
  half a year are pulled again.

**Two query engines** (`wikidata.py`):
- Wikidata's own query service is the source.
- It can't rank a class of hundreds of thousands by fame: films,
  mountains and stars timed out at 60 seconds, and timeouts spent the
  rate allowance.
- For that one step, QLever (a public engine over the Wikidata dump, from
  the University of Freiburg) is asked first. It ranks stars, galaxies,
  planets or comets in one to two seconds.
- It has quirks. It answers nothing at all to the joined subclass path
  `P31/P279*` or to a filter on fame, so its query uses two steps and the
  floor is applied afterwards.
- Its answer is used only if it's sorted by fame with genuinely famous
  things at the top: under load it was seen returning films in ten
  Wikipedias first.
- Failing that, Wikidata is asked with one level of subclasses, then
  direct members at a higher fame floor. The method that worked is kept
  per set, and a set no method can rank is skipped for good.

**Keeping it stocked** (`keep.py`). Every scheduler tick, at most
hourly, in the background:
- any quiz channel category the store doesn't know is mapped and
  harvested;
- any category short of unused facts near one of the channel's levels
  (fewer than 40, four rounds' worth) is harvested a page deeper;
- old facts are refreshed.

Nothing is fetched while a round waits.

**Rounds** (`pipeline/quiz.py`):
- A text round asks the store for unused facts near its level, six more
  than it needs.
- The writer builds each question on one listed fact, naming it. Its
  answer must be that fact's answer, which is checked. One that isn't is
  replaced from fresh facts.
- The writer no longer needs to be shown every question the channel has
  asked, because the facts are unused.
- The independent fact check still runs.
- The facts used are recorded for the channel.
- When the store can't supply a round (a category it can't map, like
  wordplay), the round is written as before, from the writer's knowledge.
- Picture rounds are unchanged.

**The Facts page** (sidebar) shows each category's facts, how many each
quiz channel hasn't used, and where it's short. It can add a category,
go deeper and stock everything now. `tools/manage_facts.py` does the same
from the command line.

## Measured

Space, first page (from a trial store):
- 12 sets and 7,165 things tagged; facts fetched in about 7 minutes.
- Views measured in 2 minutes.
- 501 things are read enough to ask about, giving about 620 askable
  facts.
- A real Medium round was built 10 of 10 on stored facts and passed the
  fact check, for 4 cents (writing and checking).
- The fact check caught one incomplete Wikidata fact: a moon credited to
  one of its two discoverers.

## Known limit

Wikidata holds who, where and when (discoverers, makers, capitals,
authors, dates), not superlatives or descriptions ("the largest planet",
"the planet with the Great Red Spot"). So a category's easiest stored
facts can be harder than a pub's easy questions: Space's Medium round
asked where astronauts were born. Levels are ranks within a category, so
this eases as a category deepens, but the easy end of fact-poor
categories may want the writer's own well-known questions mixed in (still
fact-checked and kept from repeating). Not done; for the owner to decide.

## Tried and rejected

- **Existing question banks.** Open Trivia DB is the largest free one:
  about 5,300 verified questions in all, 469 of them General Knowledge,
  multiple-choice and widely used by other channels. Paid APIs restrict
  commercial use. Game-show archives are copyrighted.
- **QLever alone.** It's fast, but under load it returned wrong answers
  with no error.
- **One level of subclasses on Wikidata.** Earth is an "inner planet",
  a kind of "terrestrial planet", a kind of "planet": one level found
  exoplanets and missed every planet in the solar system.
- **Raising the fame floor on Wikidata until a big class sorted.** The
  cost is scanning the class, not sorting it, so no floor helped, and
  each attempt spent a minute and the rate allowance.
