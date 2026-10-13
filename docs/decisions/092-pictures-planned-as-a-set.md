# 092 — Pictures planned as a set: settings, a picture editor, cuts between neighbours, an ending

**Status:** active. Supersedes 091's "cutaways stand alone" and 090's
`stills.repeats` for new scripts.

## What happened

On 12 October the owner watched the remade drill film:

> "my main issue is the repeated use of the earth cutaways - there are
> maybe a dozen or more different images that all show the earth with
> people looking up at it. This is exactly the kind of picture
> duplication we want to avoid"

> "it seems to have come up with the earth cross section as a character
> ... Let's say that there is a video about amoebas: they would live on a
> Petri dish and the humans would be in the lab with the microscope. I'm
> worried that as it stands now, the amoebas would sometimes be shown in
> the lab."

> "'cutaways will sit on their own' is a worrying statement from you; it
> suggests that you are solving one specific problem when in reality
> this needs to fix the whole set of problems in a general way"

Other points:
- **Shots:** "often it shows one picture and then a zoomed in portion -
  this is quite repetitive", and it would be better to mix them: "wide
  shot A, then wide shot B, then section of A".
- **The ending:** it "sort of concludes and then stops". It should hold
  the last picture for a few seconds with no voice, fade out, and end on
  a good last line.

The causes were general:
- **The cast had no sense of place.** It was "every person, place and
  object in more than one scene", so a diagram became a cast member.
  Nothing said where anything could be: people stood beside a planet in
  space.
- **The writer couldn't see its pictures.** It writes a chapter at a
  time, so it couldn't see that it kept asking for the same one.
- **Repeats were caught too late and too narrowly.** The repeat check
  ran only when drawing, and only caught pictures that were identical.

## Decisions

**Settings** (`outline.settings`, `SCALES`).
- The outline names the three to six places a film returns to, each at
  one scale (space, planet, landscape, human, small, microscopic,
  cutaway), with a description.
- Each cast member lists the settings it exists in. The cast is now
  only people and particular objects that must look alike. Diagrams,
  cutaways, symbols and ideas are never cast, and places are settings.
- A cutaway or microscopic setting holds only what is really inside it.
  Something from another setting is seen only through a real thing in
  this one: a screen, a model, a map.
- Each scene names its setting, or "one-off" for a picture with a place
  of its own, such as a visual metaphor or an example. A one-off has no
  cast.
- Each setting gets a reference sheet like a place, so it looks the
  same each time.
- The writer is shown every picture written so far and told never to
  repeat one. Explainers are told to give most ideas a one-off picture.

**A picture editor** (`pictures.plan`, after the script and its other
editors). One call reads every picture together and does three things:
1. **Misplaced pictures** are redirected to the right setting, or the
   thing is shown through something real there.
2. **Near-duplicates are found.** These are the same subject from the
   same viewpoint at the same scale, whatever small details differ.
   Each later one either shows the earlier picture again (`same_as`,
   drawn once, recut) when the narration is still about it, or is
   redirected to something genuinely new.
3. **Settings are balanced** (`BALANCE`):
   - an explainer's settings carry at most 25% of its pictures and run
     at most 4 in a row;
   - a story's carry at most 40% and run at most 7.

**Sameness is counted by code** (`looks`, `crowded`, `LOOKS_MAX`).
- **Why the code counts.** Asked only to avoid near-duplicates, the
  editor let thirteen pictures of the drill bit in its shaft through as
  "different": coated, straining, sealed. Asked to group the pictures
  itself, it did two opposite things. First it split one subject by
  framing (medium, close, wide), so each group looked small. Then it
  lumped a whole place into one look: the rig, the engineer, the
  geologist and the wellhead together. It counted 25 good pictures as
  repeats.
- **How it works now.** One small call names each picture's main
  subject in consistent words (a cast member by name; "the drill bit"
  however it's framed or whatever it's doing). The code groups pictures
  by setting and subject. A one-off is always a look of its own.
- **The limit.** Each look may have at most 4 pictures of its own in an
  explainer, or 5 in a story. The rest must show one of those again or
  become a genuinely different picture. The code recounts after each
  round of the editor's fixes.

**What else the first plans taught**:
- **One-offs are counted too.** Left out of the count, wet clay
  swallowing something appeared in four of them. A one-off metaphor
  may appear at most twice (`ONE_OFF_MAX`): the second is a callback,
  more is a habit.
- **One picture per idea.** When the narration returns to an idea, its
  picture comes back instead of a new prop. One plan illustrated "it
  closes over" with mud, wax, clay, soil and sand. One-offs come from
  the film's own world (tundra moss, snow on a birch log), not a
  generic object on a plain table.
- **Balance is looser than first set.** At 25% and four in a row, a
  plan turned 29 scenes into generic one-offs. Since the count of looks
  does the work against sameness, it's now 35% and six in a row for
  explainers.
- **Work is batched.** A whole film's fixes in one answer overflowed the
  20,000-token ceiling twice and the film went unplanned. Now there is
  one pass over the whole film (at most 15 changes, low effort), then
  the code's findings go back 10 scenes at a time, each with the whole
  storyboard, for up to two rounds. The subjects are labelled again
  after each round, because redirected pictures can repeat each other.
- **A picture shown again takes its source's setting and cast.** A site
  scene showing a cutaway is in the cutaway, so the cuts between
  neighbours stay right.
- **A picture described again is shown again.** One described word for
  word like an earlier one, or with up to six words added ("..., now
  still and final"), is that picture.

- **A cutaway setting is one look.** It's the same view whatever its
  subject is called. The shaft cut open was named "the drill bit" in
  some pictures and "the borehole shaft" in others, and so got past the
  count.
- **A cap on screen time.** No look is on screen more than 6 times in an
  explainer (9 in a story), counting pictures shown again
  (`SHOWN_MAX`). Four pictures each shown three times had put the shaft
  on screen eleven times.
- **The close check catches panel sheets.** It now looks for a sheet of
  panels or studies instead of one picture. Two one-offs came out as
  grids.
- **Number cards only take numbers.** The fact check puts only a number
  in a number card. One correction had put "Rock turns ductile near|"
  where 180°C belonged.

- **One frozen moment.** Every picture description, the writer's and
  the editor's, is one frozen moment, never a process. "Squeezed tighter
  and tighter" and "slowly covered until it vanishes" were drawn as
  strips of panels, twice each, even after a redraw.

A plan now costs about 25–35 cents. The fact check still let through
eight lines on the final script. Among them were an invented quote with
wrong physics, invented characters given present-day lives, and "the
molten layer" for the mantle. They were fixed by hand, so read the
script before approving it.

Then come the checks that need no model:
- `audit` finds anyone named where they don't exist, a setting over its
  share, or a run too long. Showing something through a screen or a
  model is allowed. What it finds goes back to the editor once.
- `validate` makes the rules hold:
  - cast only where it exists;
  - a picture shown at most three times, never in consecutive scenes;
  - a reuse always points at an original picture, never at another
    reuse.

Reuses survive a chapter rewrite, which re-points them. A redrawn
picture is copied to every scene that shows it again, and a redrawn
reuse gets a picture of its own. Costs about 7–15 cents.

What a first try showed:
- **Without one-offs:** five settings and no one-off pictures put 40 of
  77 scenes in two cutaways.
- **The editor's misses:** it still let an engineer stand inside the
  shaft. `audit` exists because of that miss.

**Cuts between neighbours** (`shots.interleave`).
- Across a run of scenes in one setting, a scene's last detail shot
  moves into the next scene, after that scene's whole picture: A | B, a
  detail of A | C, a detail of B.
- Each scene keeps the number of shots planned for it.
- The first scene in a run gives up its detail only if its picture can
  then be held within the 9-second limit.
- One-offs and cards break a run.

**An ending.**
- The last picture is held 5 seconds after the last word (`END_HOLD`),
  then fades to black over 2.5 seconds, and the sound fades over 3.5.
  If the last shot was a detail, the whole picture comes back for the
  hold. Five seconds is also the minimum for a YouTube end screen.
- A last-line pass (`editor.final_line`, about 1 cent) keeps a strong
  last line or writes one. A strong one is short, final, and often a
  callback, never a question, a summary or a moral.
- The script's own instructions ask for the same.
