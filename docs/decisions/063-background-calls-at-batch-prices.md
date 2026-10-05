# 063 — Background calls at batch prices, and no test spends money

**Status:** active.

## What happened

The Claude bill went from about $1 a day to $4–9 a day from 28
September. The cost log (`python main.py --costs`) said where it went:

- **Most of it had no job attached.** It came from the hourly
  background run (`pipeline.facts.keep.keep_up`): processing imported
  questions (`intake_process`, about $3 a day), writing, checking and
  rating bank questions (`bank_write`, `bank_verify`, `bank_rate`, up to
  $1.50 a day and over), and filing the bank into categories
  (`category_sort`, `category_audit`). Every "keep up" run since 28
  September was the automatic one; nobody pressed a button.
- **Output, not input.** About 70% of the Claude spend was output tokens
  (thinking plus the answer), across many small calls with prompts too
  short to cache.
- **The daily caps were the throttle.** The bank writer stopped every day
  at "Today's question-bank budget ($1.50) is spent", so its spend was
  set by the cap, not by need. Easy slots fill slowly (the independent
  rater rates most questions written as easy harder than that; Ancient
  History near Easy was written for 16 times and still had no ready
  round), so the writer always has somewhere to spend.

Nobody waits on any of that. It is the textbook case for the Message
Batches API: the same requests at half the price of every token
(input, output, cache reads and writes alike), answered in minutes rather
than seconds, within a day at worst.

Separately, the test suite had no guard against real calls. The owner's
keys are set in the shell the tests run from, so a test that forgot a
mock would bill the real account silently. None did (all 1,549 passed
with the guard on), but nothing stopped the next one.

## What was decided

**Batch mode in `pipeline.llm`.** Inside `with llm.batched():` every
`call_json`/`call_vision` goes as a one-request batch and blocks until it
ends. The result is the same `Message` a direct call returns, so the
`stop_reason` checks, the truncation retry and the cost record all apply
unchanged; the cost record carries `batch: true` and half the price.

- **The hourly run is batched**, and only it. A button pressed on the
  Facts page, and anything inside a video job, still calls directly:
  someone is looking at those.
- **Independent calls wait together** (`llm.run_together`): the fact-check
  chunks of a bank batch, the rating chunks, and the category-sort
  chunks run side by side, so a run waits one batch round for them
  rather than one per chunk. Outside batch mode it runs them in order,
  exactly as before.
- **A stopped run doesn't pay twice.** Each request's batch is written to
  a journal (`cache/llm_batches.json`) keyed by a hash of the request.
  The same request made again (an import batch reclaimed after the app
  restarts) picks up the waiting batch instead of submitting another.
  A request that differs (the bank writer picks an area at random) can't
  be matched; at most one call is lost that way, and only when the app
  stops mid-wait.
- **The daily caps were halved** — imports $3 → $1.50, the bank $1.50 →
  $0.75 — so the same work is done for half the money. Leaving them
  would have spent the saving on twice the work.

**No test may reach a paid service.** An autouse fixture
(`tests/conftest.py`) replaces the Anthropic SDK constructor and refuses
any `requests` call to a host other than localhost, and sends the cost
log to a temporary file. Tests that mock either seam replace the guard;
anything else fails with `LiveCallInTest`.

**Videos made ahead are made at batch prices too.** A job the scheduler
starts (a short to keep the buffer filled, a long quiz) is marked
`ahead` and runs inside `llm.batched()`. Jobs run one at a time, so a
video started by hand would otherwise wait out another video's batch
waits: batch mode takes an `unless` check, and a made-ahead job's calls
go direct again as soon as a job that isn't made ahead is queued. A
retry pressed by hand drops the mark. Made-ahead jobs are left out of
the history the ETAs learn from, since their stages time batch waits.

**Easy slots are written for with this category's own yardstick, and
rested when writing doesn't fill them.**
- An easy batch is shown up to eight of the category's questions the
  rater judged easy enough, and eight it judged too hard, with the
  percentage it gave each. Ancient History's writer thought Julius
  Caesar (75%) was easy; the rater's line is 80% and a ten-year-old's
  guess.
- Each write records how many of its kept questions a round at that
  level could use. A slot whose last 3 writes each gave fewer than 2 is
  rested for 3 days, so the day's budget goes where it fills rounds. It
  says so in the run's progress.

**The bank writer thinks at `low` effort**, not `medium`. Its output is
checked and rated by separate calls anyway, and output, thinking
included, was most of a batch's cost. The owner chose this knowing
there's no eval to measure what it costs in quality; the fact check and
rater still stand between the writer and a round, and the review page
is where a drop would show.

## Not done, and why

- **Prompt caching for these calls.** Their system prompts are well
  under the minimum a cache will hold; there is nothing to cache.
- **A cheaper model for imports.** Not asked for; the effort change is
  the one quality trade made here.
