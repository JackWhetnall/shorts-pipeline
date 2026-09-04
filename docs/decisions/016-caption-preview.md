# 016 — Showing the captions instead of describing them

**Status:** active

## The problem with the old Look tab

Seven text boxes. Six of them held hex strings.

```
Base color        #FFFFFF
Highlight color   #FFD400
Stroke color      #000000
Stroke width      4
Font size         68
```

You could read `#FFD400` and know it was yellow-ish. You could not tell
whether a 4px outline survived a bright frame, where 68px wrapped a
four-word caption, or what any of it looked like over the footage this
channel actually uses. The only way to find out was to spend a script, a
voiceover and a render — and then read the numbers again to guess what to
change.

Font was not a setting at all. `assemble.py` tried three hardcoded paths
and took whichever existed, so every channel was identical in the one
place a viewer actually reads.

## Render the real thing, server-side

The preview is a PNG produced by `pipeline.assemble.layout_caption` and
`render_word_overlay` — the same functions that draw every caption in
every video, at the same 1080x1920, then downscaled.

The tempting alternative was CSS: a `<div>` with `text-shadow` for the
outline, styled live in the browser with no round trip. It was rejected
because it is a *different renderer*. Pillow's stroke is a dilation of
the glyph outline; `text-shadow` is four offset copies. Pillow wraps on
`textlength` at a specific font size; the browser wraps on its own
metrics with its own hinting. A preview that is 90% right about
legibility is worse than none, because it is trusted.

So each change costs an HTTP round trip and about 380 ms. Debounced at
220 ms, that is fast enough to drag a slider against, and the honesty is
worth the latency.

## Over a real frame, and the worst one

The backdrop is a frame from this install's own footage library, not a
grey card. A flat mid-grey makes every colour look fine.

Specifically it is the **brightest** frame of a twelve-clip sample,
measured over the caption band rather than the whole frame — a clip can
be bright at the top and black where the text goes. Bright footage is
what white captions fail on; previewing over a dark clip would tell you
every setting works.

Chosen deterministically (a seeded sample) and cached to one file. A
backdrop that changed between two keystrokes would make it impossible to
compare two colour choices, which is the whole task.

## Fonts by key, not by filename

`Style.font_face` stores `"impact"`, not `C:\Windows\Fonts\impact.ttf`.

The same typeface ships under different filenames across Windows versions
and Linux distributions, so a path would tie a channel to the machine it
was configured on. `core/fonts.py` holds thirteen curated faces — heavy
enough to hold a stroke, legible at a glance, near-universal on their
platform — each with several candidate filenames tried in order.
`available()` returns only faces that resolve here, so the dropdown never
offers something that would silently fall back at render time. An unknown
key still degrades to the default rather than failing a render, because
this is read minutes into a job that has already paid for a voiceover.

The list is curated rather than enumerated. This machine has 514 font
files; almost all of them are symbol sets, light weights, or scripts that
disintegrate under a 4px stroke, and a dropdown of 514 is not a choice.
