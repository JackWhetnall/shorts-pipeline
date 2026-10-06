# 076 — Long-form channels get their own settings and a setup list

**Status:** active. Builds on 074 (documentaries) and 075 (the pivot).

## What happened

Setting up History Unmystified's first film on 6 October, the owner:

> "there are so many settings that are left over from the old workflow.
> it is unclear what is needed and when for this new form of channel ...
> there are still settings about pictures, and paintings and engravings,
> and time delays after the passage, and many other things that dont
> seem to apply"

> "keep the old settings as they are, but have channels defined as
> "shorts" or "long form", and then have a specific (greatly reduced)
> set of channel settings ... a "sleepy maths channel" might have no
> generated pictures, instead relying solely on diagrams and equations
> being drawn. for this instance i shouldnt be able to go through picking
> what picture style to generate. and i shouldnt be shown what diagram
> generation there is if its a history channel with only pictures."

> "it is unclear if i have achieved doing those settings, and if so do i
> need to then actually click the create video button or not."

They also asked whether FAL was needed. It isn't: a documentary's
pictures are stills drawn by the image model and moved across by the
camera. FAL is only for the video model, which long-form doesn't use.

## Decisions

**Two kinds of channel.** The `documentary` format is now "long form"
in the app (`ChannelConfig.long_form`, `LONG_FORM_FORMATS`); narrated and
quiz are shorts. The stored format is unchanged.

**A long-form channel has its own settings page**
(`_longform_form.html`), holding only what a film reads, as measured
from `pipeline/documentary`:

- **Channel**: name, writing brief, how a film opens, never show.
- **Films**: what fills the pictures, length, how long each picture
  stays on screen, teasers per film, with what a film of that length
  costs in words, voice credits and pictures.
- **Voice**: the voice, speed, pronunciations. No pauses after a
  passage, no cadence presets, no target length in seconds.
- **Look**: the style builder, for stills.
- **Music**: on or off, level, tracks.
- **Publishing**: when films go out and when teasers go out (a long-form
  channel's film slots were missing from the old page altogether: they
  showed only for quiz channels), YouTube.

The shorts page is untouched, and every shorts setting a long-form
channel had stays stored as it was. It's posted to the same route, and
`web.forms` only changes fields a form carries; the page carries the
same `*_present` markers and hidden values (posting profile, effects)
that keep its save from clearing what it doesn't show.

**What fills the pictures is chosen first** (`documentary.pictures`):
"drawn scenes" or "diagrams and equations". The look builder then offers
only the approaches that kind can draw (acted or scenic for drawn
scenes; diagrams for diagrams) and only the starting points that use
them. Questions only animation reads (a presenter, how it moves, words
on screen) are kept and submitted but not asked, previews are
widescreen, and what's for the video model (the animation switch, the
FAL warning, engine badges, "Make it move", motion and cutting, quality
and cost, the cast of hosts) is hidden on this page.

**Diagram films aren't built yet**, so that choice is shown, labelled
"Not built yet", and can't be picked. A channel already set to it is
told plainly, and its setup's look step is blocked. Offering a setting
that does nothing is what the owner complained of.

**"Never show" now does something on long-form.** It was on the
channel but no documentary prompt read it. It now reaches the outline
writer and every still's prompt (`keyframes.prompt_for`, via the board's
`never`; boards without it, every shorts board, are unchanged).

**A setup list says what's done and what's next** (`core.long_form`,
`_long_form_setup.html`), on Settings and on Productions until the first
film is started:

1. what the films are about; 2. a voice; 3. the look (blocked for diagram
films); 4. style frames (optional; drawn with the first storyboard
otherwise); 5. films in the plan; 6. **start the first film**; then,
optional until a film is ready, YouTube and the publishing times.

When everything a film needs is set, it says so, names the first film,
and says to open it and press *Write the outline*: nothing is made or
spent before that, and each stage then waits for approval.

**Each film's page says what to do now**: press a stage's button, read
and approve, wait (with how long batch prices usually take), or make it
again, worked out from the first stage not approved.

**A long-form channel launches by its own steps** (`core.launch`). The
header said History Unmystified was "Setting up" against the shorts
checklist, whose last stages (the automatic checks proving themselves,
then autopilot) a long-form channel can never reach, since its films
always wait for review. Its launch is now the setup list's steps.

The frozen channels' check (075) accepts a new settings key with its
default (`differences(allow_new=("/config",))`): a new setting changes
nothing by existing, and any effect it had would show in the rest of the
fingerprint.

## Not done

- Diagram films (the compositor filming a whole long-form film).
- A new-channel flow that asks "shorts or long form?" first and drafts a
  long-form channel straight onto this page. The pitch draft already
  offers long-form (074); its review page still uses the older layout.
- The chapter titles and captions take their colours and type from the
  channel's older art direction (`scenes.art`), not shown on this page.
