# 056 — Remake as is: keep what a video was made of, make again only what's wrong

**Status:** active. Generalises the quiz remake of
[055](055-question-review-and-phone.md).

## What happened

A country picture round came out with long questions cut off at the edge
of the card. The fix was a one-line change to the board, but the only way
to get it into that video was to make the video again from scratch. That
meant a fresh script, a fresh voice, a new number and new pictures.

The owner asked for a **Remake as is** button. They saw the bigger use at
once: when a video model returns one bad animated shot, keep the script and
the voice and make only that shot again.

## What was decided

**Every finished video keeps what it was made of** (`core/remake.py`):
- **Its kit.** A job used to delete its checkpoints once it succeeded.
  These are the same files a retry resumes from: the script, the voice
  track and its timings, the footage picks, and the list of pictures made.
  They now move beside the video as `<stem>_remake/`, with the seed it was
  made from.
- **Its working folder** (`<stem>_scenes/`). This is kept if it holds
  anything paid for: animated shots and their keyframes, illustrations,
  paintings, templates. A quiz board's folder is still deleted, because it
  is as big as the video and filming it again costs nothing.
- **Its script** (`_script.json`). Before, only quiz shorts kept theirs.
- The scenes checkpoint now also records **which kind of picture the
  director chose for each segment**. A part made again is then the same
  kind of thing, and the director isn't asked again.

**A remake is a new job whose checkpoints are filled from the kit before
it starts** (`remake.prepare`), less whatever is to be made again:
- **Name:** it gets a new name in today's folder, and the same number if
  it's a quiz.
- **Voice:** the voice track is kept exactly if the script is unchanged.
  If the script changed (a quiz with questions swapped), each unchanged
  line's voice comes from the voice cache instead.
- **Footage:** the picks are kept. They are checked against the script's
  shape before use, as on a retry.
- **Pictures:** they are copied into the new video's folder. If nothing is
  picked, all of them are reused. If something is picked, a
  `remake_visuals` checkpoint lists what to keep and what to make again,
  and `visuals._remake` makes only that:
  - a picked **illustration, template, diagram or painting** is made
    again for its segment;
  - a picked **animated shot** has its clip removed from the copied
    folder, and also its keyframe if "draw its picture again too" is
    ticked. The animation stage then runs over its whole stretch as
    before. It already reuses every storyboard, keyframe and shot it
    finds in its folder, so only the removed ones are generated.
- **Quiz board:** it is always filmed again. That is how a fix to the
  board reaches a video already made.

**Starting a remake** (`remake.start`) discards the old video with the
reason "remade", which isn't one you can pick. That hands its subtopic back
for the new job to claim. If the job can't start (the channel is busy, or
the app is about to restart), the old video is put back.

**Kits are cleared** by a scheduler duty (`remake.sweep`):
- once the video has gone out;
- a week after it was discarded;
- once it is a month old;
- or with the video when it is deleted.

**Where:**
- **Remake as is** in Review, on a video's own page, and on the phone.
- The page says what will be kept: the voice exactly, line by line, or how
  many characters will be voiced again; the footage; the pictures.
- It lists each made picture, and each animated shot with its keyframe,
  to tick for making again.

The quiz remake of 055 now goes through `remake.start` with its edited
script.

## What was rejected

- **Remaking from scratch with the same script.** It re-voices, re-matches
  footage and re-animates everything, so the cost of a bad shot is the
  whole video.
- **Restoring the old job's checkpoints in place** (a "retry" of a
  finished job). The new video must not overwrite the old one's files
  while the old one is still on record. A new name and copied pictures
  keep the two apart.
- **Keeping kits forever.** An animated video's working folder can be
  tens of megabytes. Once a video has gone out, nothing will remake it.
- **Re-voicing older videos from their stitched voice track.** Videos
  made before this have no kit. A quiz short is rebuilt from its
  `_meta.txt` (055) and its lines come from the voice cache if they're
  there. Anything else is made again from Create video.
