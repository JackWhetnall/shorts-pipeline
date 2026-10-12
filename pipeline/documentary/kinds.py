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
really asks, or would type into a search box, about the subject ("Why
can't we dig to the centre of the Earth?"), and the promise is its
answer, which turns out more surprising than they'd guess. The hook
states the question in the viewer's own words and gives the fact that
makes the obvious answer wrong.
""".strip(),
}

OUTLINE_WANT = {
    "story": """- `want`: what the person at the centre wants today, concretely (to get
  the bread to the sick house before dark; to get through the gate), and
  what happens if they fail. Each chapter puts something new in the way.
  A film about watching events go by loses people; a film about someone
  trying to get something keeps them.""",
    "explainer": """- `want`: the viewer's question in their own words, and why they should
  care: what the answer changes about something they see, use or wonder
  about. The film is a chain of questions: each chapter answers the one a
  viewer would ask next, and its answer raises the one after.""",
}

OUTLINE_START = {
    "story": """  - Start the story where the promise is. Background (childhood, how
    things got there) only where the story needs it, a minute at most at
    a time, never more than a fifth of the film, and never before the
    second minute unless the promise is about it.""",
    "explainer": """  - Build from what the viewer already knows to what they don't: the
    everyday version first, then the surprise, then the deeper why. Each
    idea is made concrete: an analogy from ordinary life, a scale they
    can feel (if the Earth were an apple...), a simple thought
    experiment, a real attempt that went wrong. A person or an event may
    carry a chapter, but the film is about the idea, not a life.
  - Name the wrong answer people assume before giving the right one: the
    gap between them is what keeps a viewer watching.""",
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
    "explainer": """Make it an explainer a curious friend would give, not a lecture:
- Talk to the viewer ("you"), about something they've seen or wondered.
  Ask the question they'd ask next, out loud, then answer it. Every
  chapter ends on the next question.
- Make every idea concrete: an analogy from ordinary life, a number at
  human scale (not "12 kilometres" alone but "taller than Everest, upside
  down"), a quick thought experiment, a real attempt and what went wrong.
- Give the wrong answer most people assume, then why it's wrong.
- One idea at a time, each built on the last; never two new terms in a
  sentence. A word they won't know is explained the moment it's used.
- Be funny where it's natural: a dry aside, an absurd comparison, a
  character in the picture reacting. Wonder over solemnity.
- Each picture shows the idea being said, as a cartoon would: a visual
  metaphor, a cutaway, a character trying it, things side by side at
  their real scale.""",
}

SCRIPT_DIRECTION = {
    "story": "One concrete, drawable moment, never a montage or a\n  diagram.",
    "explainer": ("One clear, drawable picture of the idea being said: a character doing something, a "
                  "cutaway, a visual metaphor, two things side by side at scale. Never a chart, a "
                  "labelled diagram or a montage."),
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
    "explainer": """- `momentum`: does every scene answer a question the viewer has or
  raise one they now need answered, and does the chapter end on the next
  question? Lecturing, listing facts and repeating score low.""",
}
