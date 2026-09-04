# 019 — Creating a channel

**Status:** active — supersedes the single create form

## What the old form produced

A real channel, created through the UI, came out like this:

```json
{
  "channel_display_name": "Wren's Guide to Witchcraft",
  "content_mode": "static_corpus",
  "source": "shakespeare",
  "style_prompt": "...short, interesting but poignant analysis of various
                   shakespeare quotes...",
  "voice": "a",
  "output_dir": "output/"
}
```

Every content field is a copy of a different channel's, the voice is a
single letter, and the output directory is the folder every channel writes
into — so its gallery listed every other channel's videos as its own. All
of it passed `validate()`.

None of that was the user's mistake. It is what the form made likely.

## The three faults

**It asked for plumbing.** "Output directory" was a required text box
pre-filled with `'output/' ~ channel.key` — and on the new-channel page
the key is empty at render time, so the box read literally `output/`.
Submitting it unchanged is the bug above. The value is derived from the
key and there was never a reason to type it.

**It asked for things you cannot know yet.** "ElevenLabs voice ID" is a
required field wanting twenty opaque characters that live on another
page. Faced with a required field and no value, you type something to get
past it. `validate()` only checked non-empty, so `"a"` was accepted and
would have failed minutes into a render, after a script had been paid
for.

**Its vocabulary explained nothing.** "Fixed source (a quote is fetched
and read aloud)" offered `bible` and `shakespeare` and no answer to "what
if I want something else". Nor did it say what the two had in common —
that they are public domain, which is the whole reason a channel can read
them aloud.

## Create on a name, then a wizard

`/channels/new` now asks for a name and derives the key. The channel is
created immediately in an incomplete state, and the two content steps are
prepended to the setup wizard that already existed:

```
content → voice → logo → email → socials → patreon → merch … 
```

This works because an incomplete channel was **already** a state the app
understood — the home page has a "Setting up" section and a checklist for
exactly that. The old form's insistence on completeness before creation
was fighting its own architecture.

What stops an incomplete channel reaching a render is
`channel_progress`, which now runs `validate()` and refuses to generate
while it fails — reporting the same sentence the pipeline would have
failed with, on the dashboard, with a link to the step that fixes it.

Settings saves no longer refuse either. Refusing made a half-set-up
channel uneditable: you could not fix its style prompt until it also had
a voice and a source. It protected nothing, because generation was gated
anyway.

## One question instead of two fields

`content_mode` and `source` are two stored fields but one decision, so
they are asked as one:

- **Written from scratch, on a topic** — leads to the topic plan
  ([018](018-topic-curriculum.md)).
- **Your own list of quotes** — the answer to "what if I want something
  else".
- **A built-in library** — Bible or Shakespeare, and the page says these
  two are here *because they are public domain*.

Radio buttons with a sentence each, not a `<select>`. The meaning has to
be readable before the option is picked, and a dropdown has nowhere to
put that.

## The extensible source is your own text

`SOURCES` was a dict of two Python functions. A third meant writing code,
so the practical answer to "something else" was no.

Both built-ins do real work that does not generalise — one calls an API
per video, the other reduces Gutenberg texts to quotable sentences
offline. What generalises is supplying the text: `core.corpus` reads
`config/corpora/<key>.txt`, one entry per line, attribution after a dash
or a bar. Plain text, so it can be edited anywhere and pasted from
anywhere.

Splitting takes the **last** separator, so `Well-being is the goal -
Aristotle` keeps its hyphen. A quote with no attribution falls back to
the channel name, because the reference is what the filename is built
from and readable filenames are how a repeat stays visible.

Licensing is stated at the point of pasting: this text is read aloud
verbatim, the built-ins are public domain, anything you paste is yours to
check — the same position the footage library already takes.

## Voices are chosen, not typed

The voice step lists the premade voices with ElevenLabs' own preview
audio, which costs nothing to play and no TTS quota. Pasting an ID is
still possible, behind a disclosure, for a cloned voice. If the voice list
cannot be fetched — a key restricted to text-to-speech can synthesize but
not list — the step says so and still accepts an ID rather than becoming
a dead end.

`validate()` now checks the shape of a voice ID (20 alphanumerics). It is
the difference between a mistake caught on the setup page and one caught
after paying for a script.

## Settings summarises what setup decides

The settings page used to define the same content choice again, in worse
words. It now shows what the channel is set to and links to the step:

> Voice — **Adam - Dominant, Firm** at 1.0× speed. *Change the voice →*
>
> Where the words come from — **The Bible (King James Version)**.
> *Change what this channel makes →*

Leaving the Content tab as the four things actually edited often: display
name, outro subtext, style prompt, avoid-imagery.

## Guards on changing a live channel

Applying a voice from the Voice Lab now confirms, and names the channel —
it is a dropdown of names with no other context, and applying to the
wrong one is silent. On a channel with published videos the wording says
so: its voice is part of what its audience already recognises. Saving
settings on a published channel confirms for the same reason, and because
one form carries every tab.
