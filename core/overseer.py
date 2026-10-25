"""
The overseer's tools (decision 094): what a scheduled Claude session uses
to read a film at its two checkpoints, fix what's wrong and approve it.

The pipeline's own checks catch most faults, but not the ones that need
judgement: a film whose whole thesis was false ("salt never leaves the
sea"), an invented quote, a prop leaking into every picture. Those were
caught by reading the script and looking at the storyboard. An overseen
channel (`documentary.overseen`) leaves its script and storyboard
"ready" for this; the autopilot does everything else, overnight, at
batch prices. The session runs on the owner's Claude subscription, not
the API.

    python -m core.overseer status
    python -m core.overseer script <channel> <id>
    python -m core.overseer edit <channel> <id> <scene> --narration "..."
    python -m core.overseer board <channel> <id>
    python -m core.overseer redraw <channel> <id> 4,17 --note "..."
    python -m core.overseer teasers <channel> <id>
    python -m core.overseer edit-teaser <channel> <id> <teaser> <line> --narration "..."
    python -m core.overseer approve <channel> <id> <script|stills|teasers>
    python -m core.overseer note <channel> <id> "what you did and why"

And the channel's topic bank (decision 118), which it keeps stocked with
films the channel can make well:

    python -m core.overseer topics <channel>
    python -m core.overseer add-topic <channel> "Title" "What it covers"
    python -m core.overseer add-subtopics <channel> <topic> "Question? :: angle" ...
    python -m core.overseer skip-subtopic <channel> <id> "why"

How to review is in docs/overseer.md. Every change is recorded in the
production's history as the overseer's.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from core import channels as channel_config
from core import curriculum, film_budget, production


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def overseen() -> dict:
    return {k: c for k, c in channel_config.load_channels().items()
            if c.format == "documentary" and getattr(c.documentary, "overseen", False) and not c.archived}


def status() -> list:
    """[{channel, id, title, stages, waiting, spent, ceiling}] for each
    overseen channel's films in progress."""
    out = []
    for key in overseen():
        for data in production.all_for(key):
            stages = {s: production.state(data, s) for s in production.STAGES}
            teasers_due = stages["teasers"] == "ready" and not (data.get("teasers") or {}).get("reviewed")
            if (stages["video"] in ("ready", "approved") and not teasers_due) or stages["pitch"] == "todo":
                continue
            waiting = [s for s in ("script", "stills") if stages[s] == "ready"] + (["teasers"] if teasers_due else [])
            out.append({"channel": key, "id": data["subtopic_id"], "title": data.get("title", ""),
                        "stages": stages, "waiting": waiting,
                        "spent": film_budget.spent(key, data["subtopic_id"]),
                        "ceiling": film_budget.ceiling(key, data["subtopic_id"])})
    return out


def script_sheet(key: str, sid: str) -> str:
    """The film's script as a reviewer reads it: angle, settings, then
    every scene with its picture, then what the editors already changed."""
    data = production.load(key, sid)
    angle = production.chosen_angle(data)
    outline, script = data.get("outline") or {}, data.get("script") or {}
    lines = [f"FILM {key}/{sid}: {data.get('title', '')}",
             f"Title: {production.packaging(data).get('title', '')}",
             f"Thumbnail words: {(production.packaging(data).get('thumbnail') or {}).get('words', '')}",
             f"Planning notes, never shown or spoken: hook \"{angle.get('hook', '')}\"; "
             f"promise \"{angle.get('promise', '')}\"", "",
             "SETTINGS:"] + [f"  - {s['name']} ({s['scale']}): {s['description']}" for s in outline.get("settings") or []]
    lines += ["CAST:"] + [f"  - {m['name']} ({m.get('kind')}; in {', '.join(m.get('settings') or []) or 'anywhere'}): "
                          f"{m.get('description', '')[:160]}" for m in outline.get("cast") or []]
    chapter = 0
    for i, s in enumerate(script.get("scenes") or []):
        if s["chapter"] != chapter:
            chapter = s["chapter"]
            title = (outline.get("chapters") or [{}] * chapter)[chapter - 1].get("title", "")
            lines.append(f"\n== Chapter {chapter}: {title}")
        if s.get("medium") == "card":
            card = s.get("card") or {}
            lines.append(f"[{i}] CARD {card.get('kind')}: heading \"{card.get('heading', '')}\" | value "
                         f"\"{card.get('value', '')}\" | caption \"{card.get('caption', '')}\" | items "
                         f"\"{'; '.join(card.get('items') or [])}\"")
        else:
            again = f" (shows scene {s['same_as']}'s picture again)" if isinstance(s.get("same_as"), int) else ""
            lines.append(f"[{i}] picture in {s.get('setting') or '?'}{again}: {s.get('direction', '')[:220]}")
        lines.append(f"     SAYS: {s['narration']}")
    lines += ["", f"DESCRIPTION: {script.get('description', '')}", "",
              "ALREADY CHANGED BY THE EDITORS:"]
    lines += [f"  - fact check, scene {f['scene']}: {f['problem']}" for f in script.get("facts") or []]
    lines += [f"  - repeat pass rewrote scene {r['scene']} (repeated {r['earlier']})" for r in script.get("restated") or []]
    lines += [f"  - picture editor, scene {c['scene']} {c['action']}: {c['why']}"
              for c in (script.get("pictures") or {}).get("changes") or []]
    if (script.get("pictures") or {}).get("unfixed"):
        lines += ["PICTURE RULES STILL BROKEN:"] + [f"  - scene {u['scene']}: {u['problem']}"
                                                 for u in script["pictures"]["unfixed"]]
    return "\n".join(lines)


def _history(d: dict, did: str) -> None:
    d.setdefault("history", []).append({"at": _now(), "stage": "script", "did": did, "by": "overseer"})


def edit(key: str, sid: str, scene: int, narration: str = None, direction: str = None,
         card_value: str = None, card_items: str = None, description: str = None,
         card_heading: str = None, card_caption: str = None, thumb_words: str = None) -> None:
    def change(d):
        scenes = d["script"]["scenes"]
        if description is not None:
            d["script"]["description"] = description
            _history(d, "rewrote the description")
        if thumb_words is not None:
            # The words on the thumbnail of the angle the film goes out with (decision 098).
            angle = production.packaging(d)
            if angle:
                angle.setdefault("thumbnail", {})["words"] = " ".join(thumb_words.split())
                _history(d, "changed the thumbnail words")
        if scene is None or scene < 0:
            return
        s = scenes[scene]
        if narration is not None:
            s["narration"] = " ".join(narration.split())
        if direction is not None:
            s["direction"] = " ".join(direction.split())
            s.pop("same_as", None)
        if card_value is not None and s.get("card"):
            s["card"]["value"] = card_value
        if card_items is not None and s.get("card"):
            s["card"]["items"] = [x.strip() for x in card_items.split(";") if x.strip()]
        if card_heading is not None and s.get("card"):
            s["card"]["heading"] = " ".join(card_heading.split())
        if card_caption is not None and s.get("card"):
            s["card"]["caption"] = " ".join(card_caption.split())
        _history(d, f"edited scene {scene}")
    production.update(key, sid, change)


def board(key: str, sid: str, per_sheet: int = 40) -> list:
    """Numbered contact sheets of the storyboard, for looking at. Returns
    their paths."""
    from PIL import Image, ImageDraw
    data = production.load(key, sid)
    folder = production.folder(key, sid)
    stills, scenes = data.get("stills") or {}, (data.get("script") or {}).get("scenes") or []
    keys = sorted(stills, key=int)
    out_dir = folder / "review"
    out_dir.mkdir(exist_ok=True)
    paths, w, h, cols = [], 384, 216, 8
    for n, start in enumerate(range(0, len(keys), per_sheet), start=1):
        chunk = keys[start:start + per_sheet]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (w * cols, h * rows), "white")
        for j, k in enumerate(chunk):
            im = Image.open(folder / stills[k]).convert("RGB").resize((w, h))
            again = scenes[int(k)].get("same_as") if int(k) < len(scenes) else None
            tag = f"{k}={again}" if isinstance(again, int) else k
            draw = ImageDraw.Draw(im)
            draw.rectangle((0, 0, 9 * len(tag) + 8, 18), fill="black")
            draw.text((4, 3), tag, fill="white")
            sheet.paste(im, ((j % cols) * w, (j // cols) * h))
        path = out_dir / f"board_{n}.jpg"
        sheet.save(path, quality=85)
        paths.append(path)
    return paths


def redraw(key: str, sid: str, scenes: list, note: str = "") -> dict:
    """Redraw these pictures now (a few cents each), with the reason."""
    from pipeline.documentary import run
    channel = channel_config.load_channels()[key]
    notes = {i: note for i in scenes} if note else None
    run.run_stage(channel, sid, "stills", only=list(scenes), notes=notes)
    production.update(key, sid, lambda d: d.setdefault("history", []).append(
        {"at": _now(), "stage": "stills", "did": f"redrew {', '.join(map(str, scenes))}: {note}"[:300],
         "by": "overseer"}))
    return {"redrawn": scenes}


def teaser_sheet(key: str, sid: str) -> str:
    """The teasers' scripts as a reviewer reads them, each line numbered,
    with the picture it's shown over (decision 111)."""
    clashes = teaser_title_clashes(key, sid)
    data = production.load(key, sid)
    scenes = (data.get("script") or {}).get("scenes") or []
    lines = [f"TEASERS for {key}/{sid}: {data.get('title', '')}",
             "Read them against the film's narration (python -m core.overseer script ...).", ""]
    if clashes:
        lines += ["TITLE CLASH (fix before approving: every video needs its own title): " + "; ".join(clashes), ""]
    for n, t in enumerate((data.get("teasers") or {}).get("scripts") or []):
        lines.append(f"== Teaser {n}: {t.get('title', '')}")
        lines.append(f"   description: {t.get('description', '')}")
        for k, s in enumerate(t.get("scenes") or []):
            pic = s.get("picture")
            shown = f" (picture {pic}: {scenes[pic].get('direction', '')[:100]})" if isinstance(pic, int) and pic < len(scenes) else ""
            lines.append(f"   [{k}] {s.get('narration', '')}{shown}")
        lines.append("")
    return "\n".join(lines)


def edit_teaser(key: str, sid: str, teaser: int, line: int, narration: str = None, title: str = None) -> None:
    def change(d):
        t = d["teasers"]["scripts"][teaser]
        if title is not None:
            t["title"] = " ".join(title.split())
        if narration is not None:
            t["scenes"][line]["narration"] = " ".join(narration.split())
        d.setdefault("history", []).append({"at": _now(), "stage": "teasers", "did": f"edited teaser {teaser}",
                                            "by": "overseer"})
    production.update(key, sid, change)


def teaser_title_clashes(key: str, sid: str) -> list:
    """Titles a film's teasers share with each other or with the channel's
    other videos."""
    from core import gallery
    data = production.load(key, sid)
    titles = [" ".join((t.get("title") or "").lower().split()) for t in (data.get("teasers") or {}).get("scripts") or []]
    clashes = [t for i, t in enumerate(titles) if t and t in titles[:i]]
    channel = channel_config.load_channels().get(key)
    if channel is None:
        return sorted(set(clashes))
    root = gallery.resolve_output_dir(channel.output_dir)
    mine = {str((root / v).resolve()) for v in (data.get("teasers") or {}).get("videos") or []}
    for path in gallery.videos_in(root):
        info = gallery.load_publish_info(path)
        if str(path.resolve()) in mine or info.get("discarded"):
            continue
        title = " ".join((info.get("title") or "").lower().split())
        if title and title in titles:
            clashes.append(title)
    return sorted(set(clashes))


def approve(key: str, sid: str, stage: str) -> None:
    if stage == "teasers" and teaser_title_clashes(key, sid):
        raise SystemExit("Two videos would share a title: " + "; ".join(teaser_title_clashes(key, sid))
                         + ". Give each teaser its own title (edit-teaser ... --title) first.")
    if stage == "teasers":
        # Their scripts read: the autopilot makes them now (decision 111).
        def change(d):
            d.setdefault("teasers", {})["reviewed"] = True
            d.setdefault("history", []).append({"at": _now(), "stage": "teasers", "did": "approved",
                                                "by": "overseer"})
        production.update(key, sid, change)
        return
    if stage not in ("script", "stills"):
        raise SystemExit("The overseer approves only the script, the storyboard and the teasers.")
    production.approve(key, sid, stage, by="overseer")


def note(key: str, sid: str, text: str) -> None:
    """A note for the owner, shown on the production page."""
    production.update(key, sid, lambda d: d.setdefault("overseer", []).append({"at": _now(), "text": text}))


# --- the topic bank (decision 118) ---------------------------------------------------

def _plan_channel(key: str):
    """A documentary channel with a plan, or an error that says so: the
    overseer never touches another channel's plan."""
    channel = channel_config.load_channels().get(key)
    if channel is None or channel.format != "documentary" or not curriculum.exists(key):
        raise SystemExit(f"{key} isn't a documentary channel with a topic plan.")
    return channel


def bank(key: str) -> dict:
    """{"waiting", "low"} for a channel's plan."""
    p = curriculum.progress(key)
    return {"waiting": p["pending"], "low": p["running_low"]}


def _stats_of(out_dir: Path, stem: str):
    from core import gallery
    if not stem:
        return None
    found = next(iter(sorted(out_dir.rglob(f"{stem}.mp4"))), None)
    return gallery.load_stats(found) if found else None


def topics_sheet(key: str) -> str:
    """A channel's plan as the overseer reviews it: what the channel can
    make well, its topics, every subtopic waiting in order, the films made
    with how the published ones are doing, what was skipped and why, and
    whether it's running low."""
    from collections import Counter
    from core import gallery
    from pipeline.documentary import kinds
    channel = _plan_channel(key)
    data = curriculum.load(key)
    level = bank(key)
    lines = [f"PLAN {key}: {data.get('subject', '')}",
             f"{level['waiting']} films waiting to be made; the bank runs low below {curriculum.LOW_WATER_MARK}."
             + (" RUNNING LOW: add one topic (docs/overseer.md, The topic bank)." if level["low"] else ""),
             "", kinds.TOPIC_FIT[kinds.of(channel)], "", "TOPICS:"]
    for t in data["topics"]:
        counts = Counter(s["status"] for s in data["subtopics"] if s["topic"] == t["id"])
        made = counts.get(curriculum.USED, 0) + counts.get(curriculum.PUBLISHED, 0)
        lines.append(f"  {t['id']} {t['title']}: {t.get('summary', '')} ({counts.get(curriculum.PENDING, 0)} "
                     f"waiting, {made} made, {counts.get(curriculum.SKIPPED, 0)} skipped)")
    lines += ["", "WAITING TO BE MADE, in plan order:"]
    lines += [f"  {s['id']} [{s['topic']}] {s['title']}" + (f" :: {s['angle']}" if s.get("angle") else "")
              for s in data["subtopics"] if s["status"] == curriculum.PENDING]
    lines += ["", "MADE, with how the published ones are doing:"]
    out_dir = gallery.resolve_output_dir(channel.output_dir)
    for s in data["subtopics"]:
        if s["status"] not in (curriculum.USED, curriculum.PUBLISHED):
            continue
        stats = _stats_of(out_dir, s.get("video_stem")) or {}
        how = ""
        if stats.get("views") is not None:
            how = f": {stats['views']} views"
            if stats.get("avg_view_percent") is not None:
                how += f", {round(float(stats['avg_view_percent']))}% of it watched on average"
        lines.append(f"  {s['id']} {s['title']}" + (how or ": not out yet"))
    skipped = [s for s in data["subtopics"] if s["status"] == curriculum.SKIPPED]
    if skipped:
        lines += ["", "SKIPPED:"] + [f"  {s['id']} {s['title']}" + (f" ({s['note']})" if s.get("note") else "")
                                     for s in skipped]
    return "\n".join(lines)


def add_topic(key: str, title: str, summary: str) -> dict:
    """A new topic at the end of the plan, at the level of the last one."""
    _plan_channel(key)
    topics = curriculum.load(key)["topics"]
    level = topics[-1].get("level", "foundation") if topics else "foundation"
    return curriculum.add_topic(key, title, summary, level=level)


def add_subtopics(key: str, topic_id: str, rows: list) -> list:
    """Subtopics for a topic, each "Question? :: one-line angle", in the
    order given. A title already in the plan is dropped. Returns what was
    added."""
    _plan_channel(key)
    parsed = []
    for row in rows:
        title, _, angle = str(row).partition("::")
        if " ".join(title.split()):
            parsed.append({"title": " ".join(title.split()), "angle": " ".join(angle.split())})
    before = {s["id"] for s in curriculum.subtopics(key)}
    curriculum.add_subtopics(key, topic_id, parsed)
    return [s for s in curriculum.subtopics(key) if s["id"] not in before]


def skip_subtopic(key: str, sid: str, why: str) -> dict:
    """A waiting subtopic taken out of the plan, with why. Only a waiting
    one: a film already being made is the owner's to stop."""
    _plan_channel(key)
    row = curriculum.find(key, sid)
    if row is None:
        raise SystemExit(f"No subtopic {sid} in {key}'s plan.")
    if row["status"] != curriculum.PENDING:
        raise SystemExit(f"{sid} is {row['status']}, not waiting: only a waiting subtopic can be skipped.")
    return curriculum.skip(key, sid, f"overseer: {why}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.overseer")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    for name in ("script", "board", "teasers"):
        p = sub.add_parser(name)
        p.add_argument("channel")
        p.add_argument("id")
    p = sub.add_parser("edit")
    p.add_argument("channel")
    p.add_argument("id")
    p.add_argument("scene", type=int, help="-1 for the description only")
    for flag in ("--narration", "--direction", "--card-value", "--card-items", "--card-heading",
                 "--card-caption", "--description", "--thumb-words"):
        p.add_argument(flag)
    p = sub.add_parser("edit-teaser")
    p.add_argument("channel")
    p.add_argument("id")
    p.add_argument("teaser", type=int)
    p.add_argument("line", type=int)
    p.add_argument("--narration")
    p.add_argument("--title")
    p = sub.add_parser("redraw")
    p.add_argument("channel")
    p.add_argument("id")
    p.add_argument("scenes", help="comma-separated scene numbers")
    p.add_argument("--note", default="")
    p = sub.add_parser("approve")
    p.add_argument("channel")
    p.add_argument("id")
    p.add_argument("stage")
    p = sub.add_parser("note")
    p.add_argument("channel")
    p.add_argument("id")
    p.add_argument("text")
    p = sub.add_parser("topics")
    p.add_argument("channel")
    p = sub.add_parser("add-topic")
    p.add_argument("channel")
    p.add_argument("title")
    p.add_argument("summary")
    p = sub.add_parser("add-subtopics")
    p.add_argument("channel")
    p.add_argument("topic")
    p.add_argument("subtopics", nargs="+", help='each "Question? :: one-line angle"')
    p = sub.add_parser("skip-subtopic")
    p.add_argument("channel")
    p.add_argument("id")
    p.add_argument("why")
    args = parser.parse_args(argv)
    if args.command == "status":
        found = status()
        if not found:
            print("No overseen film in progress.")
        for f in found:
            print(f"{f['channel']}/{f['id']} {f['title']}: waiting for review: {', '.join(f['waiting']) or 'nothing'}; "
                  f"stages {f['stages']}; spent ${f['spent']:.2f} of ${f['ceiling']:.2f}")
        for key in overseen():
            if curriculum.exists(key):
                level = bank(key)
                print(f"{key} topic bank: {level['waiting']} films waiting to be made"
                      + ("; RUNNING LOW: see docs/overseer.md, The topic bank" if level["low"] else ""))
    elif args.command == "script":
        sys.stdout.reconfigure(encoding="utf-8")
        print(script_sheet(args.channel, args.id))
    elif args.command == "edit":
        edit(args.channel, args.id, args.scene, args.narration, args.direction, args.card_value,
             args.card_items, args.description, args.card_heading, args.card_caption, args.thumb_words)
        print("edited")
    elif args.command == "teasers":
        sys.stdout.reconfigure(encoding="utf-8")
        print(teaser_sheet(args.channel, args.id))
    elif args.command == "edit-teaser":
        edit_teaser(args.channel, args.id, args.teaser, args.line, args.narration, args.title)
        print("edited")
    elif args.command == "board":
        for path in board(args.channel, args.id):
            print(path)
    elif args.command == "redraw":
        print(redraw(args.channel, args.id, [int(x) for x in args.scenes.split(",") if x.strip()], args.note))
    elif args.command == "approve":
        approve(args.channel, args.id, args.stage)
        print("approved", args.stage)
    elif args.command == "note":
        note(args.channel, args.id, args.text)
        print("noted")
    elif args.command == "topics":
        sys.stdout.reconfigure(encoding="utf-8")
        print(topics_sheet(args.channel))
    elif args.command == "add-topic":
        topic = add_topic(args.channel, args.title, args.summary)
        print(f"added topic {topic['id']}: {topic['title']}")
    elif args.command == "add-subtopics":
        sys.stdout.reconfigure(encoding="utf-8")
        added = add_subtopics(args.channel, args.topic, args.subtopics)
        for s in added:
            print(f"added {s['id']}: {s['title']}")
        if len(added) < len(args.subtopics):
            print(f"{len(args.subtopics) - len(added)} left out: already in the plan")
    elif args.command == "skip-subtopic":
        skip_subtopic(args.channel, args.id, args.why)
        print(f"skipped {args.id}")
    return 0


if __name__ == "__main__":
    from core.logging_setup import configure
    configure()
    raise SystemExit(main())
