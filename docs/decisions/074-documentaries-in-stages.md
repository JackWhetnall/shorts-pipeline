# 074 — Long-form documentaries, made in approved stages

**Status:** active. Builds on the animation bible (051), style grammar
(053) and widescreen frame (054). Motion from the video model is not used
yet (see below).

## What happened

On 6 October the owner set the direction towards long-form video:

> "for a given topic it should be possible to do this in stages to make
> sure that the plan for the is actually going to be good. this should
> start with a text outline of what the video is going to talk about,
> and how it is going to show it ... we then can generate the full
> narration script (with 'stage directions' too), as if it were a play.
> from there we can generate the still images of the scenes ... giving
> a proper storyboard. and from there, we can call the actual video
> generation."

> "this video generation needs to be done so the art style, movement
> style etc is extremely consistent between clips in one video, and also
> between different videos in a single channel. we probably need generic
> character images that can be a basis for what is produced, and some
> context about what videos have come before it"

They'd made a template channel, History Unmystified (one historical
figure per video), and found the setup made decisions they couldn't
control:
- topics came in a fixed number, each with a fixed number of videos;
- topic titles couldn't be edited;
- everything assumed shorts, with the length defaulting to 60 seconds.

"American presidents may have 15 people who are worth talking about, but
Famous scientists may have 50." And for each long video, some shorts
(three by default, configurable) that are "a mini channel video that
leaves the user wanting to see more", not "hey come watch this channel".

Asked before building, the owner chose:
- about ten minutes a video;
- stills only for now, at about $3 a video: full motion would be
  $30-50 a video;
- approval at every stage;
- teasers redrawn vertically rather than cropped from the widescreen
  video.

## Decisions

**A third format, `documentary`** (`ChannelConfig.documentary`: minutes,
teasers, scene_seconds). Each plan entry is one video, made through five
stages (`core.production`, stored under
`channels/<key>/productions/<entry>/` so a rename carries them):

1. **Outline** (`pipeline.documentary.outline`). The plan:
   - a through-line: the turning point the film pays off;
   - a visual concept: a motif and a colour script;
   - chapters, each with what it says, what's shown and its minutes;
   - the cast: every recurring person, place and object, described for
     a painter, never in the medium's terms.

   The writer is shown the channel's cast library and its other films.
2. **Script** (`script`). The narration as a play. Every scene has:
   - a stage direction, framing and camera move;
   - the cast in it;
   - an optional on-screen caption;
   - the words said over it.

   Scenes are about `scene_seconds` long. It's written a chapter at a
   time, each call shown the narration so far: a whole ten-minute script
   with directions doesn't fit safely in one non-streaming call, and a
   longer one never would. One chapter can be rewritten with a note.
3. **Storyboard** (`stills`). A still for each scene, drawn by the
   keyframe drawer (051). Its references are the channel's style sheet
   and the model sheet of each cast member in it. The vision check then
   looks at ten stills at a time and redraws failures once. The owner can
   redraw any still with a note.
4. **Video** (`render`). The narration is voiced scene by scene. Each
   still is held for exactly its words, with:
   - its camera move (a push in, pull out or pan, eased;
     `finish.camera_shot`);
   - the chapter title on a chapter's first scene;
   - captions as faded lower-thirds.

   Then music is ducked under the voice. It goes to the long-video folder,
   so it uses the long slots, YouTube only, and always waits for review.
   Its title, a description with chapter marks and a thumbnail go with it.
   The originality check runs on its narration.
5. **Teasers** (`teasers`). N vertical shorts, written then made:
   - a hook, one piece of the story, and an ending that leaves the
     question open;
   - new words, never the documentary's sentences (reused wording is
     what YouTube demonetises);
   - never "watch the full video" or "subscribe": the description names
     the long video;
   - stills redrawn in the vertical frame with the same sheets, and
     word-by-word captions;
   - into review.

**Every stage waits for approval.** Each runs as a job (Activity, batch
prices by default, Accelerate; decision 072). It ends `ready`, or
`failed` with the reason. The owner can approve it, edit it (which
approves it), or have it made again with a note. Changing an approved
stage makes every later one `stale`: a storyboard drawn for an old
script isn't trusted. Approving the teasers' scripts is what makes them.

**Consistency, within a video and across them:**
- **The hand** is fixed by the style sheet drawn from the channel's
  chosen style frame. A look's identity doesn't include its frame, so
  the widescreen film and the vertical teasers share one bible.
- **The people** are fixed by a channel-wide cast library
  (`channels/<key>/cast_library.json`, `documentary.cast`):
  - a member keeps one name and description for the channel's life,
    and its sheet is drawn once per look;
  - the outline writer is told to reuse library members word for word;
  - a person at a very different age is a separate member.

  So Washington is the same man in his own film and in Adams's.
- **The series** is held together by the outline writer seeing the
  channel's other films' through-lines and visual concepts, so each
  feels like the same series but never the same film.

**The plan is the owner's** (all channels, not only documentaries):
- The draft page offers shorts or long-form.
- Its topic plan is editable text, one "Title: what it covers" a line,
  in order, so topics can be renamed, added, removed or reordered.
- A base number of videos per topic is set there.
- On the plan page, a topic is filled with as many videos as chosen, and
  any topic can be given more ("Write that many more"): written to
  follow on, none repeating.
- A documentary draft gets twelve topics of ten, as a start.

**The shorts machinery stays out of the way.** The scheduler never makes
a documentary channel's video itself. Hourly, it writes outlines (only)
for its next videos with no production yet, at batch prices, when its
publishing plan is on. "New video" and "Coming up" go to Productions.

## Not done yet

- **Motion.** The storyboard's stills are the first frames the video
  model would animate (051), so motion is a step after the storyboard
  when it's wanted. It wasn't built in this step: no FAL key is set yet,
  and the owner chose stills for cost.
- **The look.** History Unmystified had no animation style chosen. With
  none, the style compiles to the default (felt on a tabletop), so
  drawing is refused until one is chosen. A trial outline written before
  that came out full of felt and paper tags. That's why the outline now
  keeps the medium out of descriptions and words out of pictures.
- **Its plan.** History Unmystified's first topic was written for
  shorts: its entries are moments ("Lincoln and the Gettysburg Address")
  rather than whole lives. They make fine documentaries of a moment, but
  the owner asked for one figure per video, so the list is worth writing
  again. That's left to the owner.
