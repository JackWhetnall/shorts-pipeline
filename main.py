"""
End-to-end: pick a channel -> get a seed (quote or topic) -> write a
script -> generate voiceover+timings -> assemble captioned video.

Usage:
    python main.py bible_daily            # make 1 video
    python main.py bible_daily --count 5  # make 5 videos
"""

import argparse
import random
import re
from datetime import date
from pathlib import Path

from config.channels import CHANNELS
from quote_source import get_quote
from script_gen import generate_script
from tts_captions import generate_voiceover
from video_assemble import build_video


def fetch_candidate_seed(cfg: dict) -> dict:
    """One non-interactive fetch of a quote/topic — no input(). Returns
    the seed dict script_gen.generate_script expects. Used directly by
    the web app (which drives accept/reroll via UI buttons instead of
    stdin); pick_seed below is the CLI's interactive wrapper around it."""
    if cfg["content_mode"] == "static_corpus":
        quote = get_quote(cfg["source"])
        return {"type": "quote", "text": quote["text"], "reference": quote["reference"]}
    elif cfg["content_mode"] == "topic":
        topic = random.choice(cfg["topics"])
        return {"type": "topic", "topic": topic}
    else:
        raise ValueError(f"Unknown content_mode: {cfg['content_mode']!r}")


def pick_seed(cfg: dict) -> dict:
    """Keep rerolling until the user approves a quote/topic."""
    while True:
        seed = fetch_candidate_seed(cfg)
        if seed["type"] == "quote":
            print(f"\nQuote: {seed['text']}\nReference: {seed['reference']}\n")
            prompt = "Use this quote? [Y/n] "
        else:
            print(f"\nTopic: {seed['topic']}\n")
            prompt = "Use this topic? [Y/n] "

        if input(prompt).strip().lower() in ("", "y", "yes"):
            return seed
        print("Rerolling...")


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "video"


def _title_for_seed(seed: dict) -> str:
    """A human-readable slug (book/chapter/verse for a quote, the topic
    for topic-driven content) instead of a random hash — so filenames
    alone tell you what's in each video and let you spot repeats at a
    glance."""
    if seed["type"] == "quote":
        return _slugify(seed["reference"])
    return _slugify(seed["topic"])


def _unique_stem(out_dir: Path, base: str) -> str:
    """Appends _2, _3, ... if base is already taken in out_dir (e.g. the
    same topic getting picked again, or — rarely — the same verse)."""
    if not any(out_dir.glob(f"{base}.*")):
        return base
    i = 2
    while any(out_dir.glob(f"{base}_{i}.*")):
        i += 1
    return f"{base}_{i}"


def make_one_video(channel_key: str):
    cfg = CHANNELS[channel_key]
    seed = pick_seed(cfg)
    return generate_video_from_seed(channel_key, seed, cfg)


def generate_video_from_seed(channel_key: str, seed: dict, cfg: dict = None,
                              interactive: bool = True):
    """Everything after seed selection: script -> voiceover -> footage/video
    -> metadata. Shared verbatim between the CLI (make_one_video, after its
    interactive pick_seed) and the web app (after its own accept/reroll UI
    step) — this is the one place that logic lives.

    interactive=False skips the footage-matching fallback's "pause here to
    add footage" stdin prompt (see footage_library.pick_clips_for_shots) —
    needed when this runs on a background thread with no TTY to read from,
    which would otherwise hang forever. The CLI never passes False."""
    cfg = cfg or CHANNELS[channel_key]

    print("[1/4] Generating script...")
    script = generate_script(seed, cfg["style_prompt"], cfg["pacing"])
    print(f"      {len(script['segments'])} segment(s) generated.")

    out_dir = Path(cfg["output_dir"]) / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _unique_stem(out_dir, _title_for_seed(seed))

    audio_path = out_dir / f"{stem}_audio.mp3"
    video_path = out_dir / f"{stem}.mp4"

    print("[2/4] Generating voiceover...")
    _, word_timings, segment_timings, narration_array, fps = generate_voiceover(
        script["segments"], script["citation"], cfg["voice"], str(audio_path), cfg["pacing"],
        speed=cfg["speed"],
    )

    print("[3/4] Matching footage and assembling video...")
    build_video(
        narration_array=narration_array,
        fps=fps,
        word_timings=word_timings,
        segment_timings=segment_timings,
        out_path=str(video_path),
        channel_display_name=cfg["channel_display_name"],
        outro_subtext=cfg["outro_subtext"],
        pacing=cfg["pacing"],
        style=cfg["style"],
        avoid_imagery=cfg["avoid_imagery"],
        interactive=interactive,
    )

    print("[4/4] Saving metadata...")
    # save the script alongside the video for your records / for writing
    # the YouTube description & title
    with open(out_dir / f"{stem}_meta.txt", "w", encoding="utf-8") as f:
        if script["citation"]:
            f.write(f"Reference: {script['citation']}\n\n")
        for i, seg in enumerate(script["segments"]):
            f.write(f"[segment {i}] (keywords: {', '.join(seg['keywords'])})\n")
            f.write(f"{seg['text']}\n\n")

    print(f"Done: {video_path}")
    return video_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("channel", choices=CHANNELS.keys())
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()

    for _ in range(args.count):
        make_one_video(args.channel)
