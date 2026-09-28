"""
A quiz category, mapped onto Wikidata once.

"Geography" becomes the sets of things whose facts belong in it:
countries, capital cities, rivers, mountains, islands. "Harry Potter"
becomes everything tied to the series, its films and its fictional
universe. A model proposes the sets by name, with its best guess at each
item's Wikidata ID; every ID is then checked against Wikidata's own label
(and searched for by name when it doesn't match), and the result is stored (pipeline.facts.store) and
reused: defining a category is a one-off cost of about a cent. A set
that turns out to find nothing is skipped when first harvested.

A new category is tagged across the store at once: harvesting its sets
tags every member, including entities already there, whose facts then
count for it without being fetched again (pipeline.facts.harvest).
"""

from __future__ import annotations

from core.errors import PipelineError
from core.logging_setup import get_logger
from pipeline.facts import store, wikidata
from pipeline.facts.harvest import LINK_VIA
from pipeline.llm import call_json

log = get_logger(__name__)

GENERAL = {"general knowledge", "general", "mixed bag", "trivia", "anything goes", "potluck"}

SYSTEM = """
You map a pub-quiz category onto Wikidata, so that facts for its
questions can be gathered automatically. Say which sets of Wikidata items
the category's questions are about. Each set is one of:

- kind "class": instances of one or more classes (the class items, e.g.
  "country", "chemical element", "film", "painting"), optionally narrowed
  by one property's values: `where_property` a property ID and
  `where_values` its values. People are always the class "human"
  narrowed by occupation (P106), e.g. human with occupation "physicist".
- kind "linked": items tied to anchor items (a franchise, a series, a
  fictional universe, a big event) by "from narrative universe", "part of
  the series", "part of", "present in work" or "media franchise". Use
  this for franchises and fictional worlds; give every anchor they hang
  from (the series, its films, its universe).

For each item give its English Wikidata label exactly and your best guess
at its QID. `size`: "small" (only the best-known few hundred matter),
"medium" or "large" (thousands of members are fair game).

Cover the category broadly: every major kind of thing a quiz on it asks
about, usually 4 to 12 sets. Only things with settled facts: no current
office holders, team line-ups or records. Keep each set on topic: a
"Space" category wants planets, moons, stars, constellations, spacecraft
and astronauts, not every scientist. Set `general` true only for a
category that covers everything (general knowledge).
""".strip()

SCHEMA = {
    "type": "object",
    "properties": {
        "general": {"type": "boolean"},
        "sets": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["class", "linked"]},
                "name": {"type": "string"},
                "items": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"label": {"type": "string"}, "qid": {"type": "string"}},
                    "required": ["label", "qid"], "additionalProperties": False}},
                "where_property": {"type": "string"},
                "where_values": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"label": {"type": "string"}, "qid": {"type": "string"}},
                    "required": ["label", "qid"], "additionalProperties": False}},
                "size": {"type": "string", "enum": ["small", "medium", "large"]},
            },
            "required": ["kind", "name", "items", "where_property", "where_values", "size"],
            "additionalProperties": False}},
    },
    "required": ["general", "sets"],
    "additionalProperties": False,
}


class CategoryError(PipelineError):
    pass


def _same(a: str, b: str) -> bool:
    return " ".join((a or "").lower().split()) == " ".join((b or "").lower().split())


def resolve(items: list) -> list:
    """QIDs for [{label, qid}]: the guess where Wikidata's label agrees,
    otherwise the best search match for the label."""
    guesses = [i.get("qid", "").strip() for i in items if i.get("qid", "").strip().startswith("Q")]
    known = wikidata.labels(guesses) if guesses else {}
    out = []
    for item in items:
        label, guess = item.get("label", "").strip(), item.get("qid", "").strip()
        if guess in known and _same(known[guess][0], label):
            out.append(guess)
            continue
        found = wikidata.search(label) if label else []
        exact = [f["id"] for f in found if _same(f["label"], label)]
        if exact or found:
            out.append((exact or [found[0]["id"]])[0])
        else:
            log.warning(f"  [facts] couldn't find {label!r} on Wikidata")
    return list(dict.fromkeys(out))


def propose(name: str, note: str = "") -> dict:
    user = f"Category: {name}" + (f"\n\nWhat the channel means by it: {note}" if note else "")
    return call_json(SYSTEM, user, SCHEMA, operation="facts_category", max_tokens=4000, effort="low")


def define(conn, name: str, note: str = "") -> dict:
    """Map a category onto Wikidata and store it. Returns its spec."""
    if name.strip().lower() in GENERAL:
        spec = {"general": True, "sets": []}
        store.save_category(conn, name.strip(), spec)
        return spec
    proposal = propose(name, note)
    if proposal.get("general"):
        spec = {"general": True, "sets": []}
        store.save_category(conn, name.strip(), spec)
        return spec
    sets = []
    for raw in proposal.get("sets") or []:
        qids = resolve(raw.get("items") or [])
        if not qids:
            continue
        entity_set = {"name": raw.get("name", ""), "kind": raw.get("kind", "class"),
                      "size": raw.get("size", "medium")}
        if entity_set["kind"] == "linked":
            entity_set.update(anchors=qids, via=LINK_VIA)
        else:
            entity_set["classes"] = qids
            prop = (raw.get("where_property") or "").strip()
            values = resolve(raw.get("where_values") or []) if prop.startswith("P") else []
            if values:
                entity_set["where"] = {prop: values}
        # A set that finds nothing is found out, and skipped for good, the
        # first time it's harvested: checking here cost a minute a set on
        # the biggest classes.
        sets.append(entity_set)
    if not sets:
        raise CategoryError(f"no Wikidata sets for {name}", user_message=(
            f"Couldn't map \"{name}\" onto Wikidata. Its rounds will be written without facts."))
    spec = {"general": False, "sets": sets}
    store.save_category(conn, name.strip(), spec)
    log.info(f"  [facts] {name}: {len(sets)} sets: {', '.join(s['name'] for s in sets)}")
    return spec
