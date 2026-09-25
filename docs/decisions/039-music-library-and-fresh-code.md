# 039 — Music fetched per channel; the app restarts onto new code; scenes wait for the hook

**Status:** active. Revises the music half of
[038](038-production-polish.md) ("never fetched automatically").

## What happened

The owner reported three things:

- A render failed at its last step with `'ChannelConfig' object has no
  attribute 'sound'`.
- The big hook text covered the first diagram. Diagrams should start
  after it.
- Music shouldn't have to be fetched by hand. Channel setup should offer
  playable, channel-appropriate options, and no two channels should share
  music.

## What was decided

### The app restarts onto new code (`core/code_freshness.py`)

The failure wasn't a bug in the new code. The app is a long-running
process started at logon, and pipeline modules are imported lazily. So
after an update, new pipeline code met old core code still in memory.

Now:

- the app fingerprints its code (file names, sizes, modification times)
  when it starts;
- while the code on disk differs, new jobs are refused with a message
  saying why, and a queued job stops before it pays for anything;
- a watcher relaunches the original command (`sys.orig_argv`, after a
  pause so the port is free) as soon as no job and no scheduler tick is
  running.

Verified live: touching one file restarted a test instance within 30
seconds. Debug runs, which have their own reloader, are left alone.

### The first scene waits for the hook text

In 038 the first scene was only asked to keep the hook's band clear. The
rule is now that nothing in the first scene may appear before the hook
text has gone. Three layers enforce it:

1. The writer is told the second, and the word, to start on.
2. Early entries are sent back to the writer in the repair round.
3. Any that remain are held back to just after the text, in their order,
   0.15 seconds apart.

### Music (`core/music_library.py`)

**Source.** Openverse (WordPress's open search of openly licensed media:
no key, indexing Jamendo, Freesound and others). Only licences that can
sit under a monetised video are used:

- CC0 and public domain;
- CC BY, with the credit added to the description.

Not NC or ND. Not SA either: syncing music to video makes an adaptation,
and SA would bind the video to the same licence.

**Suitability** comes from two cheap Haiku calls:

1. The channel becomes three mood searches, kept on the channel as
   `sound.music_moods`. The pitch draft now writes these itself.
2. The candidates' titles and tags are judged against the channel.
   Vocals, seasonal and novelty songs, dance tracks, field recordings and
   anything off-tone are dropped, and each pick gets a reason.

Narrow searches that find too little ("ethereal lo-fi magic" found one
track for Wren's) widen to broad instrumental terms and are judged
again.

**Choosing:**

- The draft page shows the picks with players, top three ticked, and the
  ticked ones are fetched when the channel is created.
- Each dashboard has a Music card: current tracks with players and
  Remove, and "Suggest tracks" with Add.
- A channel with no music gets the best three automatically at its next
  render.

**Never shared.** `music/registry.json` records each track's channel.
Suggestions never include another channel's tracks, and adding one is
refused.

**Tried and rejected:**

- **YouTube Audio Library and Pixabay Music:** no API.
- **Incompetech:** its catalogue is overused, and every video would need
  an attribution.
- **Generating music:** it isn't good enough.
- **Downloading sound-effect packs:** the synthesised effects already fit
  every channel.

**Risk that remains.** A CC-licensed track can still be registered with
Content ID by its distributor. Listening before adding, and watching the
first videos for claims, is the check.
