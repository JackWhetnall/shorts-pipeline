# 043 — Plans that grow safely, quiz memory for years, a fixed difficulty scale

**Status:** active. Extends 041 and 042.

## What happened

With publishing about to start on three channels, the owner raised five
problems.

1. **The review queue showed quiz board files.** A quiz's board clip sat
   beside the finished video as `<stem>_TEMP_board.mp4`, and every
   listing counted any mp4 as a video. A narrated channel's scene clips
   (`<stem>_scenes/`) did the same, and none of them were ever deleted.
2. **A daily quiz needs years of questions.** General Knowledge will have
   many Easy rounds, each needing new questions, ideally including a
   "General Knowledge 2" and a "Snakes" topic that stays clear of what
   "Biology" asked.
3. **Plans had no way to grow.** The only route was replacing the
   outline, and the owner feared losing written scripts. They wanted to
   add topics by hand or generated, from the plan page, with a topic
   count in settings that behaves sensibly.
4. **Difficulty was only a label.** Would adding "Tricky" between Hard
   and Fiendish stretch every level?
5. **Hard already felt hard.**

## What was decided

**A render's working files are its own and temporary.**

- Every intermediate clip, including the quiz board, goes in the video's
  `_scenes` folder.
- That folder is deleted once the finished video is written. It is kept
  if assembly fails, because a retry reuses it.
- `gallery.videos_in` is the one definition of "a video in this folder".
  It skips working files, and every listing uses it.
- The leftovers already on disk were deleted.

**Each channel has a question bank that is never pruned**
(`config/question_banks/<key>.json`). It is seeded from the originality
history, which keeps only 200 videos. When a round is written:

- The writer sees this category's earlier questions, up to 300. That is
  about 6k tokens, a few cents a round.
- It also sees other categories' questions that share a keyword with this
  category, up to 80, so "Snakes" sees Biology's snake questions.
- Categories are matched without their number: "General Knowledge 2" is
  General Knowledge.
- A free local check compares every new question against the whole bank,
  in every category. A question with the same answer and overlapping
  words, or nearly the same words, is replaced, like an answer the fact
  check didn't pass.
- This scales past what any prompt could hold. The prompt steers the
  writer; the local check enforces.

**Difficulty is a level on one fixed 1-10 scale, and the label is only
its name.** The scale is described to the writer in terms of how many
adults would know the answer.

- Familiar names have fixed levels: Easy 2, Medium 4, Hard 5.5, Tricky
  6.5, Very hard 7, Fiendish 8, Impossible 9.5. Hard is a little lower
  than before, since the owner found it hard.
- A familiar name keeps its level if that keeps the order rising.
  Anything else sits evenly between its neighbours, or takes a level
  given as "Tricky (7)".
- Adding a level therefore never moves the others.
- A new level is added to every existing round of every category at once
  (`sync_ladders`).
- Round 2 onwards is shown the same level from the round before, so
  rounds don't drift.

**Plans grow by adding, and only by adding.**

- New functions `add_topic`, `rename_topic`, `remove_topic` (empty topics
  only) and `set_topic_count` (placeholders up; empty topics off the end
  down). None of them touches a subtopic, a script or the record of what
  was made.
- The plan page can:
  - add a topic by hand, with its videos typed in, written for it, or
    left empty;
  - generate N more topics that continue the plan (`extend_outline`) and
    fill them;
  - add videos to a topic by hand;
  - name, fill or remove an empty topic.
- Settings has "Topics in its plan". Unnamed placeholders are never
  written about until named.
- For a quiz, a topic is a category and its rounds come by rule.
- There is still no scheduled pre-generation of topics. The scheduler
  already tops up a running plan (a round for a quiz, the next topic for
  a narrated channel), and rounds are unlimited.

## Capacity note

At the measured characters per video (Minute Pastor about 530, Wren's
about 765, the quiz about 1,200-1,470), daily videos on all three
channels need about 75,000 ElevenLabs characters a month. Starter
includes 30,000. Either the plan grows, or the cadence fits the
allowance. The publishing plan's estimate shows this per channel.

## Tried and rejected

- **Pre-writing hundreds of subtopics now.** For a quiz they are free and
  unlimited by rule. For a narrated channel, writing ahead of need spends
  money on videos that may never be made.
- **Embedding-based similarity for repeats.** A local keyword-and-answer
  check catches rewordings of the same fact at no cost. Embeddings would
  add a model call per question, or a new dependency.
- **Stretching the labels evenly across the scale.** That is exactly what
  would have moved every level when one was added.
