# Your tasks

Things only you can do: account steps, console settings, decisions and
testing. Kept up to date as the app changes. Do them top to bottom;
each says why it matters. Done items move to the bottom with a date.

*Last updated: 24 Sep 2026.*

---

## Now (5 minutes)

### 1. Send the latest work to GitHub
The newest commits exist only on this PC until pushed (`git status` says
how many).
```
git push
```
Run it in the project folder (`C:\Users\JackW\Documents\YT`).

### 2. Switch to the new version of the app
The copy you started by hand is running old code.
1. Close the terminal window running `python -m web` (or press Ctrl+C in it).
2. Start the new one the way it will start at every login from now on:
   ```
   schtasks /Run /TN "Shorts Pipeline"
   ```
3. Open <http://127.0.0.1:5000/>. If it doesn't load within about ten
   seconds, open `cache\web.log` in the project folder and send me the
   last few lines.

## When you have time to focus (testing the automation)

### 3. Set Minute Pastor's publishing plan
1. Open **Channels → Minute Pastor**. The **Launch** card should say you're
   on *Set when it publishes*. Click **Do this →**.
2. In **Publishing plan**:
   - Tick **Run this channel on its own**.
   - **Publish at**: a time your audience scrolls, e.g. `18:00`.
   - **Keep this many ready**: `3`.
   - Tick the **TikTok** and/or **Instagram** hand-off if you'll post there.
3. **Save plan**. Under *Right now* it should say it will start a video
   on the next check (within five minutes).

Cost check: the card shows the plan's monthly ElevenLabs characters.
Daily is about 16,400 of your 30,000.

### 4. Check the phone hand-off works (if you ticked it)
1. On your phone, install **OneDrive** and sign in with the same account
   as the PC.
2. Wait for the first video to go out at its slot. Then, in OneDrive on
   the phone, open **Shorts to post → Minute Pastor**. You should see the
   video and a `.txt` caption.
3. Share the video to TikTok or Instagram, paste the caption, and post.
4. On the PC, open **To post** in the top bar and click **Posted on
   TikTok** / **Instagram** (pasting the link is optional but lets the app
   count it). The phone copy is then deleted.

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
- **Generated footage pilot** (diagrams): next on the build list. Worth
  deciding first which maths/science channel it's for; pitching one (step
  7) is a good way to find out. See `docs/specs/generated-footage.md`.

---

## Done

- 24 Sep: ElevenLabs key has `user_read`; the quota shows on `/apis`.
- 24 Sep: YouTube Analytics API enabled and Minute Pastor reconnected;
  numbers are arriving (Revelation 11:15: 42 views, 27% viewed).
- 23 Sep: GitHub repo created and first push.
- 23 Sep: Google OAuth client created and Minute Pastor connected.
