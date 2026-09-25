# Your tasks

Things only you can do: account steps, console settings, decisions and
testing. Kept up to date as the app changes. Do them top to bottom;
each says why it matters. Done items move to the bottom with a date.

*Last updated: 25 Sep 2026 (afternoon).*

---

## Now (5 minutes)

### 1. Send the latest work to GitHub
The newest commits exist only on this PC until pushed (`git status` says
how many).
```
git push
```
Run it in the project folder (`C:\Users\JackW\Documents\YT`).

### 2. Switch to the new version of the app (last time by hand)
The copy you started by hand is running old code.
From now on the app restarts itself onto new code whenever it's idle,
so this is the last manual restart. It's needed once because the copy
running now predates that feature, which is why Curiosity Leak's video
failed. After restarting, retry that video from the Activity page: its
script and voiceover are reused, so it doesn't pay for them again.
1. Close the terminal window running `python -m web` (or press Ctrl+C in
   it), or end the `pythonw` process in Task Manager.
2. Start the new one the way it will start at every login from now on:
   ```
   schtasks /Run /TN "Shorts Pipeline"
   ```
3. Open <http://127.0.0.1:5000/>. If it doesn't load within about ten
   seconds, open `cache\web.log` in the project folder and send me the
   last few lines.

### 2b. Check the hook styles I wrote for your channels
Every video now opens with a hook and ends with a proper landing. How
each channel's hook *sounds* is a setting: **Settings → How it hooks**,
just under the style prompt. I wrote one for Minute Pastor, Wren's Guide
and Shakespeare Lines to fit their style prompts. Read them and adjust
the wording to your taste; they steer every future script.

Minute Pastor's videos now begin with one spoken line **before** the
verse. Try **Preview a script** on its settings page (about a penny) to
see a few.

### 2b-ii. Try a few script previews
The hook rules were rewritten after the Pythagoras video (decision 037).
On a channel's settings page, **Preview a script** (about 2 cents; no
voice, no video) shows the new hooks. Tell me which ones would and
wouldn't stop you scrolling; that's the fastest way to tune them.

### 2b-iii. Choose music for each channel (5 minutes each)
Each channel's **Settings → Music & sound** has the tracks: press **Suggest
tracks**, listen, and **Add** the ones that suit it (3-6 is plenty). If
you skip this, the app fetches the best three itself at the channel's
next video. Tracks are openly licensed and credited automatically where
needed, and no two channels share one. Listen before adding: titles can
mislead, and a track that turns out to carry a Content ID claim should
be removed.

### 2b-iv. Try Paintings on Minute Pastor
Settings → Look → **Paintings**: tick "Show a public-domain painting of
the passage". Each verse is then read over a classic painting or
engraving of it (from the Art Institute of Chicago and the Met),
credited in the description. Off until you switch it on.

### 2b-v. Curiosity Leak: lower its graphics slider
It's set to "Always animated", which the new rules say is wrong for a
subject that can be filmed (people, animals, everyday life): real
footage of a dog yawning beats any graphic. In its **Settings →
Graphics**, drag the slider to about 40 ("When it clearly helps") and
**Save changes**. Press **See the motion graphics
in this look** to see what its graphics will look like.

### 2c. Decide scenes for your existing channels
Every existing channel is **stock only** until you change it. Each
channel's **Settings → Graphics** has a slider
for when a segment gets an animation instead of stock footage (a
threshold on how much it needs one), and the look (four starting presets, then
your own colours, fonts and drawing style), with a preview.
- **Wren's Guide**: try the slider a little off the left ("Only when
  essential" or "When it clearly helps"), with the Parchment look.
- **Minute Pastor**: always stock, or just off the left. It's reflective, and stock footage
  suits it; a scene now and then for a structure (a list, a timeline)
  could help.

Scenes cost about 5-6 cents each, plus about 4 cents the first time a
channel needs an illustrated object (reused after that). The voice
quota is unaffected.

### 2d. Look over The Pub Quiz Round (new: made from your pitch)
I set it up through the pitch page, as you would, so it's worth browsing
as if it were yours. Its dashboard, **Settings** (the Channel section has
the quiz's own settings) and **Topic plan** (15 categories × 5
difficulties = 75 quizzes) are all live.
1. **Settings → Voice & timing**: it's on *Roger (laid-back, casual)*. Press the
   Voice Lab's **Listen** if you want to compare Will or Chris, the
   draft's other two picks.
2. **Settings → Music & sound → Suggest tracks**: the suggestions I saw
   were cinematic and moody, not pub-quiz. Pick something light, or
   untick *Music* and let the clock carry it.
3. **Make one video** (Create video on its dashboard) when you're happy
   to spend about 1,150 ElevenLabs characters (about 4% of the month) and
   about 10 cents. I've tested every part without the voice, but not a
   real voiced render. Watch for: the countdown's timing, whether the
   ticks are loud enough, and whether any answer is wrong. Every answer
   is fact-checked first, and a video with a doubtful one waits for you.
4. Its difficulty levels are Easy, Medium, Hard, Fiendish, Impossible
   (the draft's choice). Change them in **Settings → Channel** if you'd
   rather say "Very hard".

## When you have time to focus (testing the automation)

### 3. Set Minute Pastor's publishing plan
1. Open **Channels → Minute Pastor**. The **Launch** card should say you're
   on *Set when it publishes*. Click **Do this →**.
2. In **Settings → Publishing → When it publishes**:
   - Tick **Run this channel on its own**.
   - **Publish at**: a time your audience scrolls, e.g. `18:00`.
   - **Keep this many ready**: `3`.
   - Tick **Also post each one to TikTok / Instagram from this PC** if
     you'll post there.
3. **Save changes**. On the dashboard, under *Right now*, it should say it
   will start a video on the next check (within five minutes).

Cost check: the section shows the plan's monthly ElevenLabs characters.
Daily is about 16,400 of your 30,000.

### 4. Give Minute Pastor its own browser profile (for TikTok/Instagram)
So posting always opens the right accounts, already signed in.
1. Minute Pastor's **Settings → Publishing → TikTok and Instagram** →
   **Make a profile for this channel and sign in**.
2. A new Chrome window opens (profile folder "Shorts minute_pastor") on
   TikTok's and Instagram's login pages. Sign in to **Minute Pastor's**
   accounts in that window. Nothing else to do; it remembers them.
3. Optional: in that Chrome window, click the profile icon (top right) →
   rename it "Minute Pastor" so you can tell it apart.
4. Back in Settings, check **Post from** now shows that profile,
   and **Save plan**.

To test: in **Review**, press **Post to TikTok** on a video. Chrome should
open on TikTok's upload page as Minute Pastor, and an Explorer window with
the video selected. Drag it in, press Ctrl+V for the caption. (Don't post
the test unless you mean to.)

### 5. Do the shadow run: review five videos with the checks' verdicts
The app wants to see that its automatic checks agree with you before it
offers to publish on its own.
1. Open **Review**. Each video shows what the checks found, or "Passed
   every automatic check".
2. Decide as you normally would: **Approve** (`A`) or **Discard** (`D`,
   with a reason). Don't let the verdict decide for you; the point is to
   see whether it matches your judgement.
3. After five decisions, the Launch card moves on if the checks agreed
   with you on at least four. Malachi, waiting now, has already passed
   the checks.

Tell me about any verdict you disagreed with. That's the most useful
feedback for tuning the checks.

### 6. Switch on automatic publishing
Once step 5 is done, the Launch card offers it.
**Settings → Publishing → Publish automatically →** "Upload it if it
passes every automatic check". Leave "hold every Nth" at `5`, so one in
five still waits for you as a spot check.

### 7. Try the channel pitch
There's already one draft waiting, made while testing: *"science news for
curious teenagers"*, proposed as **Why Nobody Told You**. It cost 9 cents.
1. **Channels → + New channel**. Under **Drafts waiting for review**,
   open **Why Nobody Told You**. (Or pitch your own idea in the box: it
   takes a minute or two, about ten cents.)
2. Read **What it is** and **Worth knowing**. This one noticed the app has
   no live news feed and turned "science news" into evergreen "strange but
   true" science. Decide whether that's what you want.
3. Go through each card: pick a name, read the style prompt (it's the
   instruction every script is written from; edit freely), play the three
   voice previews and pick one, check the length, pick a colour palette,
   look over the topic plan.
4. Not right? Under **Not right?**, type what to change and **Redraft**.
   Or **Throw this draft away**.
5. **Create this channel** only if you actually want it. It becomes a real
   channel on its launch pipeline, at "Make and approve a first video".
   The next steps are the same as Minute Pastor's (steps 3–6 above).

Tell me what the draft got wrong. The drafting prompt is the thing to
tune.

## Google (do when convenient)

### 8. Make sure the consent screen is published
Without this, Google cuts off the YouTube connection every 7 days and
uploads quietly stop.
1. <https://console.cloud.google.com/> → your project → **Google Auth
   Platform → Audience** (older layout: *OAuth consent screen*).
2. If *Publishing status* says **Testing**, click **Publish app** and
   confirm. Leave the home page, privacy policy and terms fields empty.
3. If it already says **In production**, nothing to do.

### 9. Apply for the YouTube API audit
Until this passes, every upload lands **private** and needs one click in
YouTube Studio to go public. Do it after the first automatic upload, so
you can show it working.
1. Form: <https://support.google.com/youtube/contact/yt_api_form>
   (*YouTube API Services – Audit and Quota Extension*).
2. Describe it as a personal tool uploading your own videos to your own
   channels. Include the API scopes (upload, read-only statistics) and
   2–3 screenshots or a short screen recording of the upload.
3. If it asks for a privacy policy URL, tell me and I'll write one.
4. When it's approved, mark **Pass Google's API audit** done under the
   channel's **Grow** list.

## Decisions for later (no rush)

- **Wren's Guide**: keep going with it, or park it while Minute Pastor
  proves itself? Its Launch card shows its next step.
- **ElevenLabs plan**: Starter covers about one channel posting daily.
  Upgrade only when a second channel needs it.
- **A maths channel?** The Pythagoras demo's draft (step 2b) is ready to
  accept if the video convinces you. It would be the first channel built
  around animated scenes.

---

## Done

- 24 Sep: ElevenLabs key has `user_read`; the quota shows on `/apis`.
- 24 Sep: YouTube Analytics API enabled and Minute Pastor reconnected;
  numbers are arriving (Revelation 11:15: 42 views, 27% viewed).
- 23 Sep: GitHub repo created and first push.
- 23 Sep: Google OAuth client created and Minute Pastor connected.
