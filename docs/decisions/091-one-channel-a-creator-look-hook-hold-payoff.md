# 091 — One channel, a creator's look, and explainers built to hook, hold and pay off

**Status:** active. Amends 089 (explainers).

## What happened

On 12 October, after the profitability analysis, the owner decided to go
all in on one channel, Why, Though?, a science explainer. Each channel
has to join the Partner Program on its own, so fewer channels is better
for now. They also wrote:

> "the current art style is clearly AI, it's too much just cartoon,
> doesn't have a proper YouTube creator style"

> "it has to hook, then hold them, with them expecting a payoff, and
> that payoff is delayed but not to the point that it seems absent ...
> The video needs to justify the title in the opening moments so that
> people don't think it's just bait (but doesn't have to be a straight
> question and answer, it should be more clever than that)"

## Decisions

**A look chosen from four tried.** The same two scenes were drawn in
four styles, about 40 cents:
- geometric motion graphics;
- cut paper;
- risograph print;
- ink and wash.

The owner chose geometric motion graphics: flat vector shapes with no
outlines, four or five rich colours on deep navy, glows, long shadows
and film grain. People are tiny, adult and rounded, with dot eyes. The
cards use the same navy palette. The test drew every geologist as a
child, so people are now described as adult.

**Explainers are built as a detective story about an idea**
(`kinds.py`, every explainer prompt):
- **Pitch.** The title is a specific, checkable claim or a paradox,
  never a vague tease. The hook proves the title in its first fifteen
  seconds with the strangest real fact in the film, then gives a
  personal reason to care, then names the mystery. The mystery is
  answered only in the last minute.
- **Outline.** The film runs in this order:
  - a cold open of under 45 seconds: proof, stakes, then the mystery
    stated as a promise;
  - the obvious answer, taken seriously, and what breaks it;
  - clue chapters, linked by "but" and "so", never "and then", each
    ending on a deeper problem;
  - a twist between minutes three and six that reframes the film;
  - a callback to the mystery every minute or so, so the payoff is
    clearly coming;
  - the payoff in the final fifth: one clear picture, one everyday
    consequence, then the end.
- **Script.** The first three scenes do the proof, the stakes and the
  promise. The film never opens on a question, "you'd think",
  "imagine" or "this is the story of". No two chapters end the same way.
- **Critic.** It scores the opening's proof, stakes and mystery, and
  whether the mystery is kept alive without being given away.

**Checks that need no model** (`editor.explainer_checks`):
- An opening that is a question or a wind-up is sent back for
  rewriting.
- So is a chapter ending that repeats an earlier ending's question
  shape. The first drill film ended three chapters on "So what...?".

**A fact-and-sense pass for explainers** (`editor.fact_check`, about 5
cents).
- **Why.** The first two drill scripts needed lines fixed by hand.
  Viewers of science channels check the numbers, and one wrong figure
  costs a film its credibility. This is the exception to 086's "no
  fact check", which stays for story channels.
- **What it does.** One call reads every line and card. It works out
  every ratio and checks every number, physical claim, literal sense,
  invented present-day "facts" and stray production words. It rewrites
  only the lines that are wrong; the corrections are kept on the script
  as `facts`.
- **Tried on the uncorrected second script:**
  - caught six of nine problems: 22 years, not 19; the glowing bit; the
    leaked "reframe"; the pressure figure; sixty times, not six and a
    half; a meaningless scale comparison;
  - missed three: a nonsense closing line, an invented present-day
    visit and a repeated date.

  So it is a first line of defence, not a guarantee.

**Pictures vary, and cutaways stand alone.** The remade storyboard was
nearly all navy and sunset orange, and about a dozen frames had the
planet's cutaway hanging over a landscape. An explainer's directions
now vary the setting and light from scene to scene, and put a cutaway
in space or on its own.

**The close check ignores verdicts it clears itself.** It marked a
picture failed while writing "no clear fault"; such verdicts are now
dropped (`stills.CLEARED`).

**The proof film was remade.**
- Its angle is "Why Earth's Centre Is Harder to Reach Than the Moon".
  The pitched title, "...Is Further Than the Moon", is literally false,
  so it was changed to one that can't be called bait.
- It opens: "We've sent twelve people to the Moon, three hundred and
  eighty four thousand kilometres away. Nothing we've ever built has
  gone more than twelve kilometres down."
