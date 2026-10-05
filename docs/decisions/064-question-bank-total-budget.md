# 064 — The question bank has a total budget, not a daily one

**Status:** active. Replaces the daily caps in
[063](063-background-calls-at-batch-prices.md).

## What happened

Stocking the bank had two daily caps: $0.75 for writing, $1.50 for
imports. On 5 October the bank held 5,550 checked questions and 192 of
the 234 rounds Pub Quiz Buzz keeps ready, which is over six months of one
short a day. Getting there had cost $21.22 of a $40 Claude budget. That
total was shown nowhere. The Facts page said "$0.31 of $0.75 spent on it
today", which read as small every day while the job overall cost more
than half the budget.

The caps didn't hold either. Imports spent $3.11 on 2 October against
$1.50. A batch is only logged once its results come back, and filing the
bank into categories (`category_sort`, `category_audit`) wasn't under any
cap.

The owner's view: stocking is a job that needs doing for the channel to
work long term, so what has to be capped and shown is what the job costs
in total. A daily limit just hides that total.

## What was decided

- **One total limit** for everything that stocks the bank in the
  background: writing, checking and rating (`bank_*`), imports
  (`intake_*`), filing (`category_*`) and mapping categories onto
  Wikidata (`facts_*`). It covers the hourly run and the Facts page's
  buttons. Questions a video writes for itself mid-job are that video's
  cost and aren't counted. See `pipeline/facts/budget.py`.
- **The limit is set on the Facts page** and stored in
  `config/question_bank_budget.json`. Until it's set the default is
  $22.00, just above what had been spent ($21.22). The 42 rounds still
  short are mostly Easy and Medium slots, the expensive ones to fill, and
  only $3.77 of Claude credit was left. Videos come first.
- **Checked before sending.** Each write or import batch goes only if its
  expected full-price cost (`WRITE_BATCH_USD`, `IMPORT_BATCH_USD`, from
  the cost log) still fits, so the limit can't be overrun by more than
  one batch's estimate.
- **The Facts page shows the job and its cost.** That's the total spent
  against the limit, rounds ready and short, and how many days of
  publishing the ready rounds cover.

## Not done, and why

- **Lowering `SETS_AHEAD`** (3 ready rounds per category and level). One
  would still be ninety days of shorts. It's a fair trade for a smaller
  job, but it changes what the ordering can pick, and that's the
  owner's call.
