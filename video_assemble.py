"""
Combines keyword-matched background clips, the voiceover audio, and
word-level timings into a finished 1080x1920 vertical video with
karaoke-style burned-in captions (the word currently being spoken is
highlighted in a different color) and a channel-branded outro card.

Each segment's real spoken duration is split into several shots (capped
at pacing["max_shot_seconds"]) so no single piece of footage runs too
long, and every shot in the video gets its own distinct clip from the
shared library (footage_library.pick_clips_for_shots — a clip is never
reused within one video). Shots are crossfaded into each other at their
exact real timestamps — not shortened/padded concatenation, which would
drift captions out of sync with the audio as shots accumulate (see
build_video).

Pacing (pause/shot/crossfade/caption timing) and style (caption/outro
visuals) are per-channel config (config/channels.py), not hardcoded —
a reflective-quote channel and a jokes channel can look and feel
completely different without any code change.

Captions and the outro card are rendered with Pillow directly (not
moviepy's ImageMagick-backed TextClip) so there's no external ImageMagick
install/PATH setup needed.
"""

import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    VideoFileClip, CompositeVideoClip, ImageClip,
    concatenate_videoclips,
)
from moviepy.audio.AudioClip import AudioArrayClip
from moviepy.video.fx.loop import loop as loop_fx
from moviepy.video.io.ffmpeg_tools import ffmpeg_merge_video_audio

import footage_library
from audio_utils import silence_array, apply_fade

W, H = 1080, 1920
CAPTION_Y = int(H * 0.72)          # lower-third placement
CAPTION_MAX_WIDTH = int(W * 0.9)

# Tried in order; first one found on disk wins. Falls back to Pillow's
# built-in bitmap font (works everywhere, looks plainer) if none exist.
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _group_words(word_timings, pacing):
    """Chunk words into caption groups that break at sentence ends and at
    real pauses (silence between segments, or between sentences within
    one segment) rather than a fixed word count — otherwise a caption can
    straddle a pause, vanishing and reappearing mid-group, or run a
    sentence's end into the next sentence's start."""
    max_group_size = pacing["caption_max_group_size"]
    pause_gap_threshold = pacing["caption_pause_gap_threshold"]
    groups = []
    current = []
    for w in word_timings:
        if current:
            gap = w["start"] - current[-1]["end"]
            prev_ends_sentence = current[-1]["word"].rstrip().endswith((".", "!", "?"))
            if gap > pause_gap_threshold or prev_ends_sentence or len(current) >= max_group_size:
                groups.append(current)
                current = []
        current.append(w)
    if current:
        groups.append(current)
    return groups


def _load_font(fontsize):
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, fontsize)
    return ImageFont.load_default()


def _wrap_words(words, font, max_width, draw):
    """Word-wrap into lines, keeping each line as a list of words (rather
    than a joined string) so each word can still be colored individually."""
    lines = []
    current = []
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


def _render_caption_image(words, style, highlight_index=None,
                           max_width=CAPTION_MAX_WIDTH):
    """Renders one caption group to an RGBA numpy array, with the word at
    `highlight_index` (if any) drawn in the style's highlight color — a
    karaoke-style active-word highlight — for use as a moviepy ImageClip."""
    fontsize = style["font_size"]
    font = _load_font(fontsize)
    measurer = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines = _wrap_words(words, font, max_width, measurer)

    space_width = measurer.textlength(" ", font=font)
    line_height = int(fontsize * 1.3)
    stroke_width = style["stroke_width"]
    img_height = line_height * len(lines) + stroke_width * 2
    img = Image.new("RGBA", (max_width, img_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    word_index = 0
    for line_i, line_words in enumerate(lines):
        word_widths = [draw.textlength(w, font=font) for w in line_words]
        line_width = sum(word_widths) + space_width * (len(line_words) - 1)
        x = (max_width - line_width) / 2
        y = line_i * line_height
        for word, word_width in zip(line_words, word_widths):
            fill = style["highlight_color"] if word_index == highlight_index else style["base_color"]
            draw.text((x, y), word, font=font, fill=fill,
                       stroke_width=stroke_width, stroke_fill=style["stroke_color"])
            x += word_width + space_width
            word_index += 1

    return np.array(img)


def _render_outro_image(channel_name, subtext, style, width=W, height=H):
    """Channel-branded end card: display name + a subscribe line. No title
    card elsewhere in the video — this is the only branding overlay."""
    font_title = _load_font(84)
    font_subtext = _load_font(48)
    max_width = int(width * 0.85)

    img = Image.new("RGBA", (width, height), style["outro_bg_color"])
    draw = ImageDraw.Draw(img)

    title_lines = _wrap_words(channel_name.split(), font_title, max_width, draw)
    subtext_lines = _wrap_words(subtext.split(), font_subtext, max_width, draw)

    title_line_height = int(84 * 1.3)
    subtext_line_height = int(48 * 1.3)
    gap = 40
    total_height = (
        title_line_height * len(title_lines) + gap + subtext_line_height * len(subtext_lines)
    )
    y = (height - total_height) / 2

    for line in title_lines:
        text = " ".join(line)
        line_width = draw.textlength(text, font=font_title)
        x = (width - line_width) / 2
        draw.text((x, y), text, font=font_title, fill=style["outro_title_color"],
                   stroke_width=2, stroke_fill="black")
        y += title_line_height

    y += gap

    for line in subtext_lines:
        text = " ".join(line)
        line_width = draw.textlength(text, font=font_subtext)
        x = (width - line_width) / 2
        draw.text((x, y), text, font=font_subtext, fill=style["outro_subtext_color"])
        y += subtext_line_height

    return np.array(img)


def _prepare_bg_clip(clip):
    """Crop/resize a raw footage clip to fill the 1080x1920 frame."""
    bg = clip.resize(height=H)
    if bg.w < W:
        bg = bg.resize(width=W)
    return bg.crop(x_center=bg.w / 2, y_center=bg.h / 2, width=W, height=H)


def _split_segment_into_shots(segment, max_seconds):
    """Splits one segment's [start, end) span into consecutive shots no
    longer than max_seconds each (even-sized, not a short leftover
    fragment) — a segment's footage otherwise gets shown as one long
    continuous take, which reads as static/undynamic once segments run
    more than a few seconds."""
    start, end = segment["start"], segment["end"]
    duration = end - start
    count = max(1, math.ceil(duration / max_seconds))
    step = duration / count
    return [{"start": start + i * step, "end": start + (i + 1) * step} for i in range(count)]


def _shot_bg_layer(clip_path, target_duration, start_time, is_first, crossfade):
    """Prepares and trims/loops footage for one shot, picking a fresh
    random window into clip_path each call, positioned at its exact real
    timestamp."""
    raw = VideoFileClip(str(clip_path))
    bg = _prepare_bg_clip(raw)

    if bg.duration < target_duration:
        bg = loop_fx(bg, duration=target_duration)
    else:
        max_start = bg.duration - target_duration
        start = random.uniform(0, max_start) if max_start > 0 else 0.0
        bg = bg.subclip(start, start + target_duration)

    bg = bg.without_audio().set_start(start_time)
    if not is_first:
        bg = bg.crossfadein(crossfade)

    return bg


def build_video(narration_array: np.ndarray, fps: int, word_timings: list, segment_timings: list,
                 out_path: str, channel_display_name: str, outro_subtext: str,
                 pacing: dict, style: dict, avoid_imagery: list = None, interactive: bool = True):
    if narration_array.ndim == 1:
        narration_array = narration_array.reshape(-1, 1)
    narration_duration = len(narration_array) / fps

    crossfade = pacing["crossfade"]
    outro_seconds = pacing["outro_seconds"]

    segment_shot_spans = [_split_segment_into_shots(seg, pacing["max_shot_seconds"]) for seg in segment_timings]
    shot_counts = [len(spans) for spans in segment_shot_spans]
    print(f"  [video] matching footage for {sum(shot_counts)} shot(s) across {len(segment_timings)} segment(s)...")
    picked_per_segment = footage_library.pick_clips_for_shots(
        segment_timings, shot_counts, avoid_imagery, interactive=interactive
    )

    shots = []
    for spans, clip_paths in zip(segment_shot_spans, picked_per_segment):
        for span, clip_path in zip(spans, clip_paths):
            shots.append({**span, "clip_path": clip_path})

    print(f"  [video] preparing {len(shots)} background clip(s)...")
    bg_layers = []
    for i, shot in enumerate(shots):
        is_last = i == len(shots) - 1
        span = shot["end"] - shot["start"]
        target_duration = span if is_last else span + crossfade

        bg_layers.append(_shot_bg_layer(shot["clip_path"], target_duration, shot["start"], i == 0, crossfade))

    print("  [video] rendering captions...")
    caption_clips = []
    for group in _group_words(word_timings, pacing):
        words = [w["word"] for w in group]
        for i, w in enumerate(group):
            # Hold each word's highlight until the NEXT word actually starts
            # (not just until this word's own "end") — the natural gap
            # between spoken words otherwise leaves no caption clip active
            # at all for that gap, which reads as the caption flashing off
            # and back on with every word. The last word in a group still
            # ends at its own "end", since the gap after it is the real
            # pause that splits captions into groups in the first place.
            is_last_word = i == len(group) - 1
            end = w["end"] if is_last_word else group[i + 1]["start"]
            img_array = _render_caption_image(words, style, highlight_index=i)
            clip = (
                ImageClip(img_array)
                .set_start(w["start"])
                .set_end(end)
                .set_position(("center", CAPTION_Y))
            )
            caption_clips.append(clip)

    narration_video = CompositeVideoClip([*bg_layers, *caption_clips], size=(W, H))
    narration_video = narration_video.set_duration(narration_duration)

    outro_img = _render_outro_image(channel_display_name, outro_subtext, style)
    outro_clip = ImageClip(outro_img).set_duration(outro_seconds)

    final_video = concatenate_videoclips([narration_video, outro_clip], method="compose")
    final_video = final_video.set_duration(narration_duration + outro_seconds)

    narration_array = apply_fade(narration_array, fps, fade_out=0.05)
    silence = silence_array(outro_seconds, fps, narration_array.shape[1])
    full_audio = AudioArrayClip(np.concatenate([narration_array, silence], axis=0), fps=fps)

    # Video and audio are rendered and written completely separately, then
    # muxed with a plain stream copy — write_videofile's own combined
    # audio+video path was corrupting roughly the last second of audio
    # (verified: a fresh render's audio matched a standalone render of the
    # same samples sample-for-sample except in that final stretch, where it
    # was actual different, non-silent, uncorrelated content — not a decode
    # artifact). Writing audio and video independently and muxing avoids
    # whatever internal chunking that combined path does near the end.
    out = Path(out_path)
    temp_video_path = out.with_name(f"{out.stem}_TEMP_video.mp4")
    temp_audio_path = out.with_name(f"{out.stem}_TEMP_audio.m4a")

    print(f"  [video] rendering video ({len(shots)} shot(s), this is usually the slowest step)...")
    final_video.write_videofile(
        str(temp_video_path), fps=30, codec="libx264", audio=False,
        threads=4, preset="medium", logger="bar",
    )
    print("  [video] encoding audio track...")
    full_audio.write_audiofile(str(temp_audio_path), codec="aac", fps=fps, logger=None)

    print("  [video] muxing audio and video...")
    ffmpeg_merge_video_audio(str(temp_video_path), str(temp_audio_path), out_path,
                              vcodec="copy", acodec="copy", logger=None)

    temp_video_path.unlink(missing_ok=True)
    temp_audio_path.unlink(missing_ok=True)

    full_audio.close()
    for bg in bg_layers:
        bg.close()
    final_video.close()

    for clip_paths in picked_per_segment:
        for clip_path in clip_paths:
            footage_library.mark_used(clip_path)

    return out_path
