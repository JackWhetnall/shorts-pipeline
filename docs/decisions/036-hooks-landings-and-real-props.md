# 036 — Every video hooks and lands; props that touch really touch

**Status:** active.

## What happened

After the Pythagoras demo (decision 035), the owner raised four points:

- **Endings.** Every video ended with an audio drop-off. The last segment
  spoke as if more was coming, and then the outro card cut in.
- **Hooks.** Every video needs a hook: a retention opening in the first
  five seconds. It should be defined by its essence rather than as a
  formula, applied to every channel, and fitted to each channel's voice.
  Minute Pastor's has to capture the listener without taking from the
  verse, and it has to make them glad their curiosity was satisfied.
- **Props that touch.** The ladder and the wall didn't relate: the wall
  stood in for an axis instead of the ladder resting against it.
- **Cost.** Do props have to be AI-generated, or is there a free library?

## What was decided

### The hook and the landing

**The hook is defined once, for every channel.** This is
`HOOK_AND_LANDING_GUIDANCE` in `pipeline/script_gen.py`. The first
sentence opens a specific loop: a question, a tension, or a gap between
what the viewer assumes and what is true, which only this video closes.
The rules:

- It is honest: the payoff must beat the promise, with no bait phrases.
- It never spends the answer.
- It starts mid-idea, with no preamble.
- It is one breath long, about 8-16 words.
- It speaks in the channel's own register. The intensity belongs to the
  channel; the open loop is universal.

It comes with a menu of ways in, not a template, because a template is
the sameness the originality rules punish.

**The landing is defined with it.** The last segment knows it is last.
It closes the opening's loop, lands one thought, and ends on a short
sentence that falls to a close. It adds no new idea, doesn't trail off,
and has no sign-off.

**The writer plans the loop before writing.** `hook_promise` and
`payoff` come first in the response schema, so the loop is decided
before any line is written. They are stored on the script. The script
check reads them:

- no hook is a note;
- a hook the script never pays off (bait) blocks the video;
- an ending that doesn't land is a note.

The script studio's batch writer follows the same rules.

**Each channel's register is its own setting.** `ChannelConfig.hook_style`
is a sentence or three describing how this channel's hooks sound. The
pitch draft writes it. The three existing channels were given one each,
written to fit their style prompts. It is editable next to the style
prompt.

**Quote channels hook before the verse.** On Minute Pastor the verse is
read verbatim, so it can't be rewritten into a hook. A new spoken hook
line now comes first, then the verse, then its citation.
`Script.source_index` records which segment is the verbatim source, so:

- the citation follows the verse, not the hook;
- the long pause comes after the verse;
- the originality check skips the verse but checks the hook;
- the script check marks the right segment as SOURCE.

Scripts saved before this change still read as source at segment 0.

**The ending is also an audio problem.** The last line had no pause after
it, and a test enforced that, so the outro card started on the final
syllable. Now:

- `Pacing.end_hold` (0.9 s) holds the last picture in silence before
  the outro;
- the final line keeps more of its natural tail (0.6 s, where other
  segments keep 0.25 s);
- the final line fades gently (0.35 s, where other segments fade over
  0.02 s).

### Props

**Things that touch in the narration touch on screen.** The scene guide
now requires the writer to:

- work out the contact points once;
- use the same points for the objects and for the geometry drawn over
  them (the triangle's corners are the ladder's foot, the wall's foot
  and the ladder's top);
- stand a wall on the ground, and never use an axis as a stand-in for
  a wall.

**Anything that must line up with geometry is drawn, not illustrated.**
The new `beam` shape is a bar lying exactly between two points: a plank,
pole or ramp, or with `rungs`, a ladder. Areas take a `texture` (bricks,
planks or hatch), so a wall is a rect with bricks. An emoji ladder was
tried first: it is a stubby, stylised drawing with no clear long axis,
and couldn't be laid accurately along a line.

**Long, thin illustrated objects can still be laid along a line.** This
is prop `span` (for a candle or a pencil). The object's own long axis is
found from its pixels (principal component, `props.axis`), whatever
angle it was drawn at, so it is turned and scaled onto the line with its
top at the `to` point. `fit: "cover"` fills a box exactly.

**The free library comes first.** Before generating anything,
`pipeline/scenes/iconlib.py` asks Iconify for Microsoft's Fluent Emoji:

- licensed MIT;
- about 1,500 everyday objects;
- a colour set, used by Clean flat;
- a line set, recoloured in the channel's own ink or accent, used by
  Chalkboard, Parchment and Neon, so props look drawn in the same hand.

The lookup matches exact names only ("wall" must not become "wall-clock")
and tries the most specific name first ("wooden ladder", then "ladder").
Each prop is kept with a note of its source and licence. If the library
has nothing suitable, or can't be reached, the prop is generated as
before. Nothing but the object's name is sent.

### Scenes look at themselves before rendering

The first video under these rules still drew the ladder "against a
wall" with no wall. The layout check measures boxes and can't see a
missing object. So each scene is now also shown, as two stills (halfway
and complete), to a vision model with the words, before it's rendered.
Haiku does this, at about half a cent.

Its findings join the layout notes in the one repair round:

- something named but missing or wrong;
- things that should touch but don't;
- clutter;
- a picture too small for the stage.

A measured "too small" check was added too.

The frame check on the finished video now judges a scene frame near the
end of the scene, not the middle. Sampled mid-way, a scene is always
"incomplete", and that falsely held a video.

## Consequences

- Every existing channel's next script will open with a hook and end
  with a landing. Minute Pastor's videos gain a spoken line before the
  verse, about 14 words that come out of the analysis's word budget.
- Generated props become the exception. The OpenAI spend was already
  small (about 4 cents per object per channel), but the library is
  instant and gives a consistent look.
- The draft now chooses a look from the audience's relationship to the
  subject, not the subject's stereotype. The maths draft's chalkboard
  read as school to adults who were put off maths at school.
