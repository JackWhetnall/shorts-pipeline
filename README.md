# UGC book-quote pipeline

Quote → script → voiceover+captions → video, per channel, on repeat.

## Setup

```bash
pip install -r requirements.txt
# ImageMagick is needed for burned-in captions:
sudo apt-get install imagemagick
# then edit /etc/ImageMagick-6/policy.xml and comment out the line
# that blocks the "text" coder (a common ImageMagick default that
# breaks moviepy's TextClip) — see:
# https://stackoverflow.com/questions/52999027

export ANTHROPIC_API_KEY=your-key-here
```

## One-time setup per source

- **Bible**: no setup — `bible-api.com` is queried live per video.
- **Shakespeare**: build the local quote cache once:
  ```bash
  python -c "from quote_source import build_shakespeare_cache; build_shakespeare_cache()"
  ```

## Backgrounds

Drop ~10 royalty-free vertical (or croppable) video clips of books/pages
into:
```
backgrounds/bible/*.mp4
backgrounds/shakespeare/*.mp4
```
Good sources: Pexels, Pixabay, Coverr — all free for commercial use, no
attribution required (double-check each clip's license page). Keep clips
20-40s each; the pipeline loops/trims to match voiceover length.

## Run it

```bash
python main.py bible_daily --count 5
python main.py shakespeare_lines --count 5
```

Outputs land in `output/<channel>/`, each video alongside a `_meta.txt`
with the reference and full script text — handy for writing titles/
descriptions without re-watching the video.

## Adding a channel

Add an entry to `config/channels.py` with a source, voice, backgrounds
folder, style prompt, and output folder. `main.py` picks it up
automatically — no other code changes needed.

## Notes on scaling this up

- **Voices**: run `edge-tts --list-voices` to see all available voices —
  giving each channel a distinct voice helps them not feel like clones
  of each other.
- **Cost**: edge-tts is free. The only paid piece is the Claude API call
  per script (a few hundred tokens each — cheap even at volume).
- **Rate limits**: bible-api.com and edge-tts are unauthenticated public
  services — if you're generating dozens of videos in a tight loop,
  add a short `time.sleep()` between requests to stay polite.
- **Avoiding duplicate quotes**: if you want to guarantee no repeats
  across a channel's history, keep a simple `used_quotes.json` per
  channel and re-roll on a match — not built in yet, easy to add.
- **YouTube policy**: YouTube's Shorts monetization rules require videos
  to have meaningful added value beyond the raw source material —
  reused/generic backgrounds are fine, but keep the reflections genuinely
  substantive (not just quote + repeat) to stay clearly on the right
  side of the "reused content" guidelines. Worth rereading their current
  policy before you scale up channel count.
