# 073 — Storyboards ahead, optional to look at

**Status:** active.

## What happened

On 6 October the owner asked for a look at videos before they're made:

> "a storyboard review workflow before generation: for quiz channels,
> the questions; for other channels, the script outline plus footage
> descriptions, or images where video generation is used. The next ~3
> unmade videos can be pre-approved or edited ... regular review still
> needed when it is made - any storyboard not pre-reviewed is deemed a
> pass and therefore can be made, so as not to introduce a bottleneck"

## Decisions

**A storyboard is the entry's stored script.** The pipeline already
makes a video from a script stored on its plan entry when there is one
(script studio, decision 023; quiz rounds written ahead, 042). So the
storyboard is that script, written early. For a narrated channel it's
each line with its shot brief, the description the footage is matched
against. For a quiz it's the round's questions. Writing it ahead costs
nothing extra, since the video would write it anyway, and an edit
carries straight into the video.

**The next three are pinned.** A channel choosing at random would
otherwise show a different "next three" each time it was looked at. The
next three are worked out by running the ordering forward
(`storyboard.upcoming`) and kept on the plan (`coming_up`). The ordering
honours that list right after "Make next", so the three looked at are
the three made, in that order. They're what the ordering would have
picked anyway; pinning only fixes the draw.

**Written ahead hourly, at batch prices**, for channels that publish
(`storyboard.keep_up`, a scheduler duty). An entry a video is being made
from right now is left alone. "Write the rest now" does it at once.

**Approval is a mark, never a gate.** Approved and never-looked-at are
both made next. The owner can:

- approve a storyboard;
- edit its lines and shot briefs, which saves and approves it;
- write it again, with a note for a narrated one. A quiz gets another
  ready round, and the old one's questions go back to the bank unasked.

A quiz is approved when every question is fine. The existing question
review (055, 071) is where they're checked one by one; it's linked from
each storyboard, and "They're all fine" passes them all. New words
(`curriculum.set_script`) clear an approval, since they haven't been
looked at.

**Pictures for animated channels aren't drawn ahead.** An animated
film's shots are cut on the real voice's word timings
(`pipeline.animation.storyboard`), so its pictures can only be drawn
after the voiceover exists. Drawing them ahead would mean voicing ahead.
That spends the voice allowance on videos that might be rewritten, and
it splits the job pipeline in two. The shot briefs are shown instead:
they're what the director and the picture prompts are built from, so
editing a brief changes the picture. If the briefs prove not enough to
judge by, voicing and boarding ahead is the next step.

**One cost.** A script written ahead isn't rewritten by the originality
check (`_originality_gate` only rewrites a script it wrote itself); a
close one is flagged at review instead, as for any stored script.
