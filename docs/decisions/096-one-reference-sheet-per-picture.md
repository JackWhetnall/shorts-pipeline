# 096 — One reference sheet per picture

**Status:** active.

## What happened

The owner asked whether OpenAI's cached image-input price ($2/M against
$8/M) could cut the cost of drawing a film's pictures. Reference pictures
are most of that cost: in the salt film, $1.57 of the $2.25 spent on
pictures was input.

## What was tried

**Caching. It doesn't apply.** Two edits were sent back to back with the
same three references, uploaded once and sent in the same order, and the
same opening words. Both reported the full 3,072 image tokens and no
cached tokens. The edits endpoint rejects `prompt_cache_key` as an
unknown parameter. The cached price seems to belong to images inside a
conversation on the Responses API. Moving there would lose the batch
price (decision 094), so we didn't.

**One sheet. It works.** Each reference costs a fixed ~1,000 image tokens
whatever its size, so three or four references cost three or four times
as much as one. Three pictures from the salt film were drawn both ways:

- with 4 references, $0.038 became $0.016;
- with 3 references, $0.029 became $0.015;
- with 2 references, $0.023 became $0.015.

The style, the scientist's face, hair and clothes, the kitchen and the
glasses held up in all three. No panel border or number showed in any
picture.

## Decision

- **`keyframes.combine`** puts a picture's references on one 2048×1152
  sheet of numbered panels: the style sheet takes the left 58%, and the
  cast and setting sheets are stacked on the right. Sheets are kept in
  `cache/reference_sheets/`, keyed by their content, so pictures with
  the same references share one sheet.
- **The prompt changes in one way only.** It opens with `PANELS`, which
  explains that "Image N" means panel N. The rest of the prompt is
  unchanged.
- **When it applies.** `request` and `draw` take `combined`.
  - Film stills pass `documentary.combined_references`, which is on by
    default ("One reference sheet per picture" in the channel's settings).
  - A picture with a single reference is sent as it is.
  - The shorts' animation stage doesn't pass `combined`, so it is
    unchanged, and so are the frozen channels.
- **Stills already drawn are still reused.** A still's fingerprint
  describes what it shows, not how it was asked for.

## Expected saving

About 45% of a film's picture cost: roughly $1 a film at the normal
price, and about $0.50 at batch prices.

## Risk

With four references, each one gets a smaller share of the sheet. A
character close-up with four sheets is where likeness would slip first.
The keyframe check already redraws an off-model face. If faces drift,
turn the setting off for that channel.
