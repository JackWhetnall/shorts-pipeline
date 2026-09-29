"""
Generated animation from the command line (pipeline.animation).

    python tools/animate.py looks                               # the presets
    python tools/animate.py samples                             # draw missing look examples
    python tools/animate.py samples --look risograph --force    # draw one look's again
    python tools/animate.py frames curiosity_leak                # draw its style frames again
    python tools/animate.py cast curiosity_leak                  # draw its cast's model sheets
    python tools/animate.py estimate curiosity_leak --seconds 50 # what a video would cost
    python tools/animate.py animatic curiosity_leak output/curiosity_leak/.../video.mp4
    python tools/animate.py film curiosity_leak output/curiosity_leak/.../video.mp4

`animatic` storyboards an existing video and draws its checked keyframes,
held and cut to its narration: about $0.60 for a 50-second video and no
video model, the way to judge a look. `film` animates every shot too
(needs FAL_KEY), within the channel's budget. The look options
(`--look`, `--notes`, ...) try a setting without saving it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.channels import load_channels                           # noqa: E402
from core.logging_setup import configure                          # noqa: E402
from pipeline.animation import bible, look as looks, models, preview  # noqa: E402


def _channel(key: str, args):
    channels = load_channels()
    if key not in channels:
        raise SystemExit(f"No channel {key!r}. Channels: {', '.join(channels)}")
    channel = channels[key]
    a = channel.animation
    for name in ("look", "quality", "video_model", "image_model", "cadence"):
        if getattr(args, name, None):
            setattr(a, name, getattr(args, name))
    if getattr(args, "notes", None) is not None:
        a.style_notes = args.notes
    for name in ("energy", "pace", "finish"):
        if getattr(args, name, None) is not None:
            setattr(a, name, getattr(args, name))
    if getattr(args, "budget", None) is not None:
        a.budget = args.budget
    return channel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("looks")
    samples_cmd = sub.add_parser("samples")
    samples_cmd.add_argument("--look", action="append", choices=list(looks.presets()))
    samples_cmd.add_argument("--force", action="store_true")
    for name in ("frames", "cast", "estimate", "animatic", "film"):
        p = sub.add_parser(name)
        p.add_argument("channel")
        if name in ("animatic", "film"):
            p.add_argument("video")
        if name == "estimate":
            p.add_argument("--seconds", type=float, default=50.0)
        p.add_argument("--look", choices=list(looks.presets()))
        p.add_argument("--notes")
        p.add_argument("--quality", choices=["draft", "standard", "high"])
        p.add_argument("--video-model", dest="video_model", choices=list(models.VIDEO_MODELS))
        p.add_argument("--image-model", dest="image_model", choices=list(models.IMAGE_MODELS))
        p.add_argument("--cadence", choices=["ones", "twos", "threes"])
        p.add_argument("--energy", type=int)
        p.add_argument("--pace", type=int)
        p.add_argument("--finish", type=int)
        p.add_argument("--budget", type=float)
    args = parser.parse_args()
    configure()

    if args.command == "looks":
        for key, p in looks.presets().items():
            print(f"{key:20} {p['label']}: {p['description']}")
        return 0
    if args.command == "samples":
        from pipeline.animation import samples
        for path in samples.draw(args.look, force=args.force):
            print(path)
        return 0
    channel = _channel(args.channel, args)
    look = looks.resolve(channel.animation)
    if args.command == "frames":
        for path in bible.draw_style_frames(channel, look):
            print(path)
    elif args.command == "cast":
        for member in bible.cast_members(channel):
            print(bible.cast_sheet(channel, look, member))
    elif args.command == "estimate":
        a = channel.animation
        est = models.estimate(args.seconds, models.mean_shot_seconds(a.pace),
                              models.video_model(a.video_model),
                              models.image_model(a.image_model), a.quality)
        print(f"{est.shots} shots, {est.generated:.0f}s generated: video ${est.video_usd:.2f}, "
              f"pictures ${est.image_usd:.2f}, checks ${est.other_usd:.2f}; "
              f"about ${est.total:.2f} (budget ${a.budget:.2f})")
    else:
        print(preview.run(channel, Path(args.video), animate=args.command == "film"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
