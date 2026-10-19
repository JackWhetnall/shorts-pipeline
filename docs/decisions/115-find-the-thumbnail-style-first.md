# 115 — Find the thumbnail style first; endings that close without restating

**Status:** active. It replaces decision 114's A/B options, and
loosens decision 113's last-line rule.

## What the owner said

- **On the A/B thumbnails:** they were all "different" but in essentially
  the same style. The point is to work out the best style first:
  different colours, fonts, pictures and layouts, even angled against
  straight text. Then make smaller edits, such as which words or picture
  suit a given film.
- **On endings:** the last line doesn't have to rehash the title's
  question. It can be an interesting fact, a "now you know", or "next
  time you're on a plane, try the tomato juice and see if you can sense
  the different flavour". The one thing it can't be is "next time, on
  this channel, we talk about X".

## Why the thumbnails looked alike

Every film thumbnail came out of one composer: the subject on the left,
words on a dark panel on the right. The A/B options of decision 114
changed only the words and the picture. Decision 083's tests could only
nudge text size, accent colour and tilt.

## Decision

**Styles** (`pipeline/documentary/thumb_styles.py`):
- **Seven whole styles to test against each other:**
  - Side panel: the original, drawn exactly as before;
  - Bottom band;
  - Sticker;
  - Text over picture;
  - Big centred;
  - Classic serif;
  - Playful.
- **What they vary:**
  - layout;
  - font (Segoe UI Black, Impact, Arial Black, Bahnschrift Condensed,
    Georgia, Rockwell, Gill Sans Ultra);
  - colours (accent and white, white, accent, dark on accent, yellow
    pop);
  - tilt;
  - the picture (the film's close-up art or a wide storyboard scene);
  - text edge and colour grade.
- **Fitting the words:** each style picks the line split (one line, two,
  or a word to a line) that lets the words be biggest, and short words
  never stand alone.

**Three phases, per channel** (`core.thumbnail_tests`, documentary
rounds):
1. **Style.** Each film's test pits the champion style against the two
   least-tried styles. Rounds still running count, so films tested side
   by side try different styles. A style that wins becomes the champion.
   Once it has seen off challengers twice, or every style has been tried
   and it has won twice, the channel moves on.
2. **Refine.** The champion against itself with one setting changed:
   text size, tilt, colours, font, picture, edge or grade. A change that
   wins is kept, and a setting that just won is pushed further. After
   four rounds the channel moves on.
3. **Content.** The house style throughout; each film tests its own
   words and title from its pitch's next angles, and the third variant
   also gets a newly drawn picture of its angle's idea (about 3¢). Studio
   runs these as "Title and thumbnail".

**How a test works for the owner:**
- The owner ticks Studio's winner on the film's page, as decision 083
  already allowed. The page now shows each variant's style in words, the
  phase, a title to copy beside each content-round thumbnail, and a
  "Test in Studio ↗" link.
- Each film's test is made at the video stage. For the four films
  already out, the style tests were made by hand, and between them they
  cover all seven styles.

**Every film's own thumbnail is drawn in the house style**
(`thumbnail_tests.house_style`), at the video stage and when a film is
retitled. Until a test says otherwise, that's the original side panel.

**Removed:** decision 114's A/B options (their page section, route and
image folders).

**Endings** (`editor.FINAL`, the script writer, the overseer's
checklist):
- **What counts:** the last line has to close the film and make sense on
  its own. It may be the answer said plainly, a last "now you know", or
  a "next time you..." the viewer can notice or try. It needn't repeat
  the title.
- **What fails:** cryptic images, instructions without their context,
  questions, morals, "subscribe" and "next time on this channel".
- **How it's checked:** the check now writes down the viewer's takeaway
  instead of the title's answer.
- **Tried on four films:**
  - airline food: "Next time you fly, try the tomato juice: thirty
    thousand feet up, it's one of the few things still full strength.";
  - Velcro: "So next time you rip your shoe open, that satisfying tear is
    just a weed's oldest trick, still working.";
  - clocks and "bless you": both kept.
