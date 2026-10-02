# 060 — Every quiz category has a scope, and the bank is sorted to it

**Status:** active. Refines the question bank of [050](050-question-bank.md);
revises how a rename treats a category (from the 1 Oct rename work).

## What happened

The owner made an "Ancient History" round and got Bigfoot, the Bible's
creation story, Chinese luck and a Native American Coyote legend. They had
renamed Mythology to Ancient History, and History to Modern History, and a
renamed category kept everything it had: its 184 questions and its 18
"areas" (Chinese mythology, Native American mythologies, creation
myths...). A category was only ever a name:
- its areas were written from the name alone;
- its questions were tagged by whoever wrote them, loosely (1.65
  categories per question on average);
- nothing said what it covered.

The owner: categories should follow standard pub-quiz convention,
strictly. Ancient History is Greece and Rome, perhaps Egypt; Modern
History is everything after, up to about the Second World War; Music
means popular music (theory is its own category); Sport is the rules as
well as the people, teams and competitions. They didn't want to write the
rules themselves, but wanted to be able to see and change them, somewhere
out of the way.

## What was decided

**A scope per category** (`pipeline/facts/scope.py`, a `category_scope`
table in the fact store): one sentence for what it covers and one for
what it doesn't (and which of the channel's other categories that goes
to).
- **How it's written:** once, by a model, from convention. The prompt
  gives examples, including the owner's own definitions, and says to
  leave excluded things out rather than widen a category when the
  channel has nowhere else for them. Ancient History had been written
  as "Greece, Rome, Egypt, Mesopotamia and other early cultures" before
  that rule.
- **Who can change it:** the owner, on a separate page (Topic plan →
  "What each category covers", at the bottom). Their edits are kept as
  theirs.
- **What it steers:** the category's areas and every batch of questions
  written for it.

**The bank is sorted to the scopes** (`scope.sort`), in two steps:
1. **Sort:** Haiku files each question under every category it fits, in
   batches of 40, a cent a batch. Questions it skips are asked about
   again in smaller batches. Tags for other channels' categories are left
   alone.
2. **Check:** each category's questions are then checked against that
   one definition alone (`scope.audit`), by Sonnet, about two cents per
   40.

The check is needed because the sort, juggling a dozen categories, left
the Bible and Chinese legends in Ancient History. Two cheaper versions of
the check were tried and rejected:
- **Haiku with "when in doubt, it goes":** it threw out Edwin Hubble
  from Space and Kylie Minogue from Music.
- **Haiku judging twice, removing only on two "no"s:** it still
  removed a white dwarf and an observatory from Space, and was no
  cheaper than one Sonnet check.

**When it runs:** a category whose scope is new or changed (including
after a rename, which now drops the old name's scope and areas) is sorted
before its next round is chosen (`quiz._bank_questions`) and before the
bank is stocked (`keep.stock_bank`). Saving a scope on the page sorts in
the background straight away.

**Rounds written ahead** that ask outside their category's scope are
listed on the same page (`scope.outside`), with one button to clear just
those, so they're written again from the sorted bank. They aren't cleared
automatically: that would throw away questions the owner may have
checked.

**Clear written scripts** moved from the top of the topic plan into its
"Start over" box at the bottom: it is almost never needed.

### On this channel, 2 Oct

- 12 scopes were written. Ancient History was set to the owner's words
  (Greece, Rome and Egypt: their history, people, places, gods and myths)
  rather than the model's wider one.
- 1,377 questions were sorted and checked. Ancient History went from 184
  questions (mostly other cultures' myths) to 58, all Greek, Roman or
  Egyptian.
- Folklore and other cultures' myths are now in no category, so they're
  never asked. General Knowledge rounds still draw on the whole bank.
- Pop Culture (renamed from a word-play category) holds 2 questions until
  the bank writes more to its new scope.

## What was rejected

- **Asking the owner to define every category.** They said they wouldn't;
  convention covers it, and the page is there for exceptions.
- **One sorting pass only.** It wasn't strict enough (see above).
- **Re-sorting only the renamed category's own questions.** Questions
  that belong in it were sitting in other categories: Modern History's
  "Ancient Rome and Greece" area.
