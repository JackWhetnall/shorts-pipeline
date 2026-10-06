# 071 — What the owner says about a question is used

**Status:** active. Extends [055](055-question-review-and-phone.md).

## What happened

On 6 October the owner asked:

> "do quiz question discard reasons ever get used?"

They didn't. A reason was stored on the rejected question and nothing
read it. The owner also pointed out that some questions were thrown out
for the wrong reason: one in the wrong category could simply move, and
some "would be valid if reworded (eg remove 'called French Polynesia'
from a question whose answer is France)".

## Decisions

**Two more verdicts on the review page**, under "Wrong, needs rewording,
or the wrong category":

- **Move it** to another of the channel's categories. The question is
  filed there in the bank, freed for a round of that category, and
  swapped out of this one. The bank's sorting is model-driven and runs
  again whenever a scope changes, so the owner's ruling needs to outlast
  it. A table, `question_not_in`, records it, and a trigger on
  `question_tags` ignores any insert it forbids. A trigger was chosen over
  a check in each of the three filing paths (sort, refile, file new),
  because a fourth path would forget.
- **Reword** with a note. The note and the question go to a small call
  (under a cent). The result goes through the same fact check as any
  question; if it fails, the old wording stays and the page says why.
  If it passes, it replaces the question in the bank and in the round,
  with fresh host lines, and is marked fine: the owner has looked at it.

**A reason for taking one out is shown to the writer.** When the bank
writes more questions for a category, the owner's last twelve
rejections there, with their reasons, are listed: "write nothing with
the same fault". A rejection with no reason given adds nothing, so it
isn't shown.

Picture questions are left out of both: their question is the picture,
and their category is their round.
