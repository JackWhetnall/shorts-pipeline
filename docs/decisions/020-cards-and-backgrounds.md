# 020 — Title cards, and a picture behind them

**Status:** active

## What every card looked like

A flat rectangle. The outro card in every video of every channel was
`Image.new("RGBA", (W, H), style.outro_bg_color)` with text on it — the
same shape, the same treatment, the same everything, forever.

That is the most obviously templated thing a viewer sees, and this
project's whole monetization case rests on not looking mass-produced.

## A picture, chosen once

`core/backgrounds.py`: search Pexels and Pixabay's **photo** endpoints,
pick one, and it sits behind the title and outro cards instead of the
flat colour. Chosen once per channel, so it costs nothing per video.

Same two sites the footage library already uses, same keys, same
licences — and the licence is recorded in `background.json` the way a
clip's is, because the same question gets asked at monetization time. A
source that is neither of them is recorded as unconfirmed rather than
assumed free.

Search returns preview URLs the browser loads directly. Nothing is
downloaded until a picture is chosen, so browsing costs one API call and
no disk.

## Two edits, not a photo editor

Blur and dim.

A background has one job: to be behind text without competing with it.
Blur removes the detail that fights the letterforms, dim buys contrast.
Crops, filters and overlays are a different product.

Both derive from the stored original, never from the last edited version.
Blur applied twice is not the same as more blur applied once, so
re-deriving is what makes moving a slider *back* actually undo something.
The original is kept beside the result for the same reason — a channel
should never be one bad blur away from choosing a picture again.

Pictures are covered to 1080x1920, not fitted. A letterboxed background
is worse than a cropped one, and a photograph's subject is almost always
in the middle.

## The title card is off by default

`assemble.py` used to carry this comment:

> There is deliberately no title card: for short-form, viewers should land
> straight in the content.

That was right, and it is still the default. Seconds before the content
starts are watch time spent on nothing, and the scroll is decided in the
first of them.

But it is not right for every channel. One whose videos are a series
someone works through — a syllabus, in this project's terms — wants the
viewer oriented, and that is a different trade rather than a mistake. So
it became a setting, with the reasoning stated next to the checkbox
instead of buried in a comment where only the next programmer sees it.

The card shows the channel name above and the video's own title below,
both with a stroke, because the card may be sitting on a photograph and a
colour that reads on flat black can vanish on one.

It uses the **seed's** title — the subtopic name, or the quote's
reference — rather than the generated packaging title. It is what the
video is about, it is stable, and it is what the plan calls this video.

## The bug this could have caused

The card is inserted in front of the narration, so the audio needs
matching silence in front of it. Without that, every caption in the video
is out by the length of the card — and that presents as a captions bug,
not a title card one, which is a much worse afternoon.

There is a slow test that renders a real video with a card and asserts
the audio and video durations still match.
