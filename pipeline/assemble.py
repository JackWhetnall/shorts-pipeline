"""
Turning matched footage, narration and word timings into the finished
1080x1920 video.

Each segment's real spoken duration is split into shots capped at the
channel's max shot length, every shot gets its own distinct clip, and
shots are crossfaded at their exact real timestamps — not
shortened-and-concatenated, which drifts captions out of sync as shots
accumulate.

**Caption rendering.** The previous implementation redrew the entire
caption group — wrap, measure, stroke, full-width RGBA buffer — once per
spoken word, purely to move the highlight one word along. A typical
script is ~125 words, so that was ~125 full-width image renders, each
becoming its own layer in a composite that moviepy then evaluated on
every one of ~1,800 output frames. It also reloaded the font inside that
loop, probing the filesystem each time.

Here each group is laid out once and rendered once with every word in the
base colour. The active word is then a small overlay image covering just
that word's box. The number of layers is the same, but nearly all of them
are word-sized instead of full-width, and the expensive part — layout and
wrapping — happens once per group instead of once per word.

Captions and cards are drawn with Pillow directly rather than moviepy's
ImageMagick-backed TextClip, so there's no ImageMagick install to manage.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from core import fonts, job_context
from core.channels import resolve_active_ctas
from core.errors import FootageLibraryError
from core.logging_setup import get_logger
from core.paths import FRAME_HEIGHT as H, FRAME_WIDTH as W
from core.progress import encode_logger
from pipeline.audio import apply_fade, silence_array
from pipeline.plan import Shot

log = get_logger(__name__)

CAPTION_Y = int(H * 0.72)               # lower third
CAPTION_MAX_WIDTH = int(W * 0.9)
CAPTION_LEFT = (W - CAPTION_MAX_WIDTH) // 2

OUTRO_TITLE_SIZE = 84
OUTRO_SUBTEXT_SIZE = 48
END_SCREEN_TEXT_SIZE = 56

@lru_cache(maxsize=32)
def load_font(size: int, face: str = None):
    """The channel's caption face, at one size.

    Cached on (size, face): this is called once per caption group and once
    per word overlay, and re-parsing a TrueType file every time was
    measurable. A face that isn't installed falls back to the default one,
    then to Pillow's built-in bitmap font — a channel configured on a
    machine with Impact still has to render on one without it.
    """
    path = fonts.resolve_or_default(face)
    if path is not None:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            log.warning("Could not load font %s; using the built-in face.", path)
    return ImageFont.load_default()


@lru_cache(maxsize=1)
def _measurer():
    return ImageDraw.Draw(Image.new("RGBA", (1, 1)))


# --- captions ---------------------------------------------------------

def group_words(word_timings: list, pacing) -> list:
    """Chunk words into caption groups that break at sentence ends and at
    real pauses, rather than at a fixed count.

    A fixed count lets a caption straddle a pause — vanishing and
    reappearing mid-group — or run one sentence's end into the next one's
    start.
    """
    groups, current = [], []
    for word in word_timings:
        if current:
            gap = word.start - current[-1].end
            ends_sentence = current[-1].word.rstrip().endswith((".", "!", "?"))
            if (gap > pacing.caption_pause_gap_threshold
                    or ends_sentence
                    or len(current) >= pacing.caption_max_group_size):
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)
    return groups


def wrap_words(words: list, font, max_width: int) -> list:
    """Word-wrap into lines, keeping each line as a list of words rather
    than a joined string, so each word can still be positioned and
    coloured individually."""
    draw = _measurer()
    lines, current = [], []
    for word in words:
        candidate = current + [word]
        if draw.textlength(" ".join(candidate), font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = [word]
    if current:
        lines.append(current)
    return lines


@dataclass
class CaptionLayout:
    """A rendered caption group plus where each word sits inside it, so
    the highlight can be drawn as a small overlay instead of a full
    re-render."""

    image: np.ndarray
    boxes: list          # (x, y, width, height) per word, in image space
    height: int


def layout_caption(words: list, style) -> CaptionLayout:
    """Lay out and render one caption group once, all words in the base
    colour, recording each word's box."""
    font = load_font(style.font_size, style.font_face)
    draw_measure = _measurer()
    lines = wrap_words(words, font, CAPTION_MAX_WIDTH)

    space_width = draw_measure.textlength(" ", font=font)
    line_height = int(style.font_size * 1.3)
    stroke = style.stroke_width
    height = line_height * len(lines) + stroke * 2

    image = Image.new("RGBA", (CAPTION_MAX_WIDTH, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    boxes = []
    for line_index, line_words in enumerate(lines):
        widths = [draw.textlength(w, font=font) for w in line_words]
        line_width = sum(widths) + space_width * (len(line_words) - 1)
        x = (CAPTION_MAX_WIDTH - line_width) / 2
        y = line_index * line_height
        for word, width in zip(line_words, widths):
            draw.text((x, y), word, font=font, fill=style.base_color,
                      stroke_width=stroke, stroke_fill=style.stroke_color)
            boxes.append((x, y, width, line_height))
            x += width + space_width

    return CaptionLayout(image=np.array(image), boxes=boxes, height=height)


def render_word_overlay(word: str, box, style) -> np.ndarray:
    """Just the active word, in the highlight colour, sized to its own
    box plus stroke padding.

    This is what replaces re-rendering the whole caption group for every
    word. It draws one word into an image a few hundred pixels wide
    instead of redrawing the full 972-pixel-wide group.
    """
    font = load_font(style.font_size, style.font_face)
    stroke = style.stroke_width
    _, _, width, line_height = box
    image = Image.new("RGBA", (int(width) + stroke * 2 + 4, line_height + stroke * 2), (0, 0, 0, 0))
    ImageDraw.Draw(image).text(
        (stroke + 2, stroke), word, font=font, fill=style.highlight_color,
        stroke_width=stroke, stroke_fill=style.stroke_color,
    )
    return np.array(image)


def build_caption_clips(word_timings: list, style, pacing) -> list:
    """One long-lived base clip per group, plus one small overlay per
    word.

    Each word's highlight holds until the NEXT word starts rather than
    until its own end. The natural gap between spoken words otherwise
    leaves no clip active at all, which reads as the caption flashing off
    and back on with every word. The last word in a group ends at its own
    end, because the gap after it is the real pause that split the groups
    apart in the first place.
    """
    from moviepy.editor import ImageClip

    clips = []
    for group in group_words(word_timings, pacing):
        layout = layout_caption([w.word for w in group], style)
        group_start = group[0].start
        group_end = group[-1].end

        clips.append(
            ImageClip(layout.image)
            .set_start(group_start).set_end(group_end)
            .set_position(("center", CAPTION_Y))
        )

        for i, word in enumerate(group):
            end = word.end if i == len(group) - 1 else group[i + 1].start
            if end <= word.start or i >= len(layout.boxes):
                continue
            box = layout.boxes[i]
            overlay = render_word_overlay(word.word, box, style)
            x = CAPTION_LEFT + int(box[0]) - style.stroke_width - 2
            y = CAPTION_Y + int(box[1]) - style.stroke_width
            clips.append(
                ImageClip(overlay)
                .set_start(word.start).set_end(end)
                .set_position((x, y))
            )
    return clips


# --- cards ------------------------------------------------------------

def _draw_centered_lines(draw, lines, font, top, line_height, width, fill,
                         stroke_width=0, stroke_fill=None):
    y = top
    for line in lines:
        text = " ".join(line)
        x = (width - draw.textlength(text, font=font)) / 2
        draw.text((x, y), text, font=font, fill=fill,
                  stroke_width=stroke_width, stroke_fill=stroke_fill)
        y += line_height
    return y


TITLE_CARD_SIZE = 92
TITLE_CARD_CHANNEL_SIZE = 44


def card_background(channel_key: str, colour, style,
                    blur: int = None, dim: int = None) -> "Image.Image":
    """The base layer for a title or outro card.

    The channel's own picture when it has one and wants it, the flat
    colour otherwise. Every card in every video sitting on the same
    rectangle is the most obviously templated thing a viewer sees, and a
    picture chosen once per channel costs nothing per video.

    `blur`/`dim` are for the Look settings preview only: a real render
    never passes them, and reads the already-committed, already-edited
    picture exactly as before. Given, they re-derive the picture from its
    untouched original at those values instead — so dragging a slider
    shows what pressing Apply would actually save, before it is saved.

    Best-effort: a missing or unreadable file falls back to the colour
    rather than failing a render that is otherwise finished.
    """
    base = Image.new("RGBA", (W, H), tuple(colour))
    if not getattr(style, "use_background_image", True):
        return base
    try:
        from core import backgrounds

        if blur is not None or dim is not None:
            preview = backgrounds.preview_image(
                channel_key, blur=blur or 0, dim=dim or 0)
            return preview.convert("RGBA") if preview is not None else base

        picture = backgrounds.path(channel_key)
        if not picture.exists():
            return base
        with Image.open(picture) as image:
            return image.convert("RGBA").resize((W, H))
    except Exception:  # noqa: BLE001 - a background is decoration
        log.debug("Could not load the background picture", exc_info=True)
        return base


def render_title_card(channel_display_name: str, title: str, style,
                      channel_key: str = "", topic_title: str = "",
                      background_blur: int = None, background_dim: int = None) -> np.ndarray:
    """An opening card: the channel above, what this video is about below.

    Off unless the channel asks for it. Seconds before the content starts
    are watch time spent on nothing, and short-form is decided in the
    first of them — but a channel whose videos are a series someone works
    through wants the viewer oriented, which is a different trade.

    `topic_title`, when given, adds a third stack between the channel and
    the video's own title — the enclosing syllabus topic, styled like the
    channel line (a breadcrumb, not a second headline) rather than adding
    a whole new set of colour/size settings for one extra line.

    `background_blur`/`background_dim` are for the Look settings preview
    only — see `card_background`. A real render never passes them.
    """
    # The channel line keeps its original proportion to the title line
    # rather than gaining a size setting of its own: the card is one
    # decision, and the ratio was already what the card is supposed to
    # look like.
    title_size = int(getattr(style, "title_card_font_size", TITLE_CARD_SIZE))
    channel_size = max(12, round(title_size * TITLE_CARD_CHANNEL_SIZE / TITLE_CARD_SIZE))
    title_stroke = int(getattr(style, "title_card_stroke_width", 3))
    channel_stroke = max(0, title_stroke - 1)

    font_title = load_font(title_size, style.font_face)
    font_channel = load_font(channel_size, style.font_face)
    max_width = int(W * 0.82)

    image = card_background(channel_key, style.title_card_bg_color, style,
                            background_blur, background_dim)
    draw = ImageDraw.Draw(image)

    channel_lines = wrap_words(channel_display_name.split(), font_channel, max_width)
    topic_lines = wrap_words(topic_title.split(), font_channel, max_width) if topic_title else []
    title_lines = wrap_words(title.split(), font_title, max_width)
    channel_height = int(channel_size * 1.3)
    title_height = int(title_size * 1.25)
    gap = 48

    total = (channel_height * (len(channel_lines) + len(topic_lines)) + gap
             + title_height * len(title_lines))
    y = (H - total) / 2
    y = _draw_centered_lines(draw, channel_lines, font_channel, y, channel_height,
                             W, style.title_card_channel_color, channel_stroke, "black")
    if topic_lines:
        y = _draw_centered_lines(draw, topic_lines, font_channel, y, channel_height,
                                 W, style.title_card_channel_color, channel_stroke, "black")
    # A stroke on both, because the card may be sitting on a photograph
    # and a colour that reads on flat black can vanish on one.
    _draw_centered_lines(draw, title_lines, font_title, y + gap, title_height, W,
                         style.title_card_title_color, title_stroke, "black")
    return np.array(image)


def _topic_title_for_card(channel, seed) -> str:
    """The enclosing topic's title, for the title card's optional third
    line. `seed.topic_id` is a subtopic's id (see `pipeline.plan.Seed`'s
    own docstring), so this is one hop up: subtopic row -> its topic
    row. Empty whenever there's nothing to show — a quote channel, a
    flat topic list with no syllabus, or a stale id — never an error;
    the card still renders with just the channel and video title.
    """
    if channel.content_mode != "topic" or not seed.topic_id:
        return ""
    from core import curriculum
    if not curriculum.exists(channel.key):
        return ""
    row = curriculum.find(channel.key, seed.topic_id)
    topic = curriculum.find_topic(channel.key, row["topic"]) if row else None
    return topic["title"] if topic else ""


def render_outro(channel_display_name: str, subtext: str, style,
                 channel_key: str = "",
                 background_blur: int = None, background_dim: int = None) -> np.ndarray:
    """The channel-branded end card.

    `background_blur`/`background_dim` are for the Look settings preview
    only — see `card_background`. A real render never passes them.
    """
    # The subtext line keeps its original proportion to the title line,
    # same reasoning as the title card's channel line: one size decision,
    # not two. Both default to the old hardcoded constants, so a channel
    # saved before these settings existed renders exactly as it did.
    title_size = int(getattr(style, "outro_font_size", OUTRO_TITLE_SIZE))
    subtext_size = max(10, round(title_size * OUTRO_SUBTEXT_SIZE / OUTRO_TITLE_SIZE))
    # Previously hardcoded to 2 for the title and 0 (no outline at all)
    # for the subtext — which is exactly why subtext went unreadable over
    # a busy background. Both now come from one setting.
    stroke = int(getattr(style, "outro_stroke_width", 2))

    font_title = load_font(title_size, style.font_face)
    font_subtext = load_font(subtext_size, style.font_face)
    max_width = int(W * 0.85)

    image = card_background(channel_key, style.outro_bg_color, style,
                            background_blur, background_dim)
    draw = ImageDraw.Draw(image)

    title_lines = wrap_words(channel_display_name.split(), font_title, max_width)
    subtext_lines = wrap_words(subtext.split(), font_subtext, max_width)
    title_height = int(title_size * 1.3)
    subtext_height = int(subtext_size * 1.3)
    gap = 40

    total = title_height * len(title_lines) + gap + subtext_height * len(subtext_lines)
    y = (H - total) / 2
    y = _draw_centered_lines(draw, title_lines, font_title, y, title_height, W,
                             style.outro_title_color, stroke, "black")
    _draw_centered_lines(draw, subtext_lines, font_subtext, y + gap, subtext_height, W,
                         style.outro_subtext_color, stroke, "black")
    return np.array(image)


def render_end_screen(cta: dict, style, channel_key: str) -> np.ndarray:
    """The optional second card, for ONE randomly chosen active CTA.

    One per video, not every active one stacked together — the generated
    description still lists all of them, only the on-screen card is
    picked. A merch CTA also shows a random uploaded product photo when
    the channel has any.
    """
    from core.assets import list_merch_photos

    font = load_font(END_SCREEN_TEXT_SIZE, style.font_face)
    max_width = int(W * 0.85)
    image = Image.new("RGBA", (W, H), tuple(style.outro_bg_color))
    draw = ImageDraw.Draw(image)

    photo = None
    if cta["type"] == "merch":
        photos = list_merch_photos(channel_key)
        if photos:
            photo = Image.open(random.choice(photos)).convert("RGBA")

    lines = wrap_words(cta["text"].split(), font, max_width)
    line_height = int(END_SCREEN_TEXT_SIZE * 1.4)
    text_height = line_height * len(lines)

    if photo is not None:
        # Photo fills the upper portion, capped so it never crowds the
        # text; the text centres in what's left.
        scale = min(int(W * 0.8) / photo.width, int(H * 0.55) / photo.height)
        photo = photo.resize((max(1, int(photo.width * scale)), max(1, int(photo.height * scale))))
        gap = 48
        y = (H - (photo.height + gap + text_height)) / 2
        image.paste(photo, (int((W - photo.width) / 2), int(y)), photo)
        y += photo.height + gap
    else:
        y = (H - text_height) / 2

    _draw_centered_lines(draw, lines, font, y, line_height, W,
                         style.outro_subtext_color, 2, "black")
    return np.array(image)


# --- shots ------------------------------------------------------------

def split_into_shots(segments: list, max_seconds: float) -> list:
    """Split each segment's span into equal shots no longer than
    max_seconds.

    Equal rather than max-length-plus-remainder, so a segment never ends
    on a short leftover fragment. A segment shown as one continuous take
    reads as static once it runs more than a few seconds.
    """
    shots = []
    for index, segment in enumerate(segments):
        duration = segment.duration
        count = max(1, math.ceil(duration / max_seconds)) if duration > 0 else 1
        step = duration / count if count else duration
        for i in range(count):
            shots.append(Shot(
                start=segment.start + i * step,
                end=segment.start + (i + 1) * step,
                segment_index=index,
            ))
    return shots


def _background_layer(clip_path, target_duration: float, start_time: float,
                      is_first: bool, crossfade: float):
    """Prepare one shot's footage: fill the frame, take a random window,
    position at its exact real timestamp."""
    from moviepy.editor import VideoFileClip
    from moviepy.video.fx.loop import loop as loop_fx

    raw = VideoFileClip(str(clip_path))
    background = raw.resize(height=H)
    if background.w < W:
        background = background.resize(width=W)
    background = background.crop(x_center=background.w / 2, y_center=background.h / 2,
                                 width=W, height=H)

    if background.duration < target_duration:
        background = loop_fx(background, duration=target_duration)
    else:
        latest_start = background.duration - target_duration
        start = random.uniform(0, latest_start) if latest_start > 0 else 0.0
        background = background.subclip(start, start + target_duration)

    background = background.without_audio().set_start(start_time)
    if not is_first:
        background = background.crossfadein(crossfade)
    return background


# --- the stage --------------------------------------------------------

def _replace_missing_clips(plan) -> None:
    """Swap out any shot whose clip file is gone.

    The library database and the library directory can disagree - a file
    deleted by hand, a failed download that still recorded a row, a
    partially restored backup. Substitutes the least-recently-used clip
    that does exist, and flags the video as degraded because the
    replacement was never scored against the segment.
    """
    from pipeline.footage import store

    missing = [shot for shot in plan.shots
               if not shot.clip_path or not shot.clip_path.exists()]
    if not missing:
        return

    log.warning(f"  [video] {len(missing)} matched clip(s) are missing from disk; "
                f"substituting so the render can finish.")
    plan.footage_degraded = True

    present = {shot.clip_path.name for shot in plan.shots
               if shot.clip_path and shot.clip_path.exists()}
    for shot in missing:
        replacements = [c for c in store.least_recently_used(len(present) + 10,
                                                             exclude=present)
                        if c.path.exists()]
        if not replacements:
            raise FootageLibraryError(
                "no clip files present on disk",
                user_message=("The footage library's files are missing. Check "
                              "footage/library/, or re-add clips."),
            )
        shot.clip_path = replacements[0].path
        present.add(shot.clip_path.name)


def run(plan):
    """Pipeline stage: match footage, then render the video."""
    from moviepy.editor import CompositeVideoClip, ImageClip, concatenate_videoclips
    from moviepy.audio.AudioClip import AudioArrayClip
    from moviepy.video.io.ffmpeg_tools import ffmpeg_merge_video_audio
    from pipeline.footage import library

    channel = plan.channel
    pacing, style = channel.pacing, channel.style
    segments = plan.script.segments

    # --- footage
    job_context.report_stage(3)
    plan.shots = split_into_shots(segments, pacing.max_shot_seconds)
    shot_counts = [len(plan.shots_for_segment(i)) for i in range(len(segments))]
    log.info(f"[3/5] Matching footage for {len(plan.shots)} shot(s) "
             f"across {len(segments)} segment(s)...")

    outcome = library.assign_clips(segments, shot_counts, channel.avoid_imagery)
    plan.footage_repeated = outcome.repeated
    plan.footage_degraded = outcome.degraded

    from core.paths import LIBRARY_DIR
    per_segment = {i: list(names) for i, names in enumerate(outcome.picks)}
    for shot in plan.shots:
        shot.clip_path = LIBRARY_DIR / per_segment[shot.segment_index].pop(0)

    # A database row whose file has gone is invisible until moviepy tries
    # to open it, roughly a minute into the render. Substituting here
    # costs one stat() per shot and turns a hard failure into a
    # noticeably-worse video that still finishes.
    _replace_missing_clips(plan)

    # --- render
    job_context.report_stage(4)
    log.info(f"[4/5] Preparing {len(plan.shots)} background clip(s)...")

    narration = plan.voiceover.samples
    if narration.ndim == 1:
        narration = narration.reshape(-1, 1)
    fps = plan.voiceover.fps
    narration_duration = len(narration) / fps
    crossfade = pacing.crossfade

    backgrounds = []
    for i, shot in enumerate(plan.shots):
        is_last = i == len(plan.shots) - 1
        target = shot.duration if is_last else shot.duration + crossfade
        backgrounds.append(_background_layer(shot.clip_path, target, shot.start,
                                             i == 0, crossfade))

    log.info("  [video] rendering captions...")
    captions = build_caption_clips(plan.voiceover.word_timings, style, pacing)

    narration_video = CompositeVideoClip([*backgrounds, *captions], size=(W, H))
    narration_video = narration_video.set_duration(narration_duration)

    # The seed's own title rather than the generated one: it is what the
    # video is about, it is stable, and it is what the plan calls this
    # video. `split_at` is where the card lands inside the narration
    # rather than in front of all of it — 0 means "in front," same as
    # this always worked before placement was a choice.
    lead_seconds = 0.0
    split_at = 0.0
    if style.title_card_enabled:
        lead_seconds = max(0.0, float(style.title_card_seconds))
        topic_title = (_topic_title_for_card(channel, plan.seed)
                      if style.title_card_show_topic else "")
        title_card_clip = ImageClip(render_title_card(
            channel.channel_display_name,
            plan.seed.title or (plan.script.title if plan.script else ""),
            style, channel.key, topic_title)).set_duration(lead_seconds)

        if (style.title_card_placement == "after_intro"
                and plan.script and plan.script.segments):
            split_at = min(plan.script.segments[0].end, narration_duration)

        if split_at > 0:
            parts = [narration_video.subclip(0, split_at), title_card_clip,
                     narration_video.subclip(split_at, narration_duration)]
        else:
            split_at = 0.0  # guard: no real segment timing, fall back to "start"
            parts = [title_card_clip, narration_video]
    else:
        parts = [narration_video]

    tail_seconds = 0.0
    if getattr(style, "outro_enabled", True):
        tail_seconds = pacing.outro_seconds
        parts.append(ImageClip(render_outro(channel.channel_display_name,
                                            channel.outro_subtext, style, channel.key))
                    .set_duration(pacing.outro_seconds))

    active_ctas = resolve_active_ctas(channel.monetization, channel.end_screen)
    if channel.end_screen.enabled and active_ctas:
        chosen = random.choice(active_ctas)
        parts.append(ImageClip(render_end_screen(chosen, style, channel.key))
                     .set_duration(channel.end_screen.duration_seconds))
        tail_seconds += channel.end_screen.duration_seconds

    final = concatenate_videoclips(parts, method="compose")
    final = final.set_duration(lead_seconds + narration_duration + tail_seconds)

    narration = apply_fade(narration, fps, fade_out=0.05)
    # Silence for the card goes wherever the card itself landed — in
    # front of everything (split_at == 0, the original behaviour) or
    # spliced into the narration at the same point the video was split.
    lead_silence = silence_array(lead_seconds, fps, narration.shape[1])
    silence = silence_array(tail_seconds, fps, narration.shape[1])
    if split_at > 0:
        split_sample = int(split_at * fps)
        audio = AudioArrayClip(
            np.concatenate([narration[:split_sample], lead_silence,
                           narration[split_sample:], silence], axis=0), fps=fps)
    else:
        audio = AudioArrayClip(
            np.concatenate([lead_silence, narration, silence], axis=0), fps=fps)

    # Video and audio are written separately then muxed with a stream
    # copy. write_videofile's combined path was corrupting roughly the
    # last second of audio — verified by comparing against a standalone
    # render of the same samples, which matched everywhere except that
    # final stretch, where it was different non-silent content rather
    # than a decode artifact.
    out = Path(plan.video_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    temp_video = out.with_name(f"{out.stem}_TEMP_video.mp4")
    temp_audio = out.with_name(f"{out.stem}_TEMP_audio.m4a")

    log.info(f"  [video] rendering {len(plan.shots)} shot(s) — the slowest step...")
    try:
        final.write_videofile(str(temp_video), fps=30, codec="libx264", audio=False,
                              threads=4, preset="medium", logger=encode_logger())
        log.info("  [video] encoding the audio track...")
        audio.write_audiofile(str(temp_audio), codec="aac", fps=fps, logger=None)
        log.info("  [video] muxing...")
        ffmpeg_merge_video_audio(str(temp_video), str(temp_audio), str(out),
                                 vcodec="copy", acodec="copy", logger=None)
    finally:
        temp_video.unlink(missing_ok=True)
        temp_audio.unlink(missing_ok=True)
        audio.close()
        for background in backgrounds:
            background.close()
        final.close()

    library.mark_used([shot.clip_path for shot in plan.shots if shot.clip_path])
    job_context.report_progress(None)
    return plan
