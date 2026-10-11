"""
A production stage as a job (decision 074): its work done, its state in
core.production kept honest, whatever happens.

Each stage starts only once every stage before it is approved, and ends
"ready" for the owner to look at (or "failed", with the reason shown).
Redoing an earlier stage makes every later one stale.
"""

from __future__ import annotations

import shutil
from types import SimpleNamespace

from core import curriculum, production
from core.errors import PipelineError
from core.logging_setup import get_logger

log = get_logger(__name__)


def run_stage(channel, subtopic_id: str, stage: str, note: str = "", only: list = None,
              chapter: int = 0, notes: dict = None) -> SimpleNamespace:
    """Do one stage of a production. `note`: the owner's instruction for
    a rewrite. `only`/`notes`: stills to redraw, and why. `chapter`: one
    chapter of the script to rewrite. Returns what a job reports."""
    row = curriculum.find(channel.key, subtopic_id)
    if row is None:
        raise PipelineError(f"no plan entry {subtopic_id}", user_message="That video is no longer in the plan.")
    title = row["title"]
    data = production.load(channel.key, subtopic_id, title)
    if stage not in production.STAGES:
        raise PipelineError(f"unknown stage {stage}", user_message="That isn't a stage of a production.")
    if not production.can_start(data, stage) and not (stage == "teasers" and _making_teasers(data)):
        raise PipelineError(f"{stage} before its stages are approved", user_message=(
            "Approve the stages before this one first."))
    production.update(channel.key, subtopic_id, lambda d: production.mark(d, stage, "working"), title)
    try:
        result = _do(channel, row, data, stage, note, only, chapter, notes)
    except Exception as exc:
        from core.errors import friendly_message
        production.update(channel.key, subtopic_id,
                          lambda d: production.mark(d, stage, "failed", friendly_message(exc)))
        raise
    if stage in ("outline", "script", "stills"):
        retire_video(channel, subtopic_id)
    return result


def retire_video(channel, subtopic_id: str, keep: str = "") -> bool:
    """A made video that no longer follows from its plan (an earlier stage
    was redone, or a new one made) is discarded, unless it has gone out,
    and remembered as the old version (decision 081). Restorable from
    the channel's Videos like any discard. True if one was."""
    from core import gallery
    data = production.load(channel.key, subtopic_id)
    rel = (data.get("video") or {}).get("path")
    if not rel or rel == keep:
        return False
    path = _root(channel) / rel
    if not path.exists():
        return False
    info = gallery.load_publish_info(path)
    if gallery.is_out(info) or info.get("discarded"):
        return False
    gallery.set_discarded(path, True, reason="remade")

    def note(d):
        d.setdefault("video", {})["retired"] = rel
    production.update(channel.key, subtopic_id, note)
    log.info(f"  [documentary] {rel} discarded: it no longer follows from its plan")
    return True


def _making_teasers(data: dict) -> bool:
    return bool((data.get("teasers") or {}).get("scripts"))


def _do(channel, row, data, stage, note, only, chapter, notes) -> SimpleNamespace:
    key, sid, title = channel.key, row["id"], row["title"]
    folder = production.folder(key, sid)
    done = SimpleNamespace(video_path=None, warnings=[], similarity=None)
    angle = production.chosen_angle(data)
    title = angle.get("title") or title

    if stage == "pitch":
        from pipeline.documentary import pitch
        made = pitch.write(channel, row, note)
        production.update(key, sid, lambda d: production.made(d, "pitch", made))
        return done

    if stage == "outline":
        from pipeline.documentary import outline
        made = outline.write(channel, row, note, angle=angle)
        production.update(key, sid, lambda d: production.made(d, "outline", made))
        return done

    if stage == "script":
        from pipeline.documentary import editor, script
        if chapter and data.get("script"):
            made = script.rewrite_chapter(channel, title, data["outline"], data["script"], chapter, note, angle)
        else:
            made = script.write(channel, title, data["outline"], note, angle)
            # The editor's read, and the weakest chapters written again (decision 086).
            made = editor.edit(channel, title, data["outline"], made, angle)
        production.update(key, sid, lambda d: production.made(d, "script", made))
        return done

    if stage == "stills":
        from pipeline.documentary import cast, media, stills
        cast.merge(key, sid, data["outline"].get("cast") or [])
        scenes = data["script"]["scenes"]
        target = folder / "stills"
        if only is None:
            # Drawn afresh: the old ones belong to an older script.
            shutil.rmtree(target, ignore_errors=True)
        wanted = list(range(len(scenes))) if only is None else list(only)
        # Paintings and cards first (decision 086); any that can't be made
        # are drawn instead, so no scene is left without a picture.
        others, credits, draw_instead = media.make(channel, scenes, target, only=wanted)
        to_draw = [i for i in wanted if scenes[i].get("medium", "picture") == "picture"] + draw_instead
        drawn = stills.draw(channel, data["outline"], scenes, target, frame="wide", only=to_draw,
                            notes=notes) if to_draw else {}
        made_now = {**drawn, **others}
        names = {str(i): str(p.relative_to(folder)).replace("\\", "/") for i, p in made_now.items()}
        shown = {str(i): "drawn" for i in drawn}
        shown.update({str(i): ("card" if scenes[i].get("medium") == "card" else "painting") for i in others})

        def store(d):
            kept = {} if only is None else dict(d.get("stills") or {})
            kept.update(names)
            kinds = {} if only is None else dict(d.get("shown") or {})
            kinds.update(shown)
            credit = {} if only is None else dict(d.get("credits") or {})
            for i in wanted:
                credit.pop(str(i), None)
            credit.update({str(i): c for i, c in credits.items()})
            d["shown"], d["credits"] = kinds, credit
            production.made(d, "stills", kept)
        production.update(key, sid, store)
        missing = len(scenes) - len(production.load(key, sid)["stills"])
        if missing:
            done.warnings.append(f"{missing} still(s) couldn't be drawn; redraw them from the storyboard.")
        return done

    if stage == "video":
        from pipeline.documentary import render
        made = render.make(channel, data, folder)
        relpath = str(made.video_path.relative_to(_root(channel))).replace("\\", "/")
        retire_video(channel, sid, keep=relpath)
        production.update(key, sid, lambda d: production.made(d, "video", {"path": relpath}))
        # The plan entry is made now: the scheduler moves on from it.
        if (curriculum.find(key, sid) or {}).get("status") == curriculum.PENDING:
            curriculum.claim(key, sid)
        curriculum.attach_video(key, sid, made.video_path.stem)
        return made

    if stage == "teasers":
        from pipeline.documentary import teasers
        if note or not _making_teasers(data) or production.state(data, "teasers") in ("stale", "todo"):
            scripts = teasers.write(channel, title, data["outline"], data["script"], note, angle)
            production.update(key, sid, lambda d: production.made(d, "teasers", {"scripts": scripts, "videos": []}))
            return done
        paths = teasers.make(channel, data, folder)
        rel = [str(p.relative_to(_root(channel))).replace("\\", "/") for p in paths]

        def store(d):
            d["teasers"]["videos"] = rel
            production.mark(d, "teasers", "approved")
        production.update(key, sid, store)
        return teasers.summary(paths)

    raise PipelineError(f"unknown stage {stage}", user_message="That isn't a stage of a production.")


def _root(channel):
    from core import gallery
    return gallery.resolve_output_dir(channel.output_dir)
