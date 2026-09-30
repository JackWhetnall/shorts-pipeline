"""
Animation from the command line (pipeline.animation).

    python tools/animate.py styles                              # the starting points
    python tools/animate.py questions                           # the style questions and options
    python tools/animate.py materials                           # draw missing material examples
    python tools/animate.py gallery                             # draw missing starting-point examples
    python tools/animate.py gallery --id meeple_logic --force   # draw one again
    python tools/animate.py preview curiosity_leak --start felt_science
    python tools/animate.py preview curiosity_leak --set stage=game_board --set material=wood
    python tools/animate.py preview curiosity_leak --start quant_minimal --wide
    python tools/animate.py frames curiosity_leak               # draw its style frames again
    python tools/animate.py cast curiosity_leak                 # draw its cast's model sheets
    python tools/animate.py animatic curiosity_leak output/curiosity_leak/.../video.mp4
    python tools/animate.py film curiosity_leak output/curiosity_leak/.../video.mp4

A channel's saved style is used unless `--start` (a starting point) or
`--set question=option` (one answer; repeatable) say otherwise, without
saving. `preview` makes one frame of the style on the channel's subject
(`--wide` for a widescreen frame, `--moving` for a few seconds of it).
`animatic` makes a whole existing video in it: finished for a composited
style, frames cut to the narration for a generated one (for which `film`
animates it, with FAL_KEY).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.channels import load_channels                           # noqa: E402
from core.logging_setup import configure                          # noqa: E402
from pipeline.animation import bible, preview, samples, style     # noqa: E402
from pipeline.animation.style import gallery, preview as style_preview  # noqa: E402


def _channel(key: str, args):
    channels = load_channels()
    if key not in channels:
        raise SystemExit(f"No channel {key!r}. Channels: {', '.join(channels)}")
    channel = channels[key]
    a = channel.animation
    if getattr(args, "start", None):
        sp = style.starting_point(args.start)
        if not sp:
            raise SystemExit(f"No starting point {args.start!r}; see `styles`.")
        a.style = dict(sp["answers"])
    for pair in getattr(args, "set", None) or []:
        question, _, option = pair.partition("=")
        a.style = {**a.style, question.strip(): option.strip()}
    if getattr(args, "notes", None) is not None:
        a.style_notes = args.notes
    answers, changed = style.normalise(a.style)
    if changed:
        print(f"Changed to fit: {', '.join(f'{q} -> {answers[q]}' for q in changed)}")
    return channel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("styles")
    sub.add_parser("questions")
    m = sub.add_parser("materials")
    m.add_argument("--id", action="append")
    m.add_argument("--force", action="store_true")
    g = sub.add_parser("gallery")
    g.add_argument("--id", action="append")
    g.add_argument("--force", action="store_true")
    for name in ("preview", "frames", "cast", "animatic", "film"):
        p = sub.add_parser(name)
        p.add_argument("channel")
        if name in ("animatic", "film"):
            p.add_argument("video")
        p.add_argument("--start")
        p.add_argument("--set", action="append", metavar="QUESTION=OPTION")
        p.add_argument("--notes")
        if name == "preview":
            p.add_argument("--subject", default="")
            p.add_argument("--moving", action="store_true")
            p.add_argument("--wide", action="store_true")
    args = parser.parse_args()
    configure()

    if args.command == "styles":
        for sp in style.starting_points():
            print(f"{sp['id']:22} {sp['label']}: {sp['description']}")
        return 0
    if args.command == "questions":
        for q in style.questions():
            print(q["ask"])
            for o in q["options"]:
                print(f"    {q['id']}={o['id']:18} {o['label']}")
        return 0
    if args.command == "materials":
        for path in samples.draw(args.id, force=args.force):
            print(path)
        return 0
    if args.command == "gallery":
        for path in gallery.draw(args.id, force=args.force):
            print(path)
        return 0
    channel = _channel(args.channel, args)
    fmt, look = style.compile(channel.animation)
    print(look["description"])
    if args.command == "preview":
        make = style_preview.moving if args.moving else style_preview.still
        print(make(channel, channel.animation, subject=args.subject,
                   frame="wide" if args.wide else "vertical"))
    elif args.command == "frames":
        for path in bible.draw_style_frames(channel, look):
            print(path)
    elif args.command == "cast":
        for member in bible.cast_members(channel):
            print(bible.cast_sheet(channel, look, member))
    else:
        print(preview.run(channel, Path(args.video), animate=args.command == "film"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
