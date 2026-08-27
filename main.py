"""
End-to-end: pick a channel -> get a quote -> write a script -> generate
voiceover+timings -> assemble captioned video.

Usage:
    python main.py bible_daily            # make 1 video
    python main.py bible_daily --count 5  # make 5 videos
"""

import argparse
import uuid
from pathlib import Path

from config.channels import CHANNELS
from quote_source import get_quote
from script_gen import generate_script
from tts_captions import generate_voiceover
from video_assemble import build_video


def pick_quote(source: str) -> dict:
    """Keep rerolling until the user approves a quote."""
    while True:
        quote = get_quote(source)
        print(f"\nQuote: {quote['text']}\nReference: {quote['reference']}\n")
        answer = input("Use this quote? [Y/n] ").strip().lower()
        if answer in ("", "y", "yes"):
            return quote
        print("Rerolling...")


def make_one_video(channel_key: str):
    cfg = CHANNELS[channel_key]

    quote = pick_quote(cfg["source"])
    parts = generate_script(quote, cfg["style_prompt"])

    out_dir = Path(cfg["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    video_id = uuid.uuid4().hex[:8]

    audio_path = out_dir / f"{video_id}_audio.mp3"
    video_path = out_dir / f"{video_id}.mp4"

    _, word_timings = generate_voiceover(parts, cfg["voice"], str(audio_path))

    build_video(
        audio_path=str(audio_path),
        word_timings=word_timings,
        backgrounds_dir=cfg["backgrounds_dir"],
        out_path=str(video_path),
    )

    # save the script + reference alongside the video for your records /
    # for writing the YouTube description & title
    with open(out_dir / f"{video_id}_meta.txt", "w") as f:
        f.write(
            f"Reference: {quote['reference']}\n\n"
            f"Quote:\n{parts['quote']}\n\n"
            f"Reflection:\n{parts['reflection']}\n"
        )

    print(f"Done: {video_path}")
    return video_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("channel", choices=CHANNELS.keys())
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()

    for _ in range(args.count):
        make_one_video(args.channel)
