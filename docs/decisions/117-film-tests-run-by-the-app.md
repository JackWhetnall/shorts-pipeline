# 117 — Film thumbnail tests run by the app; end screens stay by hand

**Status:** active. Replaces decision
[115](115-find-the-thumbnail-style-first.md)'s Studio step for films;
the style, refine and content program is unchanged. Long quizzes keep
Studio's test ([083](083-thumbnail-tests.md)). Instagram's automatic
posting ([116](116-instagram-posts-by-itself.md)) stays built but unused:
the owner will post it by hand alongside TikTok for now.

## What the owner said

"The A/B testing is something i need you to do, providing the thumbnails
and titles to check for this. can it be done over the API or does this
also have to be manual? also, i have manually set end cards now, but
would love for them to be set automatically on upload too."

## What YouTube allows

- **Studio's Test & Compare** runs all three thumbnails at once and
  judges by watch time, but it exists only in Studio. The Data API has no
  way to start one or read its result.
- **End screens and cards** exist only in Studio too. The API has nothing
  for them, and scripting Studio would break YouTube's terms on automated
  access. They stay by hand: about 30 seconds a film, with Import from
  video.
- **What the API does allow:** setting a video's thumbnail (the upload
  permission is enough) and changing its title (that needs the
  permission to manage the channel). Each video's daily impressions and
  click-through come from the Reporting API's reach report
  (`core/reach.py`). That's how Shorts have been tested since decision
  083.

## Decision

**Films are rotated by the app, as Shorts are** (`core/thumbnail_tests.py`).
- A film's three thumbnails are still made with it, at the video stage,
  so they can be seen before it goes out.
- Once it's out, it shows A (the thumbnail it went out with) for two
  days. Then A, B and C take three days each, twice: twenty days in all.
- Films in one round start at different variants, so a film's age
  doesn't favour one.
- Days on which the thumbnail changed are left out, as before.

**Films share a round while the style is being found.** One film's twenty
days at the channel's present traffic is rarely 300 impressions per
variant.
- In the style and refine phases, films planned within a week of a
  round's first join it, up to four.
- Each film in a round gets the same three variants, drawn for it.
- A content round stays one film's own: it tests that film's words,
  picture and title.

**Titles rotate with thumbnails in content rounds**, when the channel's
YouTube connection may manage it (`youtube.set_title`). The update keeps
the rest of the video's snippet, since an update replaces all of it.
Without that permission, only thumbnails rotate, and the film's page
says so ("thumbnails only"). At the end, the winning title becomes the
film's own in the app too.

**Judging.**
- A round is judged once every film in it has rotated and its figures
  are in, three days later.
- The rules are decision 083's: 300 impressions per variant, and a
  winner at least 8% ahead.
- Each film then keeps the winner, or A.
- A tie in the style phase counts each style as tried, but crowns no
  champion and counts as no defence (`doc_learn(clear=False)`). With
  traffic this low, ties will be common. Counting them as wins for the
  current style would end the search on the panel style by default.
- A film that's discarded before it goes out doesn't hold its round up.

**Nothing rotates until click-through can be measured.** That means the
reach reports' job exists and they report no error. A rotation nobody
can measure would be twenty days for nothing. On 19 Oct the Reporting
API was off in the owner's Google Cloud project, so switching it on is
their step (TASKS G5).

**On the film's page**, the test card shows:
- **Testing by itself**, the day of twenty, and which variant is up;
- each variant's click-through so far;
- then the winner or the verdict.

The Studio button and the "Studio's winner" ticks show only when the
channel's "Test thumbnails" is off. The long-form settings page now has
that switch.

**Made ready on 19 Oct for Why, Though?:**
- its two published films' rounds that tested the same styles were
  merged;
- the five films waiting to go out were given their three (free; the
  style phase draws nothing new), joining the open rounds;
- "Test thumbnails" was switched on.

Nine films are now in three rounds, between them every style against the
current one.

## Rejected

- **Driving Studio's test from a script in the browser:** YouTube's terms
  forbid automated access to the site, and a restricted channel is the
  wrong risk.
- **One round per film:** too few impressions to name a winner at the
  channel's present size.
- **Starting rotations before the figures work:** see above.

## Worth revisiting

- Once a film gets thousands of impressions a day, Studio's own test is
  the better measure (watch time, all three at once). It would then be
  worth asking the owner to run it for the content phase.
- If YouTube adds Test & Compare or end screens to the API.
