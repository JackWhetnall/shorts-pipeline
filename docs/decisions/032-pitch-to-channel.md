# 032 — A pitch becomes a whole draft channel

**Status:** active. Adds a front door beside decision 019's name-first
setup wizard, which stays for building a channel by hand.

## Why

Setting up a channel meant making a dozen decisions one screen at a
time: format, style prompt, voice, length, look, avoid list, topic plan.
Each was a blank field, and the quality of a channel is mostly decided in
them. The owner wanted to type an idea and review a complete proposal
instead.

## What was decided

`pipeline/channel_draft.py`: one Sonnet call at medium effort turns the
pitch into every decision at once, as structured output:

- three name options, summary and audience;
- `topic` vs `static_corpus` (and which source, or a custom list of
  public-domain quotes);
- style prompt, length, segments, speed and avoid list;
- three voices chosen from the account's own cached ElevenLabs list (the
  schema's enum is those ids, so an invented voice can't come back);
- a palette from the vetted set, likewise enum-bound;
- visual approach, whether it needs a news source it can't have, and up
  to five risks.

The system prompt carries this project's constraints: what stock
b-roll can't show, YouTube's reused-content rules, and the style-picker
rule that a style prompt never contains a quotable example line.

A topic-mode draft also gets a 25-topic outline from the existing
`curriculum_gen.plan_outline`. `clean()` holds everything to what the
app can use: known voices and palettes, numbers clamped (0 is a value,
not a missing one), and a quote channel with no quotes becomes a topic
channel.

`core/drafts.py` keeps drafts as files in `cache/channel_drafts/` until
accepted, so an idea can be pitched and dropped without touching the
channel list. A redraft re-runs the whole draft with the owner's note.
Accepting creates the channel with the owner's edits, the palette applied,
and the topic plan with its first topic's videos written (or the quote
list saved), then lands on the launch pipeline at "make and approve a
first video". A taken name is refused and the draft kept.

Measured on a real pitch ("science news for curious teenagers"): 91s,
$0.09 ($0.03 draft, $0.06 outline). It pivoted to evergreen "strange but
true" science because no news source exists, and said so in its risks.

## Not done

- **Per-part regenerate** (the spec's "regenerate this part"): a redraft
  with a note covers it for now.
- **A news content mode**: flagged on the draft when the pitch needs one.
- **Running the draft as a background job**: it's synchronous behind a
  disabled button, which is fine at a minute and a half.
