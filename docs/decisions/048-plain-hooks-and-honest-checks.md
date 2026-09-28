# 048 — Plain hooks on their own screen, no pronunciation coaching, checks that know the board

**Status:** active. Revises 047's hook and spare long quizzes, and 045/046's
writer-listed pronunciations.

## What happened

The owner made an Impossible General Knowledge short and reported:

- **"Mariana" sounded wrong,** apparently coached into it. The
  pronunciation guide seemed "terrible".
- **The hook was weak.** "Every fact you've hoarded is about to get
  audited" is wordy. The in-card splash, "THE AUDIT BEGINS", isn't a hook.
  Openings may be generic ("Think you know your tunes?" is good), just
  never identical.
- **The hook needs a screen of its own.** Its words should pop in one at a
  time as they're said and stay, with a lively entrance and no sound. The
  category and difficulty should then be stamped underneath, tilted, with
  perhaps a modest sound.
- **"Level 9" appeared in the title.** Levels are backend config.
- **The review flags were false.** Several blocks called correct answers
  wrong. Only "text too small" was fair.
- **The topic plan listed Tricky below Impossible.**
- **Shorts should be numbered:** `[#4] GENERAL KNOWLEDGE [EASY]` with a
  red bubble. The word "quiz" and "keep score" come off the board. The
  number is editable when making a video, defaulting to the next one not
  yet made.
- **The create page was wordy,** and the long quiz sat at the top even
  with too few rounds. "For review" made no sense: make both formats and
  review both.
- **Rounds often repeated** already-asked questions while the ladders
  were being written.

## What we found

**Pronunciation.** "Mariana" was never respelled; the log shows it sent
as written. The voice's own reading of it failed the transcript check:
- Whisper wrote "Marianna".
- Words were compared exactly, so on a seven-word line that one spelling
  dropped the match to 82%.
- The line was re-voiced three times, paid each time, and the last take
  was kept whatever it sounded like.
- That day's log had 21 such retries.

Separately, the writer's own respellings were real and poor: "Canberra"
as "KAN-bruh", "Femur" as "FEE-mer", "Van Gogh" as "van GOH". These are
words the voice already reads well.

**The checks.** The script check re-judged quiz answers with a quick
model and blocked a correct one: FORTY was called out of alphabetical
order. The answers had already passed the stronger fact check (042). The
frame check was asked whether each answer matched its question. It read
the board's running list of earlier answers as "a leftover answer", and
a question still showing while its answer was spoken as "the wrong
question".

**Duplicates.** Repeats are caught and only the failing questions are
rewritten, about one or two a round, a cent or two each. The writer is
shown this category's earlier questions and the related ones. That works
at dozens of rounds; at hundreds, the prompt grows and famous trivia
keeps coming back.

## What was decided

**Pronunciation:**
- Writer-suggested respellings are removed from the quiz writer and the
  narrated script writer.
- What remains is:
  - the channel's own list, in settings;
  - chemical symbols, respelled by rule and recomputed at voicing time,
    so rounds stored with the old respellings don't use them.
- The transcript check counts a heard word that is a spelling of an
  expected one (similarity ≥ 0.75) as that word.
- When every attempt falls short, the closest take is kept, not the last.

**Checks for quizzes:**
- The script check is told the answers are already fact-checked, and not
  to judge them or the spelling of long words.
- The frame check is told how the board works, and reports only text too
  small, cut off or overlapping to read, or anything unsuitable.

**Levels stay behind the scenes.** The writer is told the level number is
for it alone. `quiz.no_level` also strips any "Level 9" from titles and
descriptions. The topic plan lists a category's rounds by level.

**The hook:**
- 3 to 8 plain words: a challenge naming the category in everyday words.
  Familiar is fine. Clever, jargon and in-group slang are not.
- The recent list only prevents repeats. The prompt still carries no
  lines to copy.
- There's no separate splash text now. The hook's own words are the
  screen:
  - it covers the board;
  - each word springs in as it's said and stays (`spring`: up, a slight
    turn, a little overshoot), timed from the voice's word timings;
  - the category and difficulty are stamped underneath in a tilted,
    rounded label (`stamp`: dropped from large with a bounce), with a
    soft rubber-stamp thud (`sound.thud`), the only sound on this screen;
  - it clears about a second later, and the board builds from there.
- Rounds written before hooks have no hook screen.

**Numbers:**
- Each short carries a number (its `_quiz.json`), shown on the board in a
  red bubble.
- It's the one asked for when the video is made, otherwise
  `quiz.next_number`: one more than the highest number on a short not
  discarded. With #1 published and #2 and #3 waiting, the next is #4. A
  discarded #2 is remade by typing 2.
- Shorts made before this have no number.

**The create page:**
- The video to make comes first, with its number.
- The long quiz comes after it, and is offered only when one can
  actually be made: enough approved rounds at a difficulty (or rising),
  or a category's full ladder.
- Explanations became tooltips.

**Long quizzes (revising 047):**
- Both formats go to review, and the owner chooses. Spares are gone.
- Both formats of one quiz share its episode number.
- A long quiz is built only from approved shorts (queued or published),
  never from ones still waiting for review.

## Not done, and why

**A question source that doesn't depend on the writer's memory.** The
owner asked whether real question banks can be used.
- The largest free one, Open Trivia DB, holds about 5,300 verified
  questions in all, 469 of them General Knowledge (checked 28 Sep 2026).
  That's CC BY-SA and multiple-choice, and used by many channels.
- Paid APIs restrict commercial use. Game-show archives are copyrighted.
- The promising route is facts rather than questions. Wikidata has
  millions of CC0 facts, each with an ID, which would make repeats exact
  and free to rule out. How many Wikipedia languages cover a subject is a
  measured proxy for how well known it is, which fits the 1-10 scale.
- That is a substantial piece of work, left for the owner to decide.

## Tried and rejected

- **Clever hooks** (047's "belong to the category's world"). They came
  out as "Crate diggers, this round bites back": nobody scrolling knows
  what that is.
- **A splash line different from the hook.** Two messages in the first
  two seconds; the owner wanted the spoken words on screen.
- **Spare long quizzes.** "Just make them both and let me review them
  both."
