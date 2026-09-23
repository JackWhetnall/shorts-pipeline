# 027 — The footage-match cache never hit

**Status:** active. Reverses the prompt-caching part of decision 007's
matcher design.

## What was true

The footage matching call marked its whole system prompt cacheable:
role, rubric and the shortlisted clip descriptions. The reasoning, in
`library.py` and `llm.py`, was that the clip block is stable within one
video, so a video's later fetch rounds would read it back at a tenth of
the price.

The cost log says otherwise. Across the first month of real runs:

| | Calls | Cache written | Cache read |
|---|---|---|---|
| `footage_match` | 26 | 337,419 tokens | **0** |

Every call paid the 25% cache-write premium and none got the discount.
The block isn't stable. After a fetch round the library has grown, and
`retrieval.shortlist` runs again and returns a different ~50. A different
video shortlists differently from the start. The role and rubric on
their own are well under the minimum cacheable prefix.

`_log_cache_effect` had been reporting "cached N tokens for reuse" on
every call, which read as success. It only ever logged writes.

## What was decided

The block is no longer marked cacheable. This saves about a fifth of the
matching call's input cost, and the docstrings now say what is true.

A test asserts the matching request carries no `cache_control`, so this
doesn't drift back. The general mechanism in `llm.py` stays for callers
that might genuinely repeat a prefix. The module docstring now states the
condition for using it: the same bytes really will be sent again within
a few minutes.

## What was not done

Reordering the prompt to make caching work was considered. It would mean
putting a padded rubric first to clear the minimum size, then the
shortlist. It isn't worth it: the rubric is under a thousand tokens, and
padding it to cache it spends as much as it saves.
