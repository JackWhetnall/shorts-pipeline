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

KINDS = ("story", "explainer", "working_day", "expose")
LABELS = {"story": "Story", "explainer": "Explainer", "working_day": "Working day", "expose": "Exposé"}


def of(channel) -> str:
    kind = getattr(getattr(channel, "documentary", None), "kind", "story")
    return kind if kind in KINDS else "story"


def family(kind: str) -> str:
    """"story" or "explainer": a working day and an exposé (decision 122)
    are explainers with shapes of their own, so they're fact-checked,
    held to an explainer's opening and given its pictures."""
    return "story" if kind not in KINDS or kind == "story" else "explainer"


# What each kind of channel can make well (decision 118), for whoever
# chooses its films: the plan's writer (pipeline.curriculum_gen) and the
# overseer (core.overseer topics). The owner, on 19 Oct: a film about how
# mirrors flip an image can't be trusted to its pictures, and "visual
# errors like this kill the validity and trustworthiness of the whole
# channel".
TOPIC_FIT = {
    "explainer": """
What this channel can make well, and what it can't (the owner's rules):
- The answer works by ear. Someone listening with their eyes shut can
  follow every step: a cause, a history, how a body, a planet or an
  everyday thing behaves, made concrete with comparisons from ordinary
  life. "Why is the sea salty but rivers aren't?" and "Why can't you
  tickle yourself?" are the kind.
- The pictures only illustrate. They're drawn by an image model that
  can't be trusted with exact shapes, positions, angles, directions,
  stages, layouts, counts, letters, text, maps or diagrams, so a subject
  is out if explaining it means showing one of those: how a mirror flips
  an image, a sign's shape and colours changing stage by stage, where a
  pen cap lodges in a throat, how toast turns as it falls, the Earth's
  tilt through the seasons, the two bulges of the tides, which letters
  sit where on a keyboard.
- The question has an honest answer the film can give in full, and the
  title never contradicts it ("The Pen Cap Hole That Isn't There to Save
  Your Life" was wrong: it is there to, by making choking survivable).
- Plenty of people know the thing and have wondered, and the true answer
  surprises them.
""".strip(),
    "story": """
What this channel can make well, and what it can't:
- A day someone lived through, told by voice: what they wanted and what
  stood in their way. Someone listening with their eyes shut follows it.
- The pictures only illustrate people and places. They're drawn by an
  image model that can't be trusted with exact maps, documents, text,
  insignia, how a machine works, or a precise sequence of events, so a
  story that turns on showing one of those is out.
- The title promises what the film delivers.
""".strip(),
    "working_day": """
What this channel can make well, and what it can't (the owner's rules):
- One ordinary job or role from the past, explained across one working
  day: what they actually did from waking to sleeping, how, for what
  pay, and how we know. A pirate, a Roman soldier, a caveman are the kind.
  Prefer the roles and eras other channels haven't done to death (a
  lighthouse keeper, a falconer, a rat-catcher, a samurai in peacetime,
  a tomb-builder at Deir el-Medina, a Viking trader, a telephone
  operator); the crowded three (Roman soldier, pirate, medieval peasant)
  only with an angle nobody else has.
- There's real evidence for the day: letters, rotas, accounts, diaries,
  laws, digs or a careful reconstruction, so the film can say how we
  know. A role nobody recorded is out.
- The day works by ear: tasks, tools, food, pay, danger and boredom, all
  said, with numbers at human scale. The pictures only illustrate someone
  at work. They're drawn by an image model that can't be trusted with
  exact layouts, maps, text, insignia, rigging or how a machine works, so
  a role is out if explaining it means showing one of those.
- The true day surprises: most of it isn't what films show. The title
  promises what the film delivers.
- The job, not its cruelty: no role whose day is mainly killing,
  torture or punishment.
""".strip(),
    "expose": """
What this channel can make well, and what it can't (the owner's rules):
- One naughty, scandalous corner of life in the past that a bored
  eighteen-year-old would click on sight and then stay for because the
  story is genuinely good: bathing and bathhouses, what people wore and
  didn't, seduction and flirtation, famous lovers and scandals, beauty,
  scandalous inventions (the bikini, the corset, the waltz). "How a
  medieval princess was bathed and dressed for her wedding" and "the
  invention of the bikini" are the kind.
- Suggestive, never explicit. Out: sex acts and how-to, sex work and
  brothels, fetishes, sex toys, and anything about anyone under
  eighteen. Everyone a film is about, and everyone it shows, is an
  adult. YouTube age-restricts nudity, lingerie, sexual poses and
  framing that centres on breasts or bottoms, and limits ads on vulgar
  words, so the tease is the glamour, the flirtation and the scandal.
- The title teases: a scandal, a seduction, an outrage or a number,
  innuendo welcome, never a vulgar word, "sexy", "18+", "naked" or
  emojis.
- It works by ear. The pictures illustrate the film's good-looking cast
  in the moment; they can't be trusted with how a garment is built,
  text or diagrams, so a subject is out if explaining it means showing
  one.
- There are receipts: household accounts, letters, sermons, court cases,
  newspapers' outrage, surviving garments. Busting a myth is welcome.
""".strip(),
}

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

Every angle works by ear: its proof, its clues and its answer are
things the narration can say, never something the viewer has to see
drawn exactly (a shape, a position, a direction, stages of a design),
since the pictures only illustrate. And the title's claim must be true
by the film's own answer: never a title the answer contradicts or has to
walk back.
""".strip(),
    "working_day": """
This channel explains one job from the past by walking through its
working day. Every angle is the question people really ask about the
role ("What did pirates actually do all day?"), answered with evidence.
Dozens of channels use that exact title: its title is instead the most
surprising true claim about the day, with the role named ("Roman
Soldiers Dug More Than They Fought"), specific and checkable, never a
vague tease.

The hook: in its first fifteen seconds it proves the title with the
strangest true detail of the day, then says what everyone assumes
instead, then promises the whole shift, from the first bell to lights
out. `open_loop` is the job's biggest surprise, saved for the middle of
the film.

Every angle works by ear: its tasks, numbers and evidence are things
the narration can say, never something the viewer has to see drawn
exactly (a layout, a map, how a machine works).
""".strip(),
    "expose": """
This channel tells history's naughty bits: what polite history leaves in
the bottom drawer. The test for every angle: would a bored
eighteen-year-old click it on sight, and would the film keep him because
the story is genuinely surprising? Every angle is something people are
curious about and rarely hear the truth of (how people bathed together,
what they wore and didn't, how a bride was got ready, the seduction that
caused a scandal), framed as the polite version against what really
happened. Its title teases: a scandal, a seduction, an outrage or a
number, with innuendo where it's funny ("The Swimsuit So Small It Was
Sold in a Matchbox"), never a vulgar word, "sexy", "18+", "naked" or
emojis, and never a promise the film doesn't keep.

The thumbnail is one of the film's good-looking characters, close and
confident (a smirk, a wink, a scandalised glance), with the thing at the
centre of the fuss; framed on the face and figure, never on breasts or
bottoms, which YouTube age-restricts.

The hook: in its first fifteen seconds it proves the title with the most
eyebrow-raising true detail the film has, said with a smirk, then the
polite version, then the promise of what happened behind the closed
door. `open_loop` is what the film reveals in its last minute.

Suggestive, never explicit: no sex acts, and nobody under eighteen in
anything about bodies, undressing or romance.
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
    strangest true fact in the film, said plainly, not asked about),
    the stakes for the viewer, and the mystery stated as a promise;
  - the obvious answer, taken seriously, and the evidence that kills it;
  - clues: each chapter solves part of the mystery and uncovers a deeper
    problem ("but", "so", never "and then"), and ends on that problem;
  - between minutes three and six, a twist that reframes everything so
    far (the re-hook);
  - every minute or so, a callback to the mystery that shows how close
    we are, so the payoff is clearly coming, never forgotten;
  - the payoff in the final fifth: the mystery solved in plain words,
    then one consequence that changes how the viewer sees something
    ordinary, then the end. No summary.
  Every step works by ear: the narration carries the whole explanation,
  and no chapter depends on a picture showing an exact shape, position,
  direction, count or stage.""",
    "working_day": """- `want`: what this day shows about the job that films get wrong, and
  why the viewer should care (it was a real person's job, and it explains
  something about how things are now). Say both plainly; the cold open
  must deliver them.
  The film is built like a shift:
  - the cold open (under 45 seconds): the strangest true detail of the
    day said plainly, what everyone assumes instead, and the promise of
    the whole shift;
  - the job advert, in a minute: who did this job, why they took it,
    and what it paid;
  - then the day in order, one chapter per stretch of it, each titled
    with the time of day and the task, like a time sheet ("5 a.m.:
    Muster"). Each covers the task; how it was done (tools, method, who
    gave the orders); the number it turns on (hours, weight, pay,
    calories); how we know (a letter, a rota, a dig, said aloud); and
    one human detail. It ends on what's coming next in the day: the
    worse part, or a surprise;
  - between minutes three and six, the part nobody tells you: the job's
    biggest surprise, which reframes it;
  - the last chapter, off duty and pay day: what they kept, what they
    spent, and how it ended for most of them, then one comparison that
    lands it in the viewer's own working week. No summary.
  Every step works by ear: the narration carries the whole day, and no
  chapter depends on a picture showing an exact layout, map, count or
  how a machine works.""",
    "expose": """- `want`: the polite version everyone knows, the bottom-drawer truth,
  and why the viewer should care (it's behind something they wear, do or
  fancy today). Say all three plainly; the cold open must deliver them.
  The film is built like gossip with receipts:
  - the cold open (under 45 seconds): the most eyebrow-raising true
    detail, said with a smirk; the polite version; the promise;
  - then behind the closed door, step by step, one chapter per stage
    (the bath, the dressing, the seduction, the outcry). Each gives the
    naughty detail, who was in the room, and the receipts (an account
    book, a letter, a sermon, a newspaper's outrage, said aloud). It
    ends on a bigger scandal, or "and it gets better";
  - between minutes three and five, the twist that turns it around (it
    was practical; the prudes were wrong; the scandal was invented; the
    ancients were naughtier);
  - the last chapter: how it ended up in the viewer's own wardrobe,
    bathroom or love life today, then one cheeky consequence. No summary.
  Every step works by ear; the pictures show the film's good-looking
  cast dressed as the setting allows.""",
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
    "working_day": """  - Every task made concrete: what they held, what it weighed, how long
    it took, what it smelt like, what it cost in today's money, and the
    modern job it most resembles.
  - `open_loops`: the job's biggest surprise last; before it, what each
    stretch of the day will reveal. `turn`: what comes next in the day,
    which each chapter ends on, or for the surprise chapter, the reframe.""",
    "expose": """  - Every detail concrete: what they wore and didn't, what it was made
    of, how long it took, who had to watch, what it cost, what the
    critics said in their own words.
  - `open_loops`: the main mystery last; before it, the smaller "wait,
    what?" each chapter answers. `turn`: the bigger scandal each chapter
    ends on, or for the twist chapter, the turnaround.
  - The cast: the real people the film is about, told straight, and a
    good-looking invented cast of the time (bathers, courtiers, beach
    crowds, dressers) who carry the glamour. Every one of them an adult.""",
}

OUTLINE_SOUND = {
    "story": "",
    "explainer": "\n\nThis is an explainer: every chapter's `sound` is \"none\" unless the pictures "
                 "really are somewhere loud (a storm, the sea), and then only that chapter.",
    "working_day": """

This is an explainer: every chapter's `sound` is "none" unless the pictures really are somewhere loud (a storm, the sea), and then only that chapter.
""".strip(),
    "expose": """

This is an explainer: every chapter's `sound` is "none" unless the pictures really are somewhere loud (a storm, the sea), and then only that chapter.
""".strip(),
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
  concrete fact in the film, said plainly ("In 1984, a drill in
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
  the mystery in plain words, then one consequence that changes how the
  viewer sees something ordinary, and stops.
- Talk to the viewer ("you") about things they know. Every idea made
  concrete: an analogy from ordinary life, a number at human scale (not
  "12 kilometres" alone but "taller than Everest, upside down"), a quick
  thought experiment, a real attempt and what went wrong. One idea at a
  time; a word they won't know is explained the moment it's used.
- Be funny where it's natural: a dry aside, an absurd comparison. Wonder
  over solemnity.
- Each picture illustrates the idea being said: a visual metaphor, a
  cutaway, someone trying it. The words carry the explanation; the
  picture never has to, because it can't be trusted with exact detail.
  The film's settings anchor it; most ideas get a one-off picture of
  their own, from the film's own world where possible. One picture per
  idea: when the narration comes back to an idea, so does its picture.""",
    "working_day": """Make it a working day explained, not a lecture and not a story:
- Third person, present tense: "a legionary", "the crew". The viewer is
  never cast as the worker ("you are..."); speak to them only for a dry
  aside or a comparison with their own job.
- The first three scenes give the strangest true detail of the day,
  said plainly ("A Roman legionary's most-used tool was a shovel."),
  then what everyone assumes instead, then the promise of the whole
  shift, in about forty seconds. Never open on a question, a greeting or
  "imagine".
- Then the day in order. For each stretch: the task, how it was done,
  the number, how we know (the source in a few words: "a pay slip found
  in Egypt", "a duty roster from Vindolanda"), and one human detail.
  Link with "but" and "so". Keep the clock moving: say the time when the
  day moves on.
- The narrator is a dry, deadpan guide with a time-and-motion
  inspector's eye: understatement, not jokes. The comedy is in true
  facts said flatly ("Lunch was porridge. So was dinner."). Never
  wacky, never shouting.
- The surprise chapter reframes the job. The last chapter covers pay,
  prospects and how it ended for most, then one comparison with the
  viewer's own working week, and stops. Never end on the title's
  question or a moral.
- Every idea made concrete: a weight they can feel, an hour they know,
  pay in today's money, a modern job it resembles. One idea at a time;
  a word they won't know is explained the moment it's used.
- Each picture shows someone at work on the task being said. The words
  carry the explanation, because the picture can't be trusted with exact
  detail. The film's settings anchor it; one picture per task, and when
  the narration comes back to a task, so does its picture.""",
    "expose": """Make it gossip with receipts, flirtatious and fun, never a lecture:
- The narrator is a knowing, flirtatious friend telling the naughty bit
  the history books left out: teasing asides ("Now. About the bath."),
  innuendo where it's funny, quick comic timing, a wink in every other
  line. Talk to the viewer ("you") like a friend sharing gossip.
- The first three scenes give the most eyebrow-raising true detail,
  said with a smirk, then the polite version, then the promise, in about
  thirty seconds. Never open on a question, a greeting or "imagine".
- Then behind the closed door, in order. Each chapter gives the naughty
  detail, who was in the room, and the receipts, named in a few words
  ("a 1907 police report", "the queen's own account book"). Short,
  punchy sentences; a laugh or a tease every few scenes; link with "but"
  and "so".
- The twist chapter turns it around. The last chapter lands it in the
  viewer's own wardrobe, bathroom or love life today, with one cheeky
  consequence, and stops. Never end on the title's question or a moral.
- Suggestive, never explicit: no sex acts, no vulgar words, and nobody
  under eighteen in anything about bodies, undressing or romance.
  Innuendo carries it; a body part is named plainly when it's needed.
- Every detail concrete: what they wore and didn't, what it cost, who
  watched. One idea at a time; a word they won't know is explained the
  moment it's used.
- Each picture shows the moment being said with the film's good-looking
  cast. The words carry the explanation, because the picture can't be
  trusted with exact detail. The film's settings anchor it; when the
  narration comes back to a moment, so does its picture.""",
}

SCRIPT_DIRECTION = {
    "story": "One concrete, drawable moment, never a montage or a\n  diagram.",
    "explainer": ("One clear, drawable picture of the idea being said: a character doing something, a "
                  "cutaway, a visual metaphor. Never a chart, a labelled diagram, a montage, or a picture "
                  "whose point is an exact position, angle, direction, count, scale or stage."),
    "working_day": ("One clear, drawable picture of the task being said: someone at work, the tool in hand, "
                    "the place it was done. Never a chart, a labelled diagram, a map, a montage, or a picture "
                    "whose point is an exact layout, count, sequence or how a machine works."),
    "expose": ("One clear, drawable picture of the moment being said, with the film's good-looking grown-ups: "
               "confident, flirtatious, reacting (a smirk, a wink, a scandalised glance), dressed on the revealing "
               "side of what the setting allows (swimwear on a beach, a draped toga, bare shoulders, a shirtless man "
               "at the baths). Framed on faces and whole figures, never on breasts or bottoms; anyone bathing seen "
               "from the shoulders up; no underwear worn on a body, no nudity, never people in bed. Never a chart, "
               "a diagram, writing, or a picture whose point is how a garment is built."),
}

SCRIPT_CARDS = {
    "story": "three in a film\n  at most, never a list of rules, a summary or a timeline the narration\n"
             "  already gives",
    "explainer": "about one scene in eight, for the number or comparison the explanation turns on,\n"
                 "  never a list of rules or a summary",
    "working_day": ("about one scene in eight, for the number the day turns on (hours, pay, weight,\n  "
                    "calories) or a then-and-now comparison, never a list of rules, a timeline or a summary"),
    "expose": ("about one scene in eight, for the number or the quote the scandal turns on (a\n  "
               "newspaper's outrage, a rule from an etiquette book), never a list or a summary"),
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
    "working_day": """- `momentum`: does every scene tell the viewer something new about the
  day (a task, a number, how we know), does the clock keep moving, and
  does the chapter end on what's coming next or a worse surprise? For the
  first chapter: do its first three scenes give the strangest true
  detail, what people assume, and the promise of the whole shift (score
  4 or less if any is missing)? For the last: pay, prospects and the
  landing comparison? Lecturing, listing facts, repeating and casting
  the viewer as the worker score low.""",
    "expose": """- `momentum`: does every scene reveal something new from behind the
  closed door or raise the scandal, is there a laugh or a tease every few
  scenes, and does the chapter end on a bigger scandal or the turnaround?
  For the first chapter: the eyebrow-raising detail, the polite version
  and the promise (score 4 or less if any is missing)? For the last: does
  it land in the viewer's life today? Lecturing, listing, repeating and
  prudishness score low; anything explicit or vulgar scores 1.""",
}
