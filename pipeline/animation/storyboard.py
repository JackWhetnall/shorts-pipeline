"""
The storyboard: one call that directs the film.

It reads the whole narration with every word's real time, and the
stretches the visual director gave to animation, and writes the shots: a
visual concept and colour script for the whole video, every recurring
character, place and object with a description a model can hold on to,
and for each shot the word it cuts on, its framing, its first frame (for
the picture model), what moves and how the camera moves (for the video
model).

This is where a video stops being "an illustration per sentence", the
slideshow the sprite scenes of decisions 034-040 never escaped. The guide
asks for a film: one idea, motifs, a hook shot and a landing shot,
variety of scale, cuts on the turn of a thought, and shots written for
what today's models do well. The code then makes it safe whatever came
back (`settle`): cuts snap to spoken words inside the animated
stretches, too-short shots merge, too-long ones become a continued take,
and the whole is fitted to the budget.
"""

from __future__ import annotations

from core.logging_setup import get_logger
from pipeline.animation import models
from pipeline.llm import SystemBlock, call_json

log = get_logger(__name__)

FRAMINGS = ("extreme wide", "wide", "medium", "close-up", "extreme close-up")
KINDS = ("character", "place", "object")
# A cut lands this far ahead of the word it's on: the eye takes in a new
# picture a moment before the ear takes in the word.
LEAD = 0.1
MIN_SHOT = 1.6
MAX_TOKENS = 16000
EFFORT = "medium"

GUIDE = """
You are the director and storyboard artist of a short vertical animated film: a YouTube Short,
TikTok or Reel narrated by one voice. The narration is finished and timed. Your job is the
picture: a sequence of shots that an image model will draw (the first frame of each shot) and a
video model will animate. Make it genuinely good animation, the kind a viewer stops scrolling for
and a channel is proud of, not a slideshow illustrating each sentence.

THE IDEA
- Find one visual concept that carries the whole film: a world, a protagonist, a central
  metaphor or a journey. Every shot belongs to it. Two videos on the same subject should look
  like different films because their ideas differ.
- Show, don't caption. The picture adds what the words can't: the feeling, the scale, the
  consequence. Illustrating each noun as it is said is the weakest choice; find the image that
  makes the line land.
- Build and pay off motifs: an object, a colour, a gesture that returns and means more the
  second time.
- Plan a colour script: how light and colour move through the film with its emotional arc (cold
  to warm, night to dawn, one accent colour that grows).

THE SHOTS
- The first shot is the hook. It is on screen while the viewer decides whether to stay: the most
  arresting, instantly readable picture in the film, moving from its first frame. Never open on a
  slow establishing shot.
- The last shot lands: a resolved image that holds, echoing the idea.
- Vary scale and angle with purpose: wide to place us, medium for action, close-ups for emotion
  and detail. Rarely two consecutive shots with the same framing and subject. Cut on action;
  match shape, movement or colour across a cut when you can.
- Every shot has one clear piece of animation: a character acts (turns, reaches, looks up,
  walks, laughs), something transforms (a seed splits, light spreads, water rises), or the world
  moves (wind, rain, birds, clouds, embers), with a motivated camera move. Name the action
  specifically.
- Keep continuity: characters keep their clothes and their look, screen direction holds, and a
  place looks the same each time we return.

WHAT THE MODELS CAN AND CAN'T DO
Write shots the models will get right.
- Good: one or two characters doing one simple, clear action; expressive faces and body
  language; weather, water, fire, light, particles and foliage in motion; transformations of
  shape, light and colour; camera pushes, pulls, pans, tilts, orbits and cranes; silhouettes;
  symbolic and surreal imagery; vast landscapes; tiny details.
- Bad: any text, writing, signs, labels, numbers, legible clock faces, screens with content or
  maps with names (never ask for them); exact counts of many things; intricate hand work (tying
  knots, writing, playing an instrument); fights or fast complex choreography; crowds of detailed
  faces; many characters interacting; one character turning into another; anything that must be
  geometrically or factually exact. A precise diagram or statistic is not your job.
- Never depict a real living person. Historical figures may appear, respectfully, in the film's
  style. No gore, nothing sexual, nothing that mocks a faith.

WRITING EACH SHOT
- image: the first frame, literally, as a painter would need it: who and what is where in the
  frame, pose and expression, the setting, the light and time of day, the colour emphasis. Name
  recurring characters, places and objects by their element names. The frame is vertical 9:16:
  stack the composition vertically, the subject in the upper two thirds, the bottom third
  quieter (captions sit there). One to three sentences. No style words: the look is applied
  separately.
- motion: what happens during the shot, from that frame, in order: the action, the secondary
  motion, the camera move. One or two sentences with concrete verbs, possible in the shot's
  length.
- camera: the camera move alone, in a few words (slow push-in, track left, crane up, locked
  off, orbit right).
- elements: the keys of every recurring character, place and object visible in the first frame.
- continues: true only when the shot carries the previous shot's action on unbroken, as one long
  take drawn from its last frame (a journey, a transformation still unfolding). Its image then
  describes where the previous shot ends. Use it rarely; a cut is usually better.
- why: a few words on how this picture carries what is being said.

ELEMENTS
- List every character, place and object that appears in more than one shot, and any of the
  channel's cast you use, with a key (lowercase, underscores), a name and a precise visual
  description a model can hold on to. For a character: age, build, face, hair, skin, clothes
  with their colours and one distinctive feature. The description is used for every shot they
  are in, so make it specific and stable. An object is the object alone, never a person
  holding or wearing it; a place is the place alone. Anyone else who appears in a shot is
  described in that shot's image, distinct from the recurring characters, so they aren't
  drawn as one of them. Use the channel's cast when the film calls for them;
  don't force them into every video. For cast members, copy their description as given.

TIMING
- A shot starts on a spoken word: start_word is that word's index. Cut where the thought turns,
  usually at the start of a phrase or on a stressed word, so the picture changes with the
  meaning. Shots fall only inside stretches marked ANIMATE, and every ANIMATE stretch begins with
  a shot on its first word.
- Keep to the shot count and lengths you are given. List shots in the order they play.
""".strip()


def schema() -> dict:
    element = {"type": "object", "properties": {
        "key": {"type": "string"}, "kind": {"type": "string", "enum": list(KINDS)},
        "name": {"type": "string"}, "description": {"type": "string"}},
        "required": ["key", "kind", "name", "description"], "additionalProperties": False}
    shot = {"type": "object", "properties": {
        "start_word": {"type": "integer"},
        "framing": {"type": "string", "enum": list(FRAMINGS)},
        "image": {"type": "string"}, "motion": {"type": "string"},
        "camera": {"type": "string"},
        "elements": {"type": "array", "items": {"type": "string"}},
        "continues": {"type": "boolean"}, "why": {"type": "string"}},
        "required": ["start_word", "framing", "image", "motion", "camera", "elements",
                     "continues", "why"], "additionalProperties": False}
    return {"type": "object", "properties": {
        "concept": {"type": "string"}, "colour_script": {"type": "string"},
        "elements": {"type": "array", "items": element},
        "shots": {"type": "array", "items": shot}},
        "required": ["concept", "colour_script", "elements", "shots"],
        "additionalProperties": False}


def spans(segments: list, ranges: list, words: list) -> list:
    """For each animated range (first, last segment index): its start and
    end in narration seconds and the global indices of its words."""
    out = []
    for first, last in ranges:
        start, end = segments[first].start, segments[last].end
        indices = [i for i, w in enumerate(words) if start - 0.05 <= w.start < end]
        out.append({"first": first, "last": last, "start": start, "end": end,
                    "words": indices})
    return out


def shot_limits(seconds: float, pace: int, video: models.VideoModel, max_video_usd: float,
                quality: str) -> dict:
    """How many shots, how long: from the pace slider, bounded by what the
    video model can make and by the budget."""
    mean = models.mean_shot_seconds(pace)
    longest = video.durations[-1] * models.RETIME_MAX
    shortest = max(MIN_SHOT + 0.4, mean * 0.5)
    count = max(1, round(seconds / mean))
    # Every shot costs at least the model's shortest length.
    per_shot_floor = video.cost(video.durations[0], quality)
    # (1.2 // 0.4 is 2.0 in floating point.)
    affordable = int(max_video_usd / per_shot_floor + 1e-9) if per_shot_floor > 0 else count
    most = max(1, min(max(count + 2, round(count * 1.4)), affordable))
    least = max(1, min(most, int(seconds // longest) + 1, round(count * 0.7)))
    return {"mean": mean, "shortest": round(shortest, 1),
            "longest": round(min(longest, max(mean * 2.2, 6.0)), 1),
            "least": least, "most": most, "target": max(least, min(most, count))}


def _narration(segments: list, words: list, windows: list) -> str:
    animate = {i for w in windows for i in range(w["first"], w["last"] + 1)}
    lines = []
    for s_index, segment in enumerate(segments):
        idx = [i for i, w in enumerate(words) if segment.start - 0.05 <= w.start < segment.end]
        mark = "ANIMATE" if s_index in animate else "not animated"
        text = " ".join(f"{i}:{words[i].word}@{words[i].start:.1f}" for i in idx)
        lines.append(f"[segment {s_index}, {segment.start:.1f}-{segment.end:.1f}s, {mark}] {text}")
    return "\n".join(lines)


def write(segments: list, words: list, windows: list, *, subject: str, look: dict, cast: list,
          avoid: list, limits: dict, briefs: dict, hook_until: float = 0.0,
          previous: dict = None, problems: list = None) -> dict:
    """The raw storyboard from the model (see `settle` for the safe one)."""
    cast_lines = "\n".join(f"- {c['name']}: {c.get('description') or ''}" for c in cast) \
        or "(none: invent what the film needs)"
    brief_lines = "\n".join(f"- segment {i}: {b}" for i, b in sorted(briefs.items()) if b)
    user = [
        f"The video is about: {subject}",
        f"The channel's look: {look['label']}. {look['description']} Its camera: "
        f"{look['camera']}. How things move in it: {look['motion']}.",
        f"Energy: {look['energy']}/100 (0 calm, 100 lively).",
        f"The channel's recurring cast:\n{cast_lines}",
        f"Never show: {', '.join(avoid)}." if avoid else "",
        f"What the visual director had in mind for the animated segments:\n{brief_lines}"
        if brief_lines else "",
        f"Shots: between {limits['least']} and {limits['most']} in all (aim for about "
        f"{limits['target']}), each {limits['shortest']}-{limits['longest']} seconds, "
        f"averaging about {limits['mean']} seconds.",
        (f"For the first {hook_until:.1f} seconds a line of big text sits across the middle of "
         f"the first shot: give that shot a strong, simple silhouette the text can sit over."
         if hook_until > 0 else ""),
        "The narration, each word as index:word@seconds:\n" + _narration(segments, words, windows),
    ]
    if previous is not None:
        import json
        user.append("Your previous storyboard:\n" + json.dumps(previous)[:12000])
        user.append("Fix these problems and return the whole storyboard again:\n- " +
                    "\n- ".join(problems or []))
    return call_json([SystemBlock(GUIDE, cacheable=True)], "\n\n".join(p for p in user if p),
                     schema(), operation="animation_storyboard", max_tokens=MAX_TOKENS,
                     effort=EFFORT)


def _slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def settle(raw: dict, windows: list, words: list, video: models.VideoModel, quality: str,
           max_video_usd: float, cast: list) -> tuple:
    """(board, notes): the model's storyboard made safe to produce.

    - elements get clean keys; a cast member keeps the channel's own
      description whatever the model wrote;
    - every shot's cut snaps to a word inside an animated window, and each
      window opens with a shot on its first word;
    - shots too short to read merge into the one before, and shots longer
      than the model can make become a continued take;
    - the generated seconds are fitted to the budget by merging the
      shortest neighbours.
    """
    notes = []
    cast_by_key = {_slug(c["name"]): c for c in cast}
    elements = {}
    for e in raw.get("elements") or []:
        key = _slug(e.get("key") or e.get("name"))
        if not key or key in elements:
            continue
        member = cast_by_key.get(key) or next(
            (c for c in cast if _slug(c["name"]) == _slug(e.get("name"))), None)
        elements[key] = {
            "kind": e.get("kind") if e.get("kind") in KINDS else "character",
            "name": (member or e).get("name") or key,
            "description": (member.get("description") if member else e.get("description")) or "",
            "cast": member is not None}

    window_of = {}
    for w_index, window in enumerate(windows):
        for i in window["words"]:
            window_of[i] = w_index

    shots = []
    for s in raw.get("shots") or []:
        word = s.get("start_word")
        if not isinstance(word, int) or word not in window_of:
            notes.append(f"a shot cut on word {word}, outside the animation; dropped")
            continue
        shots.append(dict(s, start_word=word, window=window_of[word],
                          elements=[k for k in (_slug(x) for x in s.get("elements") or [])
                                    if k in elements],
                          framing=s.get("framing") if s.get("framing") in FRAMINGS else "medium"))
    shots.sort(key=lambda s: s["start_word"])
    unique = []
    for s in shots:
        if unique and unique[-1]["start_word"] == s["start_word"]:
            continue
        unique.append(s)
    shots = unique

    # Every window opens with a shot on its first word.
    for w_index, window in enumerate(windows):
        if not window["words"]:
            continue
        first_word = window["words"][0]
        mine = [s for s in shots if s["window"] == w_index]
        if not mine:
            shots.append({"start_word": first_word, "window": w_index, "framing": "wide",
                          "image": "", "motion": "", "camera": "slow push-in", "elements": [],
                          "continues": False, "why": "", "missing": True})
            notes.append(f"window {w_index + 1} had no shots")
        elif mine[0]["start_word"] != first_word:
            mine[0]["start_word"] = first_word
    shots.sort(key=lambda s: s["start_word"])

    _time(shots, windows, words)
    shots = _merge_short(shots, windows, words, MIN_SHOT)
    shots = _split_long(shots, video)
    _time(shots, windows, words)
    shots, fitted = _fit_budget(shots, windows, words, video, quality, max_video_usd)
    if fitted:
        notes.append(fitted)
    for i, s in enumerate(shots):
        s["index"] = i
        s["generate"] = video.seconds_for(s["duration"])
        if s.get("continues") and (i == 0 or shots[i - 1]["window"] != s["window"]):
            s["continues"] = False
    board = {"concept": raw.get("concept") or "", "colour_script": raw.get("colour_script") or "",
             "elements": elements, "shots": shots}
    return board, notes


def _time(shots: list, windows: list, words: list) -> None:
    """Each shot's start and end in narration seconds."""
    for i, s in enumerate(shots):
        window = windows[s["window"]]
        first_word = window["words"][0] if window["words"] else None
        if s.get("split_at"):
            start = s["split_at"]
        elif s["start_word"] == first_word:
            start = window["start"]
        else:
            start = max(window["start"], words[s["start_word"]].start - LEAD)
        s["start"] = round(start, 3)
    for i, s in enumerate(shots):
        nxt = shots[i + 1] if i + 1 < len(shots) else None
        end = nxt["start"] if nxt and nxt["window"] == s["window"] else windows[s["window"]]["end"]
        s["end"] = round(end, 3)
        s["duration"] = round(s["end"] - s["start"], 3)


def _merge_short(shots: list, windows: list, words: list, floor: float) -> list:
    """A shot shorter than `floor` gives its time to its neighbour in the
    same window (the one before, or after when it opens the window)."""
    changed = True
    while changed:
        changed = False
        _time(shots, windows, words)
        for i, s in enumerate(shots):
            if s["duration"] >= floor:
                continue
            same = [j for j in (i - 1, i + 1) if 0 <= j < len(shots)
                    and shots[j]["window"] == s["window"]]
            if not same:
                continue
            if i - 1 in same:
                del shots[i]                       # the one before runs on
            else:
                shots[i + 1]["start_word"] = s["start_word"]
                del shots[i]
            changed = True
            break
    return shots


def _split_long(shots: list, video: models.VideoModel) -> list:
    """A shot longer than the model can make becomes a long take: the
    rest is drawn on from its last frame."""
    longest = video.durations[-1] * models.RETIME_MAX
    out = []
    for s in shots:
        out.append(s)
        if s.get("duration", 0) <= longest:
            continue
        parts = int(s["duration"] // longest) + 1
        step = s["duration"] / parts
        for k in range(1, parts):
            # Same start word; its own start time (split_at), which _time keeps.
            out.append(dict(s, continues=True, split_at=round(s["start"] + k * step, 3),
                            image="The shot continues exactly where it left off.",
                            why="the same take, continued"))
    return out


def cost(shots: list, video: models.VideoModel, quality: str) -> float:
    return round(sum(video.cost(video.seconds_for(s["duration"]), quality) for s in shots), 4)


def _fit_budget(shots, windows, words, video, quality, max_usd) -> tuple:
    """Merge the shortest neighbouring pair until the video model's bill
    fits. Returns (shots, a note when anything had to give)."""
    merged = 0
    longest = video.durations[-1] * models.RETIME_MAX
    while cost(shots, video, quality) > max_usd + 1e-6:
        best, best_len = None, None
        for i in range(len(shots) - 1):
            a, b = shots[i], shots[i + 1]
            if a["window"] != b["window"] or b.get("split_at"):
                continue
            length = a["duration"] + b["duration"]
            if length <= longest and (best_len is None or length < best_len):
                best, best_len = i, length
        if best is None:
            break
        del shots[best + 1]
        merged += 1
        _time(shots, windows, words)
    note = f"{merged} cut(s) removed to stay within the budget" if merged else ""
    return shots, note
