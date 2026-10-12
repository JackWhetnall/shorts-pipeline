"""
What kind of film a documentary channel makes (decision 089): a story
or an explainer.

A story follows someone who wants something today and keeps putting
things in their way (One Day In History). An explainer answers a
question a curious viewer actually has, one next question at a time.
The owner, on the first story film: "it doesn't ask or answer any
questions that a viewer might have ... why do i care?" Most of the
writers' instructions are the same for both; these are the parts that
differ, slotted into the pitch, outline, script and editor prompts.
"""

from __future__ import annotations

KINDS = ("story", "explainer")


def of(channel) -> str:
    kind = getattr(getattr(channel, "documentary", None), "kind", "story")
    return kind if kind in KINDS else "story"


PITCH = {
    "story": "",
    "explainer": """
This channel makes explainers. Every angle is a question a curious person
really asks, or would type into a search box, about the subject, framed
as a mystery with a real answer the film saves for its ending. Its title
is a specific, checkable claim or a paradox (a number, a contradiction,
a thing that shouldn't be possible), never a vague tease; "Why We Know
More About Mars Than the Ground Under Us" beats "The Hole That Changed
Everything".

The hook is not the question read out. In its first fifteen seconds it
PROVES the title is real with the strangest concrete fact or image the
film has (so nobody thinks it's bait), then gives the viewer a personal
reason to need the answer, then names the mystery the film will solve.
`open_loop` is that mystery, and the film answers it in its last
minute, not before.
""".strip(),
}

OUTLINE_WANT = {
    "story": """- `want`: what the person at the centre wants today, concretely (to get
  the bread to the sick house before dark; to get through the gate), and
  what happens if they fail. Each chapter puts something new in the way.
  A film about watching events go by loses people; a film about someone
  trying to get something keeps them.""",
    "explainer": """- `want`: the mystery, and why this viewer should care: what the answer
  changes about something they see, use or assume every day. Say both
  plainly; the cold open must deliver them.
  The film is built like a detective story about an idea:
  - the cold open (under 45 seconds): proof that the title is real (the
    strangest true fact or sight in the film, shown, not asked about),
    the stakes for the viewer, and the mystery stated as a promise;
  - the obvious answer, taken seriously, and the evidence that kills it;
  - clues: each chapter solves part of the mystery and uncovers a deeper
    problem ("but", "so", never "and then"), and ends on that problem;
  - between minutes three and six, a twist that reframes everything so
    far (the re-hook);
  - every minute or so, a callback to the mystery that shows how close
    we are, so the payoff is clearly coming, never forgotten;
  - the payoff in the final fifth: the mystery solved in one clear
    picture, then one consequence that changes how the viewer sees
    something ordinary, then the end. No summary.""",
}

OUTLINE_START = {
    "story": """  - Start the story where the promise is. Background (childhood, how
    things got there) only where the story needs it, a minute at most at
    a time, never more than a fifth of the film, and never before the
    second minute unless the promise is about it.""",
    "explainer": """  - Each idea is made concrete: an analogy from ordinary life, a scale
    they can feel (if the Earth were an apple...), a simple thought
    experiment, a real attempt that went wrong. A person or an event may
    carry a chapter, but the film is about the idea, not a life.
  - `open_loops`: the mystery last; before it, the smaller questions the
    clue chapters answer, in order. `turn`: the deeper problem each
    chapter ends on, or for the twist chapter, the reframe.""",
}

OUTLINE_SOUND = {
    "story": "",
    "explainer": "\n\nThis is an explainer: every chapter's `sound` is \"none\" unless the pictures "
                 "really are somewhere loud (a storm, the sea), and then only that chapter.",
}

SCRIPT_SHAPE = {
    "story": """Make it a story, not a tour:
- Someone wants something concrete today (to get the bread out, to get
  a message through, to get out before the gate shuts) and every
  chapter puts something in the way. The viewer should always know what
  is wanted, what stands in the way and what it costs to fail.
- Things happen: people act, argue, lie, help, run. A scene where
  someone only watches or remembers is a scene to cut.
- Every chapter ends on a turn that makes the next one necessary: a
  knock, a choice, a bad surprise, a question.
- Say the film's big idea once, at the end, if at all. Never restate the
  theme or explain what a moment means; never close on a moral.
- Warmth and wit are welcome, even in dark places: a dry aside, a human
  detail, a small joke a person there would have made.""",
    "explainer": """Make it an explainer that hooks, holds and pays off, not a lecture:
- The first three scenes prove the title, give the viewer a personal
  reason to care, and state the mystery as a promise, in that order,
  within about forty seconds. Prove, don't ask: open on the strangest
  concrete fact or sight in the film, said plainly ("In 1984, a drill in
  the Arctic pulled up rock that bent like warm toffee."), never on a
  question, a greeting, "you'd think" or "this is the story of".
- Then the obvious answer, taken seriously, and what breaks it.
- Every scene answers something the viewer is wondering, or makes them
  wonder something new. Link ideas with "but" and "so", never "and
  then". Each chapter ends on a sharper problem, a reveal or a
  cliffhanger, never the same question shape twice in a film.
- Every minute or so, bring the mystery back and show how close we are
  ("That's the first clue. The second is stranger."), so the payoff is
  clearly coming. Don't give it away early: partial answers only.
- The twist chapter reframes what came before. The last chapter solves
  the mystery in one clear picture, then one consequence that changes
  how the viewer sees something ordinary, and stops.
- Talk to the viewer ("you") about things they know. Every idea made
  concrete: an analogy from ordinary life, a number at human scale (not
  "12 kilometres" alone but "taller than Everest, upside down"), a quick
  thought experiment, a real attempt and what went wrong. One idea at a
  time; a word they won't know is explained the moment it's used.
- Be funny where it's natural: a dry aside, an absurd comparison. Wonder
  over solemnity.
- Each picture shows the idea being said: a visual metaphor, a cutaway,
  someone trying it, things side by side at their real scale.""",
}

SCRIPT_DIRECTION = {
    "story": "One concrete, drawable moment, never a montage or a\n  diagram.",
    "explainer": ("One clear, drawable picture of the idea being said: a character doing something, a "
                  "cutaway, a visual metaphor, two things side by side at scale. Never a chart, a "
                  "labelled diagram or a montage. A cutaway of a planet or an object sits in space or on "
                  "its own, never hanging over a landscape. Vary where we are and the light from scene to "
                  "scene (daylight, night, a lab, space, inside the thing); one time of day for a whole "
                  "film looks like one picture."),
}

SCRIPT_CARDS = {
    "story": "three in a film\n  at most, never a list of rules, a summary or a timeline the narration\n"
             "  already gives",
    "explainer": "about one scene in eight, for the number or comparison the explanation turns on,\n"
                 "  never a list of rules or a summary",
}

CRITIC_MOMENTUM = {
    "story": """- `momentum`: does someone want something and act, does every scene
  move the story, and does the chapter end on a turn that makes the next
  one necessary? Watching, remembering and explaining score low.""",
    "explainer": """- `momentum`: does every scene answer something the viewer is wondering
  or make them wonder something new; does the chapter end on a sharper
  problem; is the mystery kept alive without being given away? For the
  first chapter: do its first three scenes prove the title with a
  concrete fact or sight, give a reason to care and state the mystery
  (score 4 or less if any is missing)? For the last: is the mystery
  solved clearly? Lecturing, listing facts, repeating and the same
  chapter-ending question shape twice score low.""",
}
