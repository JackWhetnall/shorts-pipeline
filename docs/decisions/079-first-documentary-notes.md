# 079 — The first documentary's notes: stutters, chapter cards, length, pauses, music

**Status:** active. Amends [074](074-documentaries-in-stages.md).

## What happened

The owner made History Unmystified's first film ("Lincoln and the
Gettysburg Address") and listed what was wrong with it:

> "the start of some lines are briefly stuttered at the end of the
> preceding line. also the big 'Chapter' text on screen is jarring,
> appearing too frequently. it makes the video seem disjoint. it is also
> shorter than i think the plan suggested. however i can no longer
> navigate to see the plan. also the cadence is slightly weird, leaving
> gaps in pauses that seem unnatural. it would make sense for there to be
> some, infrequent longer gaps between 'chapters' maybe. also when the
> music loops at the end it seems to fade out and then back in ... it
> leaves a gap of silence."

## What was wrong, and what changed

**Stutters.** Each scene was voiced with the next scene as context, and
the engine sometimes began saying it. The quarter-second kept after a
line's last word kept that sound: the quiz countdown's bug (decision 070)
on every line. A documentary now voices with `close=True`
(`tts.generate_voiceover`): no line is told what follows (it still hears
what came before, for its intonation), and each is cut 0.08 s after its
last word with a short fade. Shorts keep the old behaviour; the frozen
channels' tests say so.

**Chapter cards.** A chapter title came up every minute or so, with a
large "Chapter N" above it. Chapter titles on screen are now a setting
(`documentary.chapter_titles`), off by default, and never carry "Chapter
N". The chapters stay as marks in the description.

**Length.** The outline planned 9.9 minutes. The script came back as 919
words, which at the narrator's 2.4 words a second is 6.4 minutes: about
18 words a scene where 29 were wanted. The writer now gets each
chapter's word count, words per scene, and the minutes it must fill. A
chapter under 85% of its words is written again once, told how short it
was. The production page says when a script is short of its plan.

**Pauses.** Every scene was followed by the same 0.3 s, and many scenes
end mid-sentence with the next picture carrying the thought on. A pause
now follows how the words end:
- 0.45 s after a sentence;
- 0.2 s after a comma, semicolon or colon;
- 0.06 s mid-sentence;
- 1.6 s between chapters, the infrequent longer breath the owner asked
  for.

**Music.** The channel has one track, so it loops. The track ends in its
own fade and two seconds of silence, and a two-second linear crossfade
over that played as a fade to nothing and back. A documentary's bed is
now `seamless` (`longform.music_bed`): each track's quiet ends are
trimmed, and joins crossfade over five seconds at equal power. Long
quizzes keep their bed.

**Finding the plan.** Once its video was made, a film's plan entry was
used, so it dropped out of "coming up". Productions now lists every film
made, the plan page links each entry to its production, and a
documentary's video page links back to it.

## The film already made

Its script is short, and only a new script would make it longer. That
in turn means a new storyboard for the scenes that change. Making only
the video again, from the same script and stills, fixes the stutters,
pauses, chapter cards and music. It costs no voice: a documentary's video now reuses the voice
cache (`reuse=True`), so only lines whose words changed are voiced again. Before,
a remake re-voiced every line, about a thousand credits for this film.
