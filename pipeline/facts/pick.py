"""
Facts for one quiz round.

A round at level L in a category draws from that category's facts whose
level (their rank in the category, pipeline.facts.levels) is near L and
that this channel has never asked, whichever category it asked them in.
A fact can be asked forwards ("The capital of France?") when the subject
has one value for it, and backwards ("Paris is the capital of which
country?") when the property allows it and no other subject shares the
value. The round gets one fact per subject and per answer, and a spread
of properties, so ten questions aren't ten capitals.
"""

from __future__ import annotations

import random
import re

from collections import Counter

from pipeline.facts import store
from pipeline.facts.levels import MIN_VIEWS, hardness, levels_for
from pipeline.facts.properties import PROPERTIES, phrase

WINDOWS = (0.75, 1.25, 2.0)       # how far from the level to look, widening
GIVEAWAY = 0.25                    # a value shared by this share of a property's facts...
GIVEAWAY_MIN = 12                  # ...among at least this many is a guess, not a question
SEQUENCES = {"P155", "P156"}
_QID = re.compile(r"^Q\d+$")
_NUMBERED = re.compile(r"\d")


def pool(conn, category: str, general: bool) -> list:
    """Every askable fact in a category, each with its level there.

    Not askable: a subject too few people read about; an answer that
    gives itself away because most of the category shares it (nearly
    every asteroid "orbits the Sun"); a sequence of numbered things
    ("19 Fortuna came after 18 Melpomene")."""
    rows = [dict(r) for r in store.category_facts(conn, None if general else category)]
    # (A property taken off the list since its facts were stored is out too.)
    rows = [r for r in rows if r["property"] in PROPERTIES
            and r["subject_label"] and not _QID.match(r["subject_label"])
            and (r["subject_views"] or 0) >= MIN_VIEWS
            and (r["value_sitelinks"] or 0) >= _known_answer(r["property"])
            and r["value_label"].lower() not in r["subject_label"].lower()
            and not _contains_name(r["value_label"], r["subject_label"])
            and not (r["property"] in SEQUENCES
                     and (_NUMBERED.search(r["subject_label"]) or _NUMBERED.search(r["value_label"])))]
    per_property = Counter(r["property"] for r in rows)
    per_value = Counter((r["property"], r["value"]) for r in rows)
    rows = [r for r in rows if not (per_property[r["property"]] >= GIVEAWAY_MIN
                                    and per_value[(r["property"], r["value"])]
                                    > GIVEAWAY * per_property[r["property"]])]
    for r in rows:
        r["hardness"] = hardness(r["property"], r["subject_views"], r["value_sitelinks"])
    reverse = [p for p, prop in PROPERTIES.items() if prop.reverse]
    counts = store.value_counts(conn, reverse)
    askable = []
    for r in rows:
        forward = r["values_for_subject"] == 1
        backward = counts.get((r["property"], r["value"])) == 1
        if forward or backward:
            r["ask"] = "either" if forward and backward else "forward" if forward else "backward"
            askable.append(r)
    for r, level in zip(askable, levels_for([r["hardness"] for r in askable])):
        r["level"] = level
    return askable


def _contains_name(answer: str, name: str) -> bool:
    """An answer that shares the thing asked about's name gives itself
    away: every word of it ("Fred Haise" was born "Fred Wallace Haise
    Jr."), or any long word ("Paranal Observatory" is on "Cerro
    Paranal")."""
    asked = set(re.findall(r"\w+", name.lower()))
    given = set(re.findall(r"\w+", answer.lower()))
    return bool(asked) and (asked <= given or any(len(w) >= 5 for w in asked & given))


def _known_answer(pid: str) -> int:
    prop = PROPERTIES.get(pid)
    return prop.known_answer if prop else 0


def for_round(conn, channel_key: str, category: str, level: float, count: int,
              exclude: set = frozenset(), seed=None) -> list:
    """Up to `count` unused facts for a round, spread across subjects,
    answers and properties. Fewer (possibly none) when the category is
    short at this level: the caller decides what to do then."""
    record = store.category(conn, category)
    if record is None:
        return []
    facts = pool(conn, record["name"], bool(record["spec"].get("general")))
    used = store.used_ids(conn, channel_key) | set(exclude)
    facts = [f for f in facts if f["id"] not in used]
    rng = random.Random(seed)
    for window in WINDOWS:
        near = [f for f in facts if abs(f["level"] - level) <= window]
        chosen = _spread(near, count, rng)
        if len(chosen) >= count:
            return chosen
    return _spread([f for f in facts if abs(f["level"] - level) <= WINDOWS[-1]], count, rng)


def _spread(facts: list, count: int, rng) -> list:
    """One fact per subject and per answer, always; a spread of properties
    first (a few of each), then topped up from any property, since some
    categories are mostly one kind of fact (books: who wrote them)."""
    facts = list(facts)
    rng.shuffle(facts)
    subjects, answers, properties, kinds, out = set(), set(), Counter(), Counter(), []
    for cap, kind_cap in ((max(2, count // 4), KIND_CAP), (count, KIND_CAP), (count, count)):
        for f in facts:
            if len(out) == count:
                return out
            answer = f["value_label"].lower()
            kind = kind_of(f.get("subject_description") or "")
            if (f["subject"] in subjects or answer in answers or f["subject_label"].lower() in answers
                    or properties[f["property"]] >= cap or kinds[kind] >= kind_cap):
                continue
            out.append(f)
            subjects.add(f["subject"])
            answers |= {answer, f["subject_label"].lower()}
            properties[f["property"]] += 1
            kinds[kind] += 1
    return out


KIND_CAP = 2            # facts about the same kind of thing in one round, while others remain


def kind_of(description: str) -> str:
    """What kind of thing a subject is, from its Wikidata description:
    "mountain in Greece" is a mountain, "island in the Aegean Sea" an
    island. A Fiendish Geography round was nearly all mountains and islands."""
    head = re.split(r"\s+(?:in|of|on|from|at|near|located)\s+|,|\(", description.lower())[0].strip()
    return head.split()[-1] if head else ""


def describe(fact: dict) -> str:
    """One fact as the writer sees it."""
    subject = fact["subject_label"] + (f" ({fact['subject_description']})" if fact["subject_description"] else "")
    value = fact["value_label"] + (f" ({fact['value_description']})" if fact.get("value_description") else "")
    how = {"forward": f"ask for {fact['value_label']}",
           "backward": f"ask for {fact['subject_label']}",
           "either": f"ask for either"}[fact["ask"]]
    return (f"F{fact['id']}: {phrase(fact['property'], fact['subject_label'], fact['value_label'])} "
            f"[{subject} | {PROPERTIES[fact['property']].label} | {value}] ({how})")


def answers_for(fact: dict) -> list:
    """The answers a question built on this fact may have."""
    out = []
    if fact["ask"] in ("forward", "either"):
        out.append(fact["value_label"])
    if fact["ask"] in ("backward", "either"):
        out.append(fact["subject_label"])
    return out
