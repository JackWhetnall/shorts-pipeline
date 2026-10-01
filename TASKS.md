# Your tasks

Things only you can do: account steps, console settings, decisions and
testing. Kept up to date as the app changes. Do them top to bottom;
each says why it matters. Done items move to the bottom with a date.

*Last updated: 30 Sep 2026. For now only The Pub Quiz Round publishes.
New: check a quiz's questions one by one and swap out the bad ones (step
4d), and the app on your phone (step 4e). Also a guided animation style
builder for narrated channels (its own section below the quiz list).*

---

## Launching The Pub Quiz Round, in order

Where it stands: 73 rounds planned, three shorts and one long quiz
waiting in Review, a logo chosen. Nothing publishing-related is set up
yet: no YouTube channel connected, its publishing plan is off and
automatic publishing is off. Nothing will go out until you get to step 12.

What "automatic" means here: **YouTube only** is fully automatic (shorts
and long quizzes). TikTok and Instagram are one-minute manual posts the
app sets up for you (step 15).

### 1. Send the latest work to GitHub (1 minute)
The latest commits exist only on this PC (`git status` says how many).
```
git push
```
Run it in the project folder (`C:\Users\JackW\Documents\YT`).

### 2. Keep the PC awake (1 minute, once)
The app makes and uploads videos only while it's running and the PC is
awake. It's running now (I started it on 28 Sep, and it starts itself at
every login). **Windows Settings → System → Power → Screen, sleep &
hibernate timeouts**: set *When plugged in, put my device to sleep after*
to **Never**. The screen can still turn off.

If it ever stops, start it again. In Git Bash, `/` is read as a path, so
it needs doubling:
```
schtasks //Run //TN "Shorts Pipeline"
```

### 3. Decide the voice allowance (the one real limit)
ElevenLabs Starter gives **30,000 characters a month**. This month you've
used 4,381, and it resets on **7 Oct**. A quiz short takes about
1,150–1,470 characters (ten questions and answers is a lot of talking).
A long quiz takes about 600, because it reuses the shorts' audio.
- **Stay on Starter: 4 shorts a week** (about 22,000 a month) plus a long
  quiz a fortnight. This leaves room for retries.
- **Upgrade to Creator (100,000 a month)** for daily shorts (about
  40,000). Check the price on your ElevenLabs subscription page first.

My suggestion: start on Starter at 4 a week while you're still reviewing
(steps 13–14), then upgrade once it runs clean, if daily looks worth it.
The app refuses a video it can't afford rather than failing half-way.

### 4. Choose the music and the clock (5 minutes)
The music buttons work now: they were dead on quiz channels.
1. Its two tracks are *Cinematic Ambient* and *Drops*, which are moody
   for a pub quiz. **Settings → Music & sound → Suggest tracks**, listen,
   **Add** two or three lighter ones and **Remove** what doesn't fit. Or
   untick **Music** and let the clock carry it. Long quizzes cycle through
   the same tracks. The suggestions can still lean ambient; tell me if
   none suit.
2. **The clock**: pick the tick (the default is now a soft knock; the old
   one is *Wooden tick*) and its level, and press **Listen**. **Save
   changes**.

### 4b. Let the question bank and fact store fill (nothing to do but leave the app running)
Rounds now come from a **question bank** of classic pub-quiz questions,
written and checked ahead (the **Facts** page in the sidebar), and fall
back to stored Wikidata facts. The bank tops itself up hourly, up to
$1.50 a day, about 400 questions: a full first stock (about 2,000 across
the categories) takes four or five days and about $7. **Write more
questions now** on that page starts a run straight away. Science already
has about 70.
The fact store (below) fills alongside it. The app is already filling it by itself in the background (it
started on 28 Sep): each category takes about 10 minutes and a cent, so
the fifteen take a few hours. Leave the app running. The **Facts** page
shows each category's facts and progress; **Stock every quiz category
now** does the same thing if it's ever idle. A category it can't map
(like Word Play) keeps being written the old way.
Once a few categories are in, try **Add it** with one of your own (e.g.
"Harry Potter") to see a new category tagged and filled, and make a
short or two to hear the questions.

### 4b-ii. Approving now sticks; see each channel's Videos page
Approved videos used to bounce back to Review because the publishing plan
was off. Now they wait as "Approved, ready to publish" until the plan is
on (step 12) and YouTube is connected (step 8). The channel dashboard's
video tile opens its **Videos** page: waiting for review, approved,
published, discarded, with Approve and Back to review buttons. Re-approve
the video that bounced back.

### 4c. Clear the old written scripts (1 minute)
Thirteen quiz rounds were written ahead by earlier versions (before the
question bank and the difficulty fix). **Topic plan → Clear written
scripts (13)**. Each is written afresh from the bank when its video is
made. Discard any quiz still in Review that came from them.

### 4c-ii. Anthropic credit (2 minutes)
On 1 Oct the app's Anthropic key still reported "credit balance is too low"
after you'd added credit, so the credit probably went to a different
organisation from the one the key belongs to. At
<https://console.anthropic.com> → **Plans & Billing**, check the organisation
shown in the top-left is the one whose key is in your `ANTHROPIC_API_KEY`
(**API keys** page lists the keys per organisation/workspace). Then press
**Retry** on the failed Mythology attempt, or **Discard this attempt** to
start fresh. The two shorts made while credit was out (Sport: Tricky) had
their automatic checks skipped, so watch that one yourself.

### 4d. Check a round's questions (5 minutes)
Each question can now be judged on its own, with a bad one swapped out
rather than the whole round written again.
1. In **Review**, open one of the quiz shorts waiting, and click **Check
   the questions**. You'll see just the questions and answers, with how
   many adults the rater thinks would know each one.
2. For each question:
   - **Fine** keeps it.
   - **Too easy** or **Too hard** moves it in the bank to the next easier
     or harder level, where a round at that level can use it, and swaps
     in another.
   - **Wrong or no good** (with a reason if you like) takes it out of the
     bank for good and swaps in another.

   **All the rest are fine** clears the others in one go.
3. If you swapped any, press **Remake with these changes**. The short is
   discarded and made again with the same number. The shorts waiting now
   were made before this existed, so their remake voices the whole round
   once (about one short's worth of voice characters). From now on a
   remake voices only the lines that changed.

Rounds written ahead of their video can be checked the same way before
they're made: **Topic plan → Check questions** beside the round. Create
video isn't affected: it still writes and makes without stopping.

### 4d-ii. Remake the country round (2 minutes)
Long picture questions now wrap instead of running off the card. To get
that into the country round already made: in **Review**, open it and
press **Remake as is**, then **Remake it**. It keeps the script, the number
(#5) and the voice (nothing is voiced again); only the board is filmed
again. The old one is discarded for you.

The same button works on any video from now on. If one animated shot or
illustration comes back wrong, tick just that part on the remake page
(with **Draw its picture again too** if the picture itself is wrong, not
only the movement). Everything else, voice and footage included, is
kept. Videos made before today can only be remade this way if they're
quiz shorts.

### 4d-iii. Publish by hand, in one click (and the channel profile)
Open an approved video (**Videos** page, or Review). The **Publish** card
shows its title and description to check and edit, then **Publish now**
uploads to YouTube through the API, and opens TikTok and Instagram in the
channel's browser profile with the video selected in its folder and the
caption on your clipboard. Post it on each, then **To post** → mark
posted. YouTube has to be connected first (step 8). **Show the file**
opens its folder with it selected, and **Download** names it by its title.

The channel's dashboard has a new step, **Write the channel description
and make the banner**. It needs the Anthropic credit working (4c-ii) for
the words (about a cent); the banner is free. On the page: paste the
About text and keywords into YouTube Studio → Customisation, the bios
into TikTok and Instagram, and upload the banner (Studio → Customisation
→ Branding). Put your YouTube, TikTok and Instagram links in **Settings →
Publishing** (and Patreon or merch in **Money**) first, and they appear
in the text.

### 4e. Use it from your phone (5 minutes, optional)
1. On the PC, click **Phone** in the top bar, then **Turn on phone
   access**. The app restarts itself within a minute (once nothing is
   being made), and the page then shows an address like
   `http://192.168.1.23:5000/m` and a six-digit code.
2. Let the phone through Windows Firewall, once. I can't change system
   settings for you. Open PowerShell with **Run as administrator** (Start,
   type PowerShell, right-click, Run as administrator), then:
   ```
   netsh advfirewall firewall add rule name="Shorts Pipeline (phone)" dir=in action=allow protocol=TCP localport=5000 profile=private
   ```
   That allows it on private networks only. If Windows has your home
   Wi-Fi marked as **Public**, switch it to **Private**: Settings, Network
   & internet, Wi-Fi, your network's properties.
3. On the phone, on the same Wi-Fi, open that address and enter the code.
   The phone stays signed in; **New code** on the PC signs every phone out.
   Adding it to your home screen makes it feel like an app (Share → Add to
   Home Screen on iPhone; ⋮ → Add to Home screen on Android).

From the phone you can see what's being made, watch and approve or discard
what's waiting, check a quiz's questions (and remake), and start the next
video or pick one from the plan. **Full app** opens everything else.
Don't forward the port on your router: this is for your home network
only.

### 5. Clear Review, then make a few new shorts (20 minutes)
1. **Discard** the 7-minute long quiz. It has the old, quick timing.
2. The shorts waiting now were made before the hook screen and numbers
   (and the Impossible one's "failed" checks were the checks' mistakes,
   fixed on 28 Sep). Approve or discard them as you'd judge them; they
   have no number on the board. Each decision counts towards step 13.
3. Make two or three new shorts from **Create video**: the first is **#1**
   (the number box is prefilled; change it only to remake a discarded
   number). Watch the opening: the hook appears word by word, then the
   category is stamped under it. Tell me what you think before more are
   made.
4. The **long quiz** option appears on Create video once there are
   enough *approved* shorts for one (six by default). It makes both
   formats, and both come to Review: publish the one you prefer.

### 6. Create the YouTube channel (10 minutes)
Make it a second channel on the same Google account as Minute Pastor.
It's then a "brand channel" with its own name, and you don't need a new
Gmail.
1. On <https://www.youtube.com/>, signed in as that account: your
   picture (top right) → **Settings** → **Add or manage your
   channel(s)** → **Create a channel**. Name it **The Pub Quiz Round**.
2. **YouTube Studio → Customization**:
   - *Basic info*: a handle (e.g. `@ThePubQuizRound`), a one-line
     description ("A new pub quiz round every day: ten questions,
     easy to impossible."), and your contact email if you want one shown.
   - *Branding → Picture*: upload the logo. It's at
     `channels\the_pub_quiz_round\logo\logo.png` in the project folder.
     A banner is optional; ask me if you want one made.
   - **Publish** (top right).
3. **Studio → Settings**:
   - *Channel → Basic info*: Country = United Kingdom.
   - *Channel → Advanced settings*: **No, set this channel as not made
     for kids** (the app says so on every upload too).
   - *Upload defaults*: Category **Entertainment**, language English.
4. **Verify the channel by phone**: <https://www.youtube.com/verify>.
   It's needed for custom thumbnails (long quizzes have their own) and
   for videos over 15 minutes. Without it YouTube picks a frame.
5. Copy the channel's address (e.g. `https://www.youtube.com/@ThePubQuizRound`)
   into the app: **Settings → Publishing → Where this channel lives →
   YouTube**, then **Save changes**. It's for your reference; nothing
   published reads it.

### 7. Check the Google consent screen is published (2 minutes)
If it's still in Testing, Google cuts every connection off after 7 days
and uploads quietly stop. Minute Pastor was connected on 24 Sep, so if
it's in Testing that connection dies around 1 Oct.
1. <https://console.cloud.google.com/> → your project → **Google Auth
   Platform → Audience** (older layout: *OAuth consent screen*).
2. If *Publishing status* says **Testing**, click **Publish app** and
   confirm. Google now insists on a **homepage and a privacy policy URL**
   first (my earlier "leave them empty" was out of date). Do step 7a to
   get those. When you next connect, Google shows "Google hasn't verified
   this app". That's expected for a personal tool: **Advanced → Go to (app
   name)**.
3. If it already says **In production**, nothing to do.

### 7a. Make the homepage and privacy policy pages (10 minutes)
Google needs two public web addresses. I've written the pages (the
`site` folder in the project); they just need putting on the web. GitHub
Pages does that for free. Use a **new, separate public repository**, not
your main one, so the project itself stays private.
1. Open `site\privacy.html` in a text editor and replace
   `REPLACE-WITH-YOUR-SUPPORT-EMAIL` with your support email (the one in
   the Google console). That address will be public on the page.
2. <https://github.com/new> → name it `shorts-pipeline-site`, **Public**,
   tick *Add a README*, **Create repository**.
3. On its page: **Add file → Upload files**, drag in `index.html` and
   `privacy.html` from the `site` folder, **Commit changes**.
4. **Settings → Pages**: *Source* = **Deploy from a branch**, *Branch* =
   **main**, folder **/ (root)**, **Save**. After a minute or two the page
   shows its address, which will be
   `https://jackwhetnall.github.io/shorts-pipeline-site/`. Open it and
   `.../privacy.html` to check they load.
5. In the Google console, **Google Auth Platform → Branding**: set
   *Application home page* to the first address and *Application privacy
   policy link* to `.../privacy.html`. If it asks for an *Authorized
   domain*, add `jackwhetnall.github.io`. Make sure the app name matches
   the one on the page ("Shorts Pipeline") or change the page's title to
   whatever you called it. **Save**.
6. Back in **Audience**, **Publish app** again.

### 8. Connect the channel to the app (2 minutes)
**The Pub Quiz Round → Settings → Publishing → Automatic YouTube uploads
→ Connect this channel.** In Google's chooser, pick **The Pub Quiz
Round**, not your own name or Minute Pastor. That choice decides where
uploads go. Afterwards it should show as connected. If it names the
wrong channel, disconnect and connect again.

### 9. One test upload (5 minutes)
1. In **Review**, open an approved short → **Upload to YouTube**.
2. In **Studio → Content** it arrives **private**. This is Google's rule
   for apps that haven't passed the audit (step 10), not a fault. Check
   the title, description and hashtags look right.
3. Take 2–3 screenshots: the app's upload button, the video in Studio,
   and the connect screen. Step 10 wants them.
4. Make it **Public** if you're happy, or leave it private as a test.

### 10. Apply for the YouTube API audit (20 minutes, then a few weeks' wait)
Until this passes, every upload lands private and needs one click in
Studio (step 14). This is what stands between you and fully hands-off.
1. Form: <https://support.google.com/youtube/contact/yt_api_form>
   (*YouTube API Services – Audit and Quota Extension*).
2. Describe it as a personal tool that uploads your own videos to your
   own channels, with no other users. Scopes: upload, and read-only
   statistics. Attach the screenshots from step 9.
3. If it asks for a privacy policy URL, tell me and I'll write one.
4. When it's approved, mark **Pass Google's API audit** done under the
   channel's **Grow** list.

### 11. Set the quiz settings (5 minutes)
**Settings → Channel**, under the quiz format:
- **Difficulty levels**: each has its number on the 1-10 scale now (Hard
  is 5.5). Change a number to make that level easier or harder; add or
  remove levels here.
- **Shorts**, **Answers as you go** and **Answers at the end** each have
  their own clock and pauses. The long ones start at a 10-second clock.
- **Long quizzes → Make one automatically every**: `14` days on Starter
  (each needs six rounds not yet used in the mixed series), `7` if you
  upgraded. It's off (0) now.
- **Format for review**: *Alternate* publishes both formats over time
  (different rounds each), so you'll see which does better. Both are
  always made either way.
- Leave *a category's own quiz* ticked. Science Quiz #1 etc. will come
  once a category has all its levels out.

### 12. Turn on the publishing plan (5 minutes)
**Settings → Publishing → When it publishes**:
- Tick **Run this channel on its own**.
- **Publish at**: `18:00`.
- **On**: Mon, Tue, Thu, Fri on Starter, or every day if you upgraded.
- **Keep this many ready**: `2`.
- **Long quizzes**: Saturday `19:00` (already set).

**Save changes.** On the dashboard, *Right now* should say it will start
a video at the next check (within five minutes). From here it makes
videos by itself, adding rounds to the topic plan when it runs low, and
**queues them for you** until step 14.

### 13. Shadow run: review the next five
The app wants to see that its automatic checks agree with you before it
offers to publish on its own. In **Review**, decide as normal. After five
decisions (the three in step 5 count) the Launch card moves on if the
checks agreed with you on at least four. Tell me about any verdict you
disagreed with: that's the best feedback for tuning the checks.

### 14. Switch on automatic publishing
Once the Launch card offers it: **Settings → Publishing → Publish
automatically → Upload it if it passes every automatic check**. Leave
**Hold every Nth clean video for me anyway** at `5`.

What's left for you each day after that:
- **Until the audit passes**: one click. The day's upload arrives private,
  so set it **Public** in Studio. The YouTube Studio phone app works.
- **Every 5th short, anything flagged, and every long quiz** wait in
  Review. Long quizzes always wait, because they're 10+ minutes.
- **After the audit**: nothing else. Uploads go out public at the slot.

### 15. Optional: TikTok and Instagram
Worth adding once YouTube runs by itself. It's shorts only, and each
post takes about a minute by hand.
1. Create the accounts yourself (the phone apps are easiest): TikTok, and
   an Instagram account for the channel. Use the same name and logo.
2. **Settings → Publishing → TikTok and Instagram → Make a profile for
   this channel and sign in.** In the Chrome window that opens, sign in
   to those two accounts. It remembers them.
3. Tick **Also post each one to TikTok / Instagram from this PC**, then
   **Save changes**.
4. Put their addresses in **Settings → Publishing → Where this channel lives**.
5. To post: in Review, **Open TikTok upload**. Chrome opens as the
   channel with the video selected in Explorer. Drag it in, press Ctrl+V
   for the caption, then post.

## Animation (29-30 Sep)

A narrated channel's animated **style** is now built from eight plain
questions, each offering only what makes sense after your answers so far
(decisions 053, 054). There are 34 ready-made starting points, from felt
science and meeple logic puzzles to stubby paper history and minimal
maths on black (modelled on Quant_Prof). You can also describe a style in
your own words. Nothing changes on a channel until you switch it on.

Most styles are **composited**: a few cents a video, no new account.
Styles acted out in shots use a video model (about $4 a video) and need a
fal key (D). The builder marks which is which.

### A. Look through the starting points (5 minutes)
**Settings > Animation > Start from an example.** Each card is a real
frame from the renderer on a subject of its own. Tell me which ones are
wrong or weak; they're the easiest thing to tune.

### B. Build a style for one channel (10 minutes)
**Settings > Animation** on the channel:
1. **Start from an example** or **Describe it in your own words**, or just
   answer the questions from the top.
2. Change any answer. Later questions only offer what fits, and if a
   change rules out a later answer, it says what it changed. **Material**
   shows four example pictures of each; **See larger** steps through them.
3. **See this style** makes a real frame of exactly that style on the
   channel's subject (about a minute, 5-15 cents the first time, then
   cached). Switch **Vertical short / Widescreen** to see the widescreen
   version (it reuses the same moment, so it's nearly free). **Make it
   move** films a few seconds (free for composited styles; a video-model
   style needs the fal key).
4. Optional: **style notes**, **colours**, and a **cast** (the first is
   the host, for styles with one).
5. **Save changes**, then **Make an animatic** or **Animate it** on one of
   the channel's videos to see a whole video in the style.

Suggestions:
- **Curiosity Leak**: *Felt science table*, or *Minimal 3D in white space*.
- **Wren's Guide**: *Cosy felt craft* or *Knitted wellbeing*.
- **Minute Pastor**: *Engraved legends* or *Stubby paper history* (a
  puppet play, composited), or *Storybook scripture* once there's a fal key.
- **A maths or puzzle channel**: *Minimal maths on black* or *Meeple logic
  puzzles*.

### C. Switch it on
**Animate this channel's pictures in its own style** (top of Animation).
Then, in **Pictures**, set the slider to **Always** to animate the whole
video. On a composited style that's the right setting: it draws its own
diagrams and labels.

### D. Only for video-model styles: a fal account and key (10 minutes)
The video models run on fal. OpenAI's Sora was shut down on 24 Sep.
1. <https://fal.ai> > **Sign in** (Google or GitHub).
2. **Dashboard > Billing**: add credit. $20 is several test videos; a
   fully animated 50-second video is about $4 at the default settings.
3. **Dashboard > Keys > Create key** (scope: API). Copy it.
4. Save it as a Windows user variable: **Start > "Edit environment
   variables for your account" > New**. Name `FAL_KEY`, value the key.
5. Sign out of Windows and back in, so the app restarts with it. **APIs**
   should show fal as set.

### E. Decide about long widescreen explainers
Every style can now render widescreen as well as vertical, but nothing
yet makes a longer, more in-depth widescreen version of a video (its own
script, assembly and upload slot). Say if you want that built, and for
which channel first.

## Other channels (on hold while the quiz launches)

None of these block the quiz. Pick them up when a second channel
comes back.

### Check the hook styles I wrote for your channels
Every video now opens with a hook and ends with a proper landing. How
each channel's hook *sounds* is a setting: **Settings → How it hooks**,
just under the style prompt. I wrote one for Minute Pastor, Wren's Guide
and Shakespeare Lines to fit their style prompts. Read them and adjust
the wording to your taste; they steer every future script.

Minute Pastor's videos now begin with one spoken line **before** the
verse. Try **Preview a script** on its settings page (about a penny) to
see a few.

### Try a few script previews
The hook rules were rewritten after the Pythagoras video (decision 037).
On a channel's settings page, **Preview a script** (about 2 cents; no
voice, no video) shows the new hooks. Tell me which ones would and
wouldn't stop you scrolling; that's the fastest way to tune them.

### Choose music for each channel (5 minutes each)
Each channel's **Settings → Music & sound** has the tracks: press **Suggest
tracks**, listen, and **Add** the ones that suit it (3-6 is plenty). If
you skip this, the app fetches the best three itself at the channel's
next video. Tracks are openly licensed and credited automatically where
needed, and no two channels share one. Listen before adding: titles can
mislead, and a track that turns out to carry a Content ID claim should
be removed.

### Allow paintings on Minute Pastor (and Wren's, maybe)
Settings → Pictures → **Paintings and engravings**: tick it. The director
can then use a classic public-domain painting or engraving (from the Art
Institute of Chicago and the Met) for any segment one shows well: a Bible
scene, a myth, a historical moment. Credited in the description. It's no
longer tied to the verse, and the slider doesn't limit it. Off until you
switch it on.

### Curiosity Leak: lower its graphics slider
It's set to "Always animated", which the new rules say is wrong for a
subject that can be filmed (people, animals, everyday life): real
footage of a dog yawning beats any graphic. In its **Settings →
Graphics**, drag the slider to about 40 ("When it clearly helps") and
**Save changes**. Press **See the motion graphics
in this look** to see what its graphics will look like.

### Decide scenes for your existing channels
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

### Try the channel pitch
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
   The next steps are the same as the quiz's (steps 3–14 above).

Tell me what the draft got wrong. The drafting prompt is the thing to
tune.

## Decisions for later (no rush)

- **Which channel next?** Minute Pastor is connected and its numbers are
  arriving; Wren's Guide is still being tuned. Either needs its own share
  of the voice allowance (quiz step 3).
- **A maths channel?** The Pythagoras demo's draft is ready to accept if
  the video convinced you. It would be the first channel built around
  animated scenes.

---

## Done

- 27 Sep: The Pub Quiz Round reviewed as a test channel; dingbats removed.

- 24 Sep: ElevenLabs key has `user_read`; the quota shows on `/apis`.
- 24 Sep: YouTube Analytics API enabled and Minute Pastor reconnected;
  numbers are arriving (Revelation 11:15: 42 views, 27% viewed).
- 23 Sep: GitHub repo created and first push.
- 23 Sep: Google OAuth client created and Minute Pastor connected.
