# 046 — Picture rounds, and long quizzes as two series

**Status:** active. Revises 045's round reuse setting.

## What happened

The owner asked for:

- picture rounds (celebrities, country outlines, flags, dingbats "and
  more"), reliably sourced and working well;
- a category's easiest-to-hardest long quiz made by itself when ready;
- episode numbers on long quizzes;
- answers in the long quiz's description;
- tricky words listed for narrated scripts too.

The owner also suggested Google Images, assuming it was fair use. It isn't
a safe source. Fair use is a US defence judged case by case, not a
permission, and reproducing a whole photograph in an entertainment video
is weak ground. Photos taken from search results are the likeliest route
to copyright claims and strikes on a YouTube channel.

## What was decided

**Two long-quiz series instead of a reuse setting.** The owner pointed
out that a setting allowing reuse "might cause mixup":

- a mixed series ("Quiz Night #12", with a name set in settings);
- a series per category ("Science Quiz #3", easiest to hardest).

Each uses a round at most once, so a round can be in one of each and
never more. Each series keeps its own record of rounds used and its own
episode numbers. Titles always start with the label, and the cover and
thumbnail carry it.

A category's quiz is made by itself once the category has a finished
round at every level not yet used in one of its quizzes. Only one waits
at a time, so they keep pace with the long-video slots.

**Descriptions list every answer** under "Answers (spoilers!)", with
the time each is given.

**Narrated scripts list tricky words** (names in a passage, symbols), the
same way quiz rounds do, and the voice alone uses them.

**Picture rounds** (`pipeline/pictures.py`). A quiz category can be one
of six kinds, set on the topic plan. The writer names what each question
shows, and the picture comes from a source that's safe to reuse:

| Kind | Source | Why it's safe |
|---|---|---|
| flags | flagcdn | flags are public domain |
| outlines | drawn from Natural Earth's shapes | public domain data; nothing to license or go missing. Specks and scattered archipelagos left out |
| faces, landmarks | Wikidata's image of the subject, or the article's lead image | only Commons files under public domain, CC0, CC BY or CC BY-SA, credited in the description. Wikipedia's non-free files are refused |
| paintings | the museum collections (038) | public domain works |
| dingbats | drawn from the writer's layout (words with positions, sizes, turns, strikes and real colours) | no image at all |

**Every picture is looked at before it's used:**

- **Faces** are checked as a clear photograph of one person with nothing
  naming them (captions, shirts, logos). The model doesn't identify
  people from their faces; the identity comes from the source. Asking it
  "is this Beyoncé?" failed good photographs.
- **Other pictures** are checked that they show the answer, with no text
  giving it away, and are suitable.
- **Dingbats** are solved blind by the checker. A dingbat whose every
  word can simply be read off (TOUCH over WOOD) is refused before that:
  the blind solve passed those precisely because they say the answer.

A failing question is replaced, with up to three rewrites for picture
rounds, where more fall. Rewrites never repeat a refused subject.

Picture questions share their wording by design ("Whose flag is this?"),
so repeats and clashes are judged on what's pictured. Face clues are kept
to the two hardest levels and must never answer on their own.

**Boards:**

- In shorts, an all-picture round gets a taller card with the picture
  large and the question beneath.
- Long quizzes show a thumbnail in each row, with the answer arriving
  beside it, and the picture large in the panel.

**Measured, per round written and checked (no voice):**

| Round | Cost | Outcome |
|---|---|---|
| Faces, medium | about 15¢ | two refused: a shirt reading "PORTUGAL" and an Oval Office background |
| Faces, hard | 6¢ | clean |
| Dingbats, medium | about 26¢ | 9 of 10 passed after rewrites; the last wait for review |

Dingbats are the weakest kind, so their rounds are worth reviewing
before publishing.

## Revised: dingbats removed

The owner removed dingbats entirely. A dingbat's meaning lives in its
exact shape, which a model can't reliably design or judge: even the ones
that passed were drawn clumsily ("growing pains" shrank). There's also no
free library of real dingbat images. A category previously set to
dingbats now makes ordinary rounds.

## Tried and rejected

- **Google Images.** See above.
- **Asking the checker to recognise a face.** It won't identify people,
  and it failed good pictures.
- **Trusting the blind solve alone for dingbats.** It passed puzzles that
  just spell their answer out.
- **A reuse-limit setting.** Replaced by the two series.
