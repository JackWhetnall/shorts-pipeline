# 087 — A second look: voice, story, light, air, sound

**Status:** active. Builds on 086.

## What happened

On 12 October the owner watched *The Baker Who Wasn't Allowed to Flee
the Plague*, the first One Day In History film:

> "ok that video is very similar, watercolours, same voice - also the
> script voicing isnt very inspiring. are you sure this is the best you
> can do? i dont think it would really capture an audience. it didnt
> capture me. also the visuals look a bit like a powerpoint. the
> pictures are gloomy, which can be fine but make the video a bit dingy.
> and then these bright visuals (that are stylistically odd, and some of
> the info seems pointless) appear and it is quite jarring."

Measured against that:
- **Voice:** both documentary narrators were premade ElevenLabs voices,
  middle-aged British men (Daniel, George), read by the Turbo v2.5
  model with no direction.
- **Brightness:** the drawn pictures averaged 16% brightness, against
  35–45% for a well-lit film. The look's "dramatic" mood asks for "low
  and directional light, with deep shadows" and a heavy vignette.
- **Cards:** they averaged 76% brightness, nearly five times the
  pictures, in a different visual language (bright parchment slides),
  and some said little ("The Lord Mayor's Plague Orders": a list).
- **Motion:** nothing in a picture moved but the camera.
- **Script:** you watched the day go by and wanted nothing. The film
  restated one idea (the law that kept the apprentice in London) in a
  dozen wordings. No character spoke.
- **Sound:** one music bed, no ambience.

## Decisions

**Voice.**
- A documentary channel can be voiced with a newer model
  (`documentary.voice_model`). ElevenLabs released v4 in October 2026,
  and its Turbo variant reportedly ranks first in blind listening tests
  at the same price tier as v2.5. On launch pricing, the remade film's
  12 minutes cost 599 credits.
- v3 and v4 perform inline delivery cues. The script may open about one
  line in four with one ([whispers], [tense], [wry], [urgent] ...).
  `tts.strip_tags` and `without_tags` keep cues out of word timings,
  transcript checks, word counts and the originality check. Any other
  model has them taken out before sending.
- **Characters speak** (`documentary.dialogue`). A scene can be a cast
  member's line (`speaker`), voiced by `render.voices_for`: a different
  premade voice per speaking character, British first, women's voices
  for women, never the narrator's.
- **The narrator is the channel's own:** One Day In History's voice was
  designed for it with ElevenLabs Voice Design (229 credits), a low,
  warm, wry English woman's voice. Of three candidates, the one with the
  widest pitch and loudness range was kept. A designed voice is used by
  no other channel.
- The shorts' voice path is unchanged. A call that names no model uses
  the old one and makes the same cache key.

**Story.**
- The outline now has a `want`: what the person at the centre wants
  today and what failing costs. Chapters end on the turn that makes the
  next necessary.
- The script is told: someone wants something; people act, argue, lie
  and joke; say the big idea once at most and never close on a moral;
  wit is welcome; vary the rhythm so a voice has something to perform.
- The editor's critic now scores watching, remembering and explaining
  low, and theme-restating low. A deterministic check catches a
  three-word phrase used four or more times.
- **Cards are rare and earned:** three a film at most, only for a fact
  that hits harder seen than heard. Never a list of rules or a summary.

**Pictures.**
- One Day In History's look is now "a cinematic film still from a
  big-budget historical drama", with natural light that follows the time
  of day, and the "clean" mood instead of "dramatic". The outline's
  colour plan follows the real time of day, and stage directions say
  daylight is bright.
- **Exposure** (`atmosphere.exposure`): a still darker than a daytime
  level (34%, or 24% at night) is lifted with a gamma curve, never
  darkened. The old film's pictures lifted by a gamma of about 1.6.
- **Air** (`atmosphere.py`, `documentary.atmosphere`): embers, dust,
  rain or snow chosen from the scene's direction, drawn here as seamless
  loops of light on black and screened over the shot. Free.
- **Cuts on the words:** a scene's shots are cut at the starts of
  sentences or clauses (`render.beats_in`, `shots._lengths`), at most
  40% of a shot away from an even split. Shots are now about 4.8 seconds.
- **Cards over the picture:** a card is drawn over the scene before it,
  blurred and darkened, in light type on a smoked-glass panel; maps go
  dark too. Storyboard previews match.

**Sound** (`ambience.py`).
- Each outline chapter names its background from a fixed vocabulary
  (interior_fire, street_quiet, market, rain, bells and so on). The
  video lays that bed under the chapter, looped, crossfaded and 15 dB
  under the voice.
- Beds are made once by ElevenLabs' sound-effects model, at about 40
  credits a second (20-second loops), and shared by every channel.
- The current API key lacks the sound-effects permission. Until it's
  given, films are made without beds and the report says so.

## Not done, and why

- **Real depth (2.5D parallax)** needs a depth model on this machine.
  Depth Anything V2 Small is Apache-2.0, about 100 MB, from Hugging Face
  via onnxruntime, which is already installed. Downloading it is the
  owner's call.
- **Generated motion** (image-to-video) needs a FAL key. Kling-class
  models cost about $0.08 a second, so a dozen 5-second moments is
  about $5 a film.
- **The remade film's pictures:** the OpenAI API account ran out of
  credit on 12 October ("no credits remaining"). The script, the voice
  and the plan are made; the storyboard and video wait for credit.
