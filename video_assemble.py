"""
Combines a looping background clip, the voiceover audio, and word-level
timings into a finished 1080x1920 vertical video with karaoke-style
burned-in captions (current word highlighted).

Captions are rendered with Pillow directly (not moviepy's ImageMagick-backed
TextClip) so there's no external ImageMagick install/PATH setup needed.
"""

import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    VideoFileClip, AudioFileClip, CompositeVideoClip, ImageClip,
    concatenate_videoclips,
)

W, H = 1080, 1920
FONTSIZE = 70
CAPTION_Y = int(H * 0.72)          # lower-third placement
CAPTION_MAX_WIDTH = int(W * 0.9)
GROUP_SIZE = 3                     # words shown together per caption chunk

# Tried in order; first one found on disk wins. Falls back to Pillow's
# built-in bitmap font (works everywhere, looks plainer) if none exist.
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def pick_background(backgrounds_dir: str) -> str:
    files = list(Path(backgrounds_dir).glob("*.mp4"))
    if not files:
        raise FileNotFoundError(f"No .mp4 backgrounds found in {backgrounds_dir}")
    return str(random.choice(files))


def _group_words(word_timings, group_size=GROUP_SIZE):
    """Chunk words into small caption groups so text isn't one-word-flashy."""
    groups = []
    for i in range(0, len(word_timings), group_size):
        chunk = word_timings[i:i + group_size]
        groups.append({
            "text": " ".join(w["word"] for w in chunk),
            "start": chunk[0]["start"],
            "end": chunk[-1]["end"],
        })
    return groups


def _load_font(fontsize):
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, fontsize)
    return ImageFont.load_default()


def _wrap_text(text, font, max_width, draw):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _render_caption_image(text, fontsize=FONTSIZE, max_width=CAPTION_MAX_WIDTH,
                           color="white", stroke_color="black", stroke_width=3):
    """Renders one caption group to an RGBA numpy array, sized to fit its
    (possibly wrapped) text, for use as a moviepy ImageClip."""
    font = _load_font(fontsize)
    measurer = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines = _wrap_text(text, font, max_width, measurer)

    line_height = int(fontsize * 1.3)
    img_height = line_height * len(lines) + stroke_width * 2
    img = Image.new("RGBA", (max_width, img_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for i, line in enumerate(lines):
        line_width = draw.textlength(line, font=font)
        x = (max_width - line_width) / 2
        y = i * line_height
        draw.text((x, y), line, font=font, fill=color,
                   stroke_width=stroke_width, stroke_fill=stroke_color)

    return np.array(img)


def build_video(audio_path: str, word_timings: list, backgrounds_dir: str,
                 out_path: str):
    audio = AudioFileClip(audio_path)
    duration = audio.duration

    bg_path = pick_background(backgrounds_dir)
    bg = VideoFileClip(bg_path)

    # loop/trim background to match voiceover length, crop/resize to 9:16
    bg = bg.resize(height=H)
    if bg.w < W:
        bg = bg.resize(width=W)
    bg = bg.crop(x_center=bg.w / 2, y_center=bg.h / 2, width=W, height=H)

    if bg.duration < duration:
        loops_needed = int(duration // bg.duration) + 1
        bg = concatenate_videoclips([bg] * loops_needed)
    bg = bg.subclip(0, duration).without_audio()

    caption_groups = _group_words(word_timings)
    caption_clips = []
    for group in caption_groups:
        img_array = _render_caption_image(group["text"])
        txt_clip = (
            ImageClip(img_array)
            .set_start(group["start"])
            .set_end(group["end"])
            .set_position(("center", CAPTION_Y))
        )
        caption_clips.append(txt_clip)

    final = CompositeVideoClip([bg, *caption_clips], size=(W, H))
    final = final.set_audio(audio)
    final = final.set_duration(duration)

    final.write_videofile(
        out_path, fps=30, codec="libx264", audio_codec="aac",
        threads=4, preset="medium",
    )

    audio.close()
    bg.close()
    final.close()

    return out_path
