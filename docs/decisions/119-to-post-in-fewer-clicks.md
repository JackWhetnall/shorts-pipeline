# 119 — To post: open once, copy three things, never post twice

**Status:** active. Refines decision [059](059-posting-steps.md)'s steps.

## What the owner said

- Instagram should come above TikTok for each video.
- The Open Instagram and Open TikTok buttons are needed once, at the top
  right, not on every video.
- The buttons go: copy the video's location, copy the thumbnail, copy
  the caption. "Again" isn't needed.
- Drop the paragraph about where the video is.
- The link box should be there to type in, without a click to open it,
  and without long placeholder text.
- They posted one clip twice after getting distracted. A copy button
  should turn green once used and still work. Leaving with a post half
  done should ask "1 manual video upload in progress, are you sure you
  want to leave?", with the right number.

## Decision

- **Order:** a video's platforms are listed Instagram first (`posting.ORDER`).
- **Opening:** To post opens each platform's upload page once per channel,
  in the channel's browser profile (`posting.open_upload`,
  `/api/channels/<key>/open-upload`), from the page's top right. A
  video's own page keeps its Open button, since it shows one video.
- **Copying:**
  - **Copy thumbnail** copies the cover's location (a quiz short's cover,
    else the video's thumbnail), for each platform's cover picker
    (`posting.thumbnail_of`).
  - The steps are short labels: select the video, the cover, the
    caption, then post.
  - The link box is always shown ("Instagram link (optional)") beside
    **I've posted it**.
- **Never twice:**
  - A copy button that's been used turns green, kept in the browser per
    video and platform until it's marked posted.
  - A link inside the app asks first, with the count, while any post on
    the page is half done.
  - Closing or reloading the tab asks too, in the browser's own words:
    browsers don't allow a page to set that message.
