"""
Thumbnail tests, and what a channel learns from them (decision 083).

A channel has a recipe, its best thumbnail so far (pipeline.thumbnail_
variants). A round tests three: A, the recipe as it is; B and C, each
with one setting changed. What happens next is a coordinate search:
- B or C wins: its change is kept, and the next round pushes the same
  setting a step further, beside a fresh change elsewhere;
- A wins: the changes tried were worse, so their steps are halved (or,
  for a choice, the next option is tried) and other settings come up.

Shorts are tested by rotation, the app changing the thumbnail itself.
Each short in a round shows A, B and C in turn, three days each, twice,
after two days left alone (a video's first days are mostly its
subscribers). Each short starts the cycle at a different variant, so a
video's age doesn't favour one. Click-through comes from the Reporting
API (core.reach). Days a thumbnail changed on are left out. A round
ends when its shorts have finished and their figures are in, and it
needs MIN_IMPRESSIONS for each variant to name a winner.

Long quizzes use YouTube's own Test & Compare, which runs all three at
once and judges by watch time. It's in Studio only, so the app makes
the three, the owner starts the test there and ticks the winner here.

Films are rotated by the app too (decision 117): the owner wanted the
tests done for them, and Studio's test can't be driven through the API.
A film's three are made with it, and it starts rotating when it's out:
A for two days, then A, B and C three days each, twice. Films planned
within a week share a style or refine round (FILM_ROUND_SIZE), so a
round has more impressions to judge by; a content round is one film's,
and rotates its titles as well when the channel may be managed. Nothing
starts until the reach reports work, since a rotation nobody can
measure would be twenty days for nothing.

Kept in channels/<key>/thumbnail_tests.json, which moves with a renamed
channel.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core.errors import PipelineError
from core.logging_setup import get_logger
from core.paths import CHANNELS_DIR

log = get_logger(__name__)

SETTLE_DAYS = 2
SEGMENT_DAYS = 3
CYCLES = 2
LABELS = ("A", "B", "C")
ROUND_SIZE = 6              # shorts in one rotation round
MIN_IMPRESSIONS = 300       # per variant, to call a winner
MIN_LEAD = 0.08             # the winner's click-through, at least this much (relatively) ahead
DATA_LAG_DAYS = 3
FILM_ROUND_SIZE = 4         # films sharing one style or refine round (decision 117)
FILM_ROUND_DAYS = 7         # ...planned within this many days of its first
FILM_DAYS = SETTLE_DAYS + SEGMENT_DAYS * 3 * CYCLES

_lock = threading.Lock()


def _path(channel_key: str) -> Path:
    return CHANNELS_DIR / channel_key / "thumbnail_tests.json"


def load(channel_key: str) -> dict:
    from pipeline import thumbnail_variants as tv
    try:
        data = json.loads(_path(channel_key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("recipe", dict(tv.DEFAULT))
    data.setdefault("steps", {name: spec[2] for name, spec in tv.PARAMS.items() if spec[2]})
    data.setdefault("tried", {})          # setting -> options tried and lost, for a choice
    data.setdefault("rounds", [])
    for round_ in data["rounds"]:
        # Decision 117: a film's round is rotated by the app, not run in Studio.
        if round_.get("doc") and round_["kind"] == "studio":
            round_["kind"] = "film"
    return data


def _save(channel_key: str, data: dict) -> None:
    path = _path(channel_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)


def update(channel_key: str, change):
    with _lock:
        data = load(channel_key)
        out = change(data)
        _save(channel_key, data)
        return out


# --- the next changes to try ----------------------------------------------------

def _changed(recipe: dict, name: str, data: dict, direction: int = 1):
    """The recipe with one setting moved, or None if it can't move."""
    from pipeline import thumbnail_variants as tv
    default, options, step = tv.PARAMS[name]
    value = recipe[name]
    if step:
        low, high = options
        step = data["steps"].get(name, step)
        new = round(min(high, max(low, value + direction * step)), 3)
        return None if abs(new - value) < 1e-6 else {**recipe, name: new}
    lost = set(data["tried"].get(name, []))
    for option in options:
        if option != value and option not in lost:
            return {**recipe, name: option}
    return None


def next_variants(data: dict) -> list:
    """[(label, recipe, change)] for a new round: the recipe, and two
    single changes. A setting that just won is pushed further first; the
    rest come round in turn, least recently tried first."""
    from pipeline import thumbnail_variants as tv
    recipe = data["recipe"]
    last = next((r for r in reversed(data["rounds"]) if r.get("result")), None)
    order = list(tv.PARAMS)
    if last:
        won = last["result"].get("winner_change")
        tried = [v["change"][0] for v in last["variants"] if v.get("change")]
        order = ([won[0]] if won else []) + [n for n in order if n not in tried] + [n for n in tried if not won or n != won[0]]
        order = list(dict.fromkeys(order))
    variants = [("A", recipe, None)]
    for name in order:
        if len(variants) == 3:
            break
        direction = 1
        if last and last["result"].get("winner_change") and last["result"]["winner_change"][0] == name:
            w = last["result"]["winner_change"]
            if isinstance(w[2], (int, float)) and isinstance(w[1], (int, float)):
                direction = 1 if w[2] > w[1] else -1
        moved = _changed(recipe, name, data, direction) or _changed(recipe, name, data, -direction)
        if moved:
            variants.append((LABELS[len(variants)], moved, [name, recipe[name], moved[name]]))
    return variants


def learn(data: dict, round_: dict, winner: str) -> None:
    """Take a finished round's result into the recipe."""
    from pipeline import thumbnail_variants as tv
    chosen = next(v for v in round_["variants"] if v["label"] == winner)
    round_["result"]["winner"] = winner
    round_["result"]["winner_change"] = chosen.get("change")
    if chosen.get("change"):
        data["recipe"] = dict(chosen["recipe"])
        return
    # A won: the changes tried were worse. Smaller steps for numbers; a
    # choice that lost isn't offered again for a while.
    for v in round_["variants"]:
        if not v.get("change"):
            continue
        name = v["change"][0]
        step = tv.PARAMS[name][2]
        if step:
            data["steps"][name] = max(step / 4, data["steps"].get(name, step) / 2)
        else:
            data["tried"].setdefault(name, []).append(v["change"][2])


# --- rounds ------------------------------------------------------------------------

def open_round(data: dict, kind: str):
    return next((r for r in data["rounds"] if r["kind"] == kind and r["status"] == "running"
                 and (kind != "rotation" or len(r["videos"]) < ROUND_SIZE)), None)


def start_round(data: dict, kind: str) -> dict:
    round_ = {"id": uuid.uuid4().hex[:8], "kind": kind, "status": "running", "started_at": time.time(),
              "variants": [{"label": l, "recipe": r, "change": c} for l, r, c in next_variants(data)],
              "videos": [], "result": {}}
    data["rounds"].append(round_)
    return round_


def join_rotation(channel, video_path, video_id: str) -> dict:
    """A short that has gone out joins this channel's rotation round (a new
    one if none is open). Its variants are drawn now. Returns the round."""
    from pipeline import thumbnail_variants as tv
    video_path = Path(video_path)

    def change(data):
        if any(v["stem"] == video_path.stem for r in data["rounds"] for v in r["videos"]):
            return None
        round_ = open_round(data, "rotation") or start_round(data, "rotation")
        for v in round_["variants"]:
            tv.render_short(channel, video_path, v["recipe"], tv.variant_path(video_path, v["label"]))
        round_["videos"].append({"stem": video_path.stem, "path": str(video_path), "video_id": video_id,
                                 "joined": time.time(), "offset": len(round_["videos"]) % 3, "log": []})
        return round_
    return update(channel.key, change)


def scheduled_label(video: dict, now: float) -> str:
    """The variant a short in rotation should show now, or None when its
    rotation has ended (it then keeps the round's winner, or A)."""
    days = (now - video["joined"]) / 86400
    if days < SETTLE_DAYS:
        return "A"
    segment = int((days - SETTLE_DAYS) // SEGMENT_DAYS)
    if segment >= 3 * CYCLES:
        return None
    return LABELS[(segment + video["offset"]) % 3]


def rotate(channel, now: float = None) -> int:
    """Put each short and film in rotation on the variant it's due
    (core.scheduler, every pass). Returns how many were changed."""
    from core import youtube
    from pipeline import thumbnail_variants as tv
    now = now or time.time()
    films = _reach_ready(channel.key)

    def change(data):
        moved = 0
        for round_ in data["rounds"]:
            if round_["kind"] == "film" and films:
                moved += _rotate_films(channel, round_, now)
        return moved
    changed = update(channel.key, change)
    data = load(channel.key)
    shorts = 0
    for round_ in data["rounds"]:
        if round_["kind"] != "rotation" or round_["status"] != "running":
            continue
        winner = round_.get("result", {}).get("winner")
        for video in round_["videos"]:
            label = scheduled_label(video, now) or winner or "A"
            current = video["log"][-1][1] if video["log"] else "A"
            if label == current:
                continue
            image = tv.variant_path(Path(video["path"]), label)
            try:
                if not image.exists():
                    variant = next(v for v in round_["variants"] if v["label"] == label)
                    tv.render_short(channel, video["path"], variant["recipe"], image)
                youtube.set_thumbnail(channel.key, video["video_id"], image)
            except (PipelineError, OSError, StopIteration) as exc:
                log.warning(f"{channel.key}: couldn't rotate {video['stem']}'s thumbnail: {exc}")
                continue
            video["log"].append([now, label])
            shorts += 1
    if shorts:
        _save(channel.key, data)
    return changed + shorts


def _reach_ready(channel_key: str) -> bool:
    """Whether click-through can be measured: the reach reports' job made
    and no error from them (core.reach)."""
    from core import reach
    data = reach.load(channel_key)
    return bool(data.get("job_id")) and not data.get("error")


def _rotate_films(channel, round_: dict, now: float) -> int:
    """Each film of a film round on the variant it's due. A film starts
    once it's out, on A (the thumbnail it went out with), and keeps the
    winner, or A, once the round is judged. A content round's titles
    change with its thumbnails when the channel may be managed; the
    winning title becomes the film's own."""
    from core import audience, gallery, youtube
    from pipeline import thumbnail_variants as tv
    running = round_["status"] == "running"
    winner = round_.get("result", {}).get("winner")
    titled = any(v.get("title") for v in round_["variants"])
    can_title = titled and youtube.connection(channel.key).get("manage")
    moved = 0
    for video in round_["videos"]:
        path = Path(video["path"])
        if video.get("dropped"):
            continue
        if not video.get("video_id"):
            if not running:
                continue
            info = gallery.load_publish_info(path)
            if info.get("discarded"):
                video["dropped"] = True
                moved += 1
                continue
            vid = audience.video_id(info.get("youtube_url") or "")
            if not vid:
                continue
            started = sum(1 for v in round_["videos"] if v.get("video_id"))
            video.update(video_id=vid, joined=now, offset=started % 3, log=[[now, "A"]],
                         title_a=info.get("title") or "")
            moved += 1
            continue
        label = (scheduled_label(video, now) if running else None) or winner or "A"
        current = video["log"][-1][1] if video["log"] else "A"
        if label == current:
            continue
        variant = next((v for v in round_["variants"] if v["label"] == label), None)
        if variant is None:
            continue
        image = tv.variant_path(path, label)
        title = (variant.get("title") or video.get("title_a") or "") if can_title else ""
        try:
            if not image.exists():
                tv.render_long(channel, path, variant["recipe"], image)
            youtube.set_thumbnail(channel.key, video["video_id"], image)
            if title:
                youtube.set_title(channel.key, video["video_id"], title)
        except (PipelineError, OSError) as exc:
            log.warning(f"{channel.key}: couldn't rotate {video['stem']}'s thumbnail: {exc}")
            continue
        video["log"].append([now, label])
        if title and not running and label == winner:
            info = gallery.load_publish_info(path)
            gallery.save_title_and_description(path, title, info.get("description") or "")
        moved += 1
    return moved


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()


def tally(channel_key: str, round_: dict, now: float = None) -> dict:
    """{label: {"impressions", "clicks", "ctr"}} for a rotation round so
    far, from the days each variant was up all day."""
    from core import reach
    now = now or time.time()
    out = {l: {"impressions": 0, "clicks": 0.0} for l in LABELS}
    for video in round_["videos"]:
        if not video.get("video_id") or video.get("dropped"):
            continue
        changes = {_day(ts) for ts, _ in video["log"]}
        for day, (shown, ctr) in reach.days(channel_key, video["video_id"]).items():
            ts = datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() + 43200
            if day in changes or ts < video["joined"]:
                continue
            live = [l for t, l in video["log"] if t <= ts]
            label = live[-1] if live else "A"
            rate = ctr / 100 if ctr > 1 else ctr
            out[label]["impressions"] += shown
            out[label]["clicks"] += shown * rate
    for t in out.values():
        t["ctr"] = t["clicks"] / t["impressions"] if t["impressions"] else None
    return out


def finish_rotations(channel, now: float = None) -> list:
    """Rounds whose shorts have all finished rotating and whose figures are
    in: their winner named and learnt from. Returns the rounds finished."""
    now = now or time.time()
    done = []

    def change(data):
        for round_ in data["rounds"]:
            if round_["status"] != "running":
                continue
            if round_["kind"] == "film":
                films = [v for v in round_["videos"] if not v.get("dropped")]
                if not films or any(not v.get("video_id") for v in films):
                    continue        # a film still to go out
                end = (FILM_DAYS + DATA_LAG_DAYS) * 86400
            elif round_["kind"] == "rotation" and len(round_["videos"]) >= ROUND_SIZE:
                films = round_["videos"]
                end = (SETTLE_DAYS + SEGMENT_DAYS * 3 * CYCLES + DATA_LAG_DAYS) * 86400
            else:
                continue
            if any(now - v["joined"] < end for v in films):
                continue
            counts = tally(channel.key, round_, now)
            round_["result"]["tally"] = counts
            rated = {l: c["ctr"] for l, c in counts.items() if c["impressions"] >= MIN_IMPRESSIONS and c["ctr"] is not None}
            round_["status"] = "done"
            round_["finished_at"] = now
            if len(rated) < 3:
                round_["result"]["verdict"] = "too few impressions to tell"
                continue
            best = max(rated, key=rated.get)
            others = [c for l, c in rated.items() if l != best]
            clear = rated[best] >= (1 + MIN_LEAD) * max(others)
            if not clear:
                best = "A"
                round_["result"]["verdict"] = ("no clear winner; keeping A" if round_.get("doc")
                                               else "no clear winner; keeping the recipe")
            if round_.get("doc"):
                doc_learn(data, round_, best, clear=clear)
            else:
                learn(data, round_, best)
            done.append(round_["id"])
    update(channel.key, change)
    return done


# --- long videos: Studio's own test ----------------------------------------------------

def _open_film_round(data: dict, phase: str):
    """A style or refine round a new film can join: the same three
    variants, drawn for it, judged together with the round's other films,
    so there are more impressions to go on."""
    if phase not in ("style", "refine"):
        return None
    now = time.time()
    return next((r for r in reversed(data["rounds"]) if r["kind"] == "film" and r["status"] == "running"
                 and r.get("phase") == phase and len(r["videos"]) < FILM_ROUND_SIZE
                 and now - r.get("started_at", 0) < FILM_ROUND_DAYS * 86400), None)


def studio_round(channel, video_path) -> dict:
    """Three thumbnails for a long video: a long quiz's to load into
    YouTube Studio's Test & Compare, a film's for the app to rotate once
    it's out (decision 117). Made once; returns the round."""
    from pipeline import thumbnail_variants as tv
    video_path = Path(video_path)

    from pipeline.documentary import thumbs
    documentary = thumbs.is_documentary(video_path)

    def change(data):
        existing = next((r for r in data["rounds"] if r["kind"] in ("studio", "film")
                         and any(v["stem"] == video_path.stem for v in r["videos"])), None)
        if existing:
            return existing
        if documentary:
            # Decision 115: style, then refine, then content.
            phase = program(data)["phase"]
            round_ = _open_film_round(data, phase)
            if round_ is None:
                round_ = {"id": uuid.uuid4().hex[:8], "kind": "film", "status": "running", "doc": True,
                          "phase": phase, "started_at": time.time(),
                          "variants": doc_variants(data, thumbs.other_angles(video_path)), "videos": [],
                          "result": {}}
                data["rounds"].append(round_)
        else:
            round_ = start_round(data, "studio")
        for v in round_["variants"]:
            tv.render_long(channel, video_path, v["recipe"], tv.variant_path(video_path, v["label"]))
        round_["videos"].append({"stem": video_path.stem, "path": str(video_path), "joined": time.time()})
        return round_
    return update(channel.key, change)


def studio_result(channel_key: str, round_id: str, winner: str) -> dict:
    """The winner Studio named, learnt from."""
    if winner not in LABELS:
        raise PipelineError(f"winner {winner!r}", user_message="Pick A, B or C.")

    def change(data):
        round_ = next((r for r in data["rounds"] if r["id"] == round_id), None)
        if round_ is None:
            raise PipelineError("no round", user_message="That test is no longer here.")
        round_["status"] = "done"
        round_["finished_at"] = time.time()
        if round_.get("doc"):
            doc_learn(data, round_, winner)
        else:
            learn(data, round_, winner)
        return round_
    return update(channel_key, change)



# --- a documentary channel's thumbnail styles (decision 115) ------------------------------
#
# The owner: find the style first (layout, font, colours, picture, angled
# or straight text), then refine it, then test each film's own words and
# picture. Three phases, kept in data["program"]:
# - style: the champion style (A) against the two least-tried others;
# - refine: the champion with one setting changed (B, C), as above;
# - content: the house style, each film's words, picture and title.

STYLE_DEFENCES = 2           # a champion that has seen off challengers twice in a row is the style
REFINE_ROUNDS = 4            # then this many rounds of single changes before testing content


def program(data: dict) -> dict:
    from pipeline.documentary import thumb_styles as ts
    p = data.setdefault("program", {})
    p.setdefault("phase", "style")
    p.setdefault("champion", "panel")
    p.setdefault("families", {})
    p.setdefault("defences", 0)
    p.setdefault("refined", 0)
    data.setdefault("doc_recipe", {"family": p["champion"]})
    data.setdefault("doc_steps", {name: spec[1] for name, spec in ts.PARAMS.items() if spec[1]})
    data.setdefault("doc_tried", {})
    return p


def house_style(channel_key: str) -> dict:
    """The recipe a documentary channel's films are drawn in now: its
    champion style, refined as far as the tests have got."""
    data = load(channel_key)
    p = program(data)
    return dict(data["doc_recipe"]) if p["phase"] != "style" else {"family": p["champion"]}


def _doc_changed(recipe: dict, name: str, data: dict, direction: int = 1):
    from pipeline.documentary import thumb_styles as ts
    options, step = ts.PARAMS[name]
    value = ts.full(recipe)[name]
    if step:
        low, high = options
        step = data["doc_steps"].get(name, step)
        new = round(min(high, max(low, float(value) + direction * step)), 3)
        return None if abs(new - float(value)) < 1e-6 else {**recipe, name: new}
    lost = set(data["doc_tried"].get(name, []))
    for option in options:
        if option != value and option not in lost:
            return {**recipe, name: option}
    return None


def doc_variants(data: dict, angles: list = ()) -> list:
    """The three variants of a new round for a film, as the phase asks:
    [{"label", "recipe", "change", "title"?}]. `angles`: the film's other
    angles, best first ({"title", "words", "subject"}), for content rounds."""
    from pipeline.documentary import thumb_styles as ts
    p = program(data)
    if p["phase"] == "style":
        champion = p["champion"]
        # Rounds still running count, so films tested side by side try different styles.
        seen = {f: p["families"].get(f, {}).get("rounds", 0) for f in ts.FAMILIES}
        for r in data["rounds"]:
            if r["kind"] == "film" and r["status"] == "running":
                for v in r["variants"]:
                    family = v["recipe"].get("family")
                    if family in seen:
                        seen[family] += 1
        names = list(ts.FAMILIES)
        others = sorted((f for f in names if f != champion), key=lambda f: (seen[f], names.index(f)))
        return [{"label": "A", "recipe": {"family": champion}, "change": None}] + [
            {"label": label, "recipe": {"family": f}, "change": ["style", champion, f]}
            for label, f in zip("BC", others[:2])]
    base = dict(data["doc_recipe"])
    if p["phase"] == "refine":
        variants = [{"label": "A", "recipe": base, "change": None}]
        last = next((r for r in reversed(data["rounds"]) if r.get("doc") and r.get("phase") == "refine"
                     and r.get("result", {}).get("winner")), None)
        won = (last or {}).get("result", {}).get("winner_change")
        names = list(ts.PARAMS)
        start = p["refined"] % len(names)
        order = names[start:] + names[:start]          # the settings come round in turn
        if won and won[0] in ts.PARAMS:
            order = [won[0]] + [n for n in order if n != won[0]]   # a change that won is pushed further
        for name in order:
            if len(variants) == 3:
                break
            direction = 1
            if won and won[0] == name and isinstance(won[2], (int, float)) and isinstance(won[1], (int, float)):
                direction = 1 if won[2] > won[1] else -1
            moved = _doc_changed(base, name, data, direction) or _doc_changed(base, name, data, -direction)
            if moved:
                variants.append({"label": "ABC"[len(variants)], "recipe": moved,
                                 "change": [name, ts.full(base)[name], ts.full(moved)[name]]})
        return variants
    # content: the house style throughout; each film's own words, picture and title vary.
    variants = [{"label": "A", "recipe": base, "change": None}]
    for label, angle in zip("BC", angles):
        recipe = {**base, "words": angle.get("words", "")}
        change = ["words", None, angle.get("words", "")]
        if label == "C" and angle.get("subject"):
            recipe["draw_subject"] = angle["subject"]
            change = ["words and picture", None, angle.get("words", "")]
        variants.append({"label": label, "recipe": recipe, "change": change, "title": angle.get("title", "")})
    return variants


def doc_learn(data: dict, round_: dict, winner: str, clear: bool = True) -> None:
    """A documentary round's result into the program. Without a `clear`
    winner, a style round's styles count as tried but nothing has won:
    a champion isn't crowned by a tie."""
    from pipeline.documentary import thumb_styles as ts
    p = program(data)
    chosen = next(v for v in round_["variants"] if v["label"] == winner)
    round_["result"]["winner"] = winner
    round_["result"]["winner_change"] = chosen.get("change")
    phase = round_.get("phase", p["phase"])
    if phase == "style":
        for v in round_["variants"]:
            family = v["recipe"].get("family")
            stats = p["families"].setdefault(family, {"rounds": 0, "wins": 0})
            stats["rounds"] += 1
            if clear and v["label"] == winner:
                stats["wins"] += 1
        if not clear:
            return
        family = chosen["recipe"].get("family")
        if family == p["champion"]:
            p["defences"] += 1
        else:
            p["champion"], p["defences"] = family, 0
        tried_all = all(p["families"].get(f, {}).get("rounds") for f in ts.FAMILIES)
        if p["phase"] == "style" and (p["defences"] >= STYLE_DEFENCES or
                                      (tried_all and p["families"][p["champion"]]["wins"] >= 2)):
            p["phase"] = "refine"
            data["doc_recipe"] = {"family": p["champion"]}
        return
    if phase == "refine":
        if chosen.get("change"):
            data["doc_recipe"] = dict(chosen["recipe"])
        else:
            for v in round_["variants"]:
                if not v.get("change"):
                    continue
                name = v["change"][0]
                step = ts.PARAMS.get(name, (None, None))[1]
                if step:
                    data["doc_steps"][name] = max(step / 4, data["doc_steps"].get(name, step) / 2)
                else:
                    data["doc_tried"].setdefault(name, []).append(v["change"][2])
        p["refined"] += 1
        if p["phase"] == "refine" and p["refined"] >= REFINE_ROUNDS:
            p["phase"] = "content"


def doc_change_text(variant: dict) -> str:
    """What a documentary variant tries, in a few words."""
    from pipeline.documentary import thumb_styles as ts
    change = variant.get("change")
    if not change or change[0] == "style":
        return ts.describe(variant["recipe"])
    name, _before, after = change
    if name in ("words", "words and picture"):
        return f"{name}: {after}"
    return f"{ts.SETTING_NAMES.get(name, name)}: {str(after).replace('_', ' ')}"


def film_status(channel_key: str, round_: dict, stem: str, now: float = None) -> dict:
    """How far one film's test has got, for its page: {"state": "waiting"
    (not out yet), "rotating", "judging" (rotated, figures to come) or
    "done"; "day" and "days" of its rotation; "showing", the variant up
    now; "counts", the round's figures so far}."""
    now = now or time.time()
    video = next((v for v in round_["videos"] if v["stem"] == stem), None)
    out = {"days": FILM_DAYS, "counts": round_.get("result", {}).get("tally") or {}}
    if not out["counts"] and any(v.get("video_id") for v in round_["videos"]):
        out["counts"] = tally(channel_key, round_, now)
    if round_["status"] != "running":
        out["state"] = "done"
    elif not video or not video.get("video_id"):
        out["state"] = "waiting"
    else:
        out.update(state="rotating" if scheduled_label(video, now) else "judging",
                   day=min(FILM_DAYS, int((now - video["joined"]) // 86400) + 1),
                   showing=video["log"][-1][1] if video["log"] else "A")
    return out


def for_page(round_: dict) -> dict:
    """A round with each variant's change in words."""
    from pipeline import thumbnail_variants as tv
    if round_.get("doc"):
        return {**round_, "variants": [{**v, "change_text": doc_change_text(v)} for v in round_["variants"]]}
    return {**round_, "variants": [{**v, "change_text": tv.describe_change(v.get("change"))}
                                   for v in round_["variants"]]}
