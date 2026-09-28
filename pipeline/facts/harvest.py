"""
Filling the fact store from Wikidata, a category at a time.

A category is a list of entity sets (pipeline.facts.categories):

- {"kind": "class", "classes": [...], "where": {property: [values]}}:
  instances of these classes (countries; humans whose occupation is
  physicist), most famous first;
- {"kind": "linked", "anchors": [...], "via": [...]}: items tied to these
  (everything from the Harry Potter universe, in the series, part of it).

Harvesting a set takes its next page of members, most famous first, so
each harvest goes a little deeper and the store keeps growing as it's
eaten. Every member is tagged with the category (an entity already in
the store is tagged without being fetched again), then the facts of the
members not yet pulled are fetched, a chunk at a time, for every
property in pipeline.facts.properties.

Nothing here is written for a particular script: facts are statements,
and a round is written from them later (pipeline.quiz).
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from core.logging_setup import get_logger
from pipeline.facts import levels, store, wikidata
from pipeline.facts.properties import ITEM_PROPERTIES, PROPERTIES, YEAR_PROPERTIES

log = get_logger(__name__)

LINK_VIA = ["P1080", "P179", "P361", "P1441", "P8345"]
DEFAULT_PAGE = {"small": 300, "medium": 1200, "large": 3000}
MIN_SITELINKS = {"class": 8, "linked": 1}
CHUNK = 120                     # entities per facts query
RETRY_SKIPPED = 7 * 86400       # seconds before a skipped set is tried again
_QID = re.compile(r"^Q\d+$")


def _values(qids) -> str:
    return " ".join(f"wd:{q}" for q in qids)


# How a class set's members are found, tried in order until one works;
# the one that did is kept in the set's spec for its next pages.
# "ranked": instances of the class and all its subclasses, ranked on
# QLever, which is fast when it's well and checked either way;
# "one level": the class and its direct subclasses (the Moon is a
# "regular moon", a kind of natural satellite), on Wikidata, which times
# out on the biggest classes; "direct": instances only, at four times
# the fame floor.
METHODS = ("ranked", "one level", "direct")


def members_query(spec: dict, offset: int, limit: int, method: str = "one level") -> str:
    kind = spec.get("kind")
    floor = int(spec.get("min_sitelinks", MIN_SITELINKS.get(kind, 8)))
    if kind == "linked":
        via = " ".join(f"wdt:{p}" for p in spec.get("via") or LINK_VIA)
        where = (f"VALUES ?a {{ {_values(spec['anchors'])} }} VALUES ?p {{ {via} }} ?s ?p ?a .")
    else:
        if method == "ranked":
            # Two steps: QLever answers the joined path P31/P279* with
            # nothing at all.
            where = (f"VALUES ?root {{ {_values(spec['classes'])} }} "
                     f"?s wdt:P31 ?c . ?c wdt:P279* ?root .")
        else:
            path = "wdt:P31/wdt:P279?" if method == "one level" else "wdt:P31"
            where = f"VALUES ?c {{ {_values(spec['classes'])} }} ?s {path} ?c ."
        if method == "direct":
            floor *= 4
        for prop, values in (spec.get("where") or {}).items():
            where += f" ?s wdt:{prop} ?w_{prop} . VALUES ?w_{prop} {{ {_values(values)} }}"
    # QLever answers nothing at all with the fame filter in (it's applied
    # to its rows afterwards, in `members`); the sort does the same job.
    fame = "" if method == "ranked" else f"FILTER(?sl >= {floor}) "
    inner = (f"{{ SELECT DISTINCT ?s ?sl WHERE {{ {where} ?s wikibase:sitelinks ?sl . "
             f"{fame}}} ORDER BY DESC(?sl) OFFSET {offset} LIMIT {limit} }}")
    if method == "ranked":
        return f"""SELECT ?s ?sLabel ?sDescription ?sl WHERE {{ {inner}
  ?s rdfs:label ?sLabel . FILTER(LANG(?sLabel) = "en")
  OPTIONAL {{ ?s schema:description ?sDescription . FILTER(LANG(?sDescription) = "en") }}
}} ORDER BY DESC(?sl)"""
    return f"""SELECT ?s ?sLabel ?sDescription ?sl WHERE {{ {inner}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} ORDER BY DESC(?sl)"""


def _sane(rows: list, offset: int) -> bool:
    """QLever's answer is used only if it looks right: fame in descending
    order, and on a first page genuinely famous things at the top (it was
    seen returning films in ten Wikipedias first)."""
    fame = [int(float(r.get("sl") or 0)) for r in rows]
    if not fame or any(a < b for a, b in zip(fame, fame[1:])):
        return False
    return offset > 0 or fame[0] >= 30


def members(spec: dict, offset: int, limit: int) -> list:
    """[(qid, label, description, sitelinks)] for a page of the set, most
    famous first. A class set tries each of METHODS from the one that
    last worked; `spec["method"]` records it, or "skipped" when none did,
    so a class too big for any isn't tried at every harvest. A skip is
    tried again after RETRY_SKIPPED: a bad hour on both services isn't a
    verdict on the set."""
    rows = None
    if spec.get("kind") == "linked":
        try:
            rows = wikidata.sparql(members_query(spec, offset, limit))
        except wikidata.QueryTimeout:
            log.warning(f"  [facts] {spec.get('name')}: too many linked items to rank; skipped")
            return []
    else:
        if spec.get("method") == "skipped":
            if time.time() - float(spec.get("skipped_at") or 0) < RETRY_SKIPPED:
                return []
            spec.pop("method")
        start = METHODS.index(spec["method"]) if spec.get("method") in METHODS else 0
        for method in METHODS[start:]:
            engine = "qlever" if method == "ranked" else "wikidata"
            try:
                found = wikidata.sparql(members_query(spec, offset, limit, method), engine=engine)
            except wikidata.QueryTimeout:
                log.info(f"  [facts] {spec.get('name')}: too many to rank that way ({method})")
                continue
            except Exception as exc:  # noqa: BLE001 - QLever is a fallback; its failure is one more try
                if engine != "qlever":
                    raise
                log.info(f"  [facts] {spec.get('name')}: QLever didn't help ({exc})")
                continue
            if engine == "qlever":
                if not _sane(found, offset):
                    log.info(f"  [facts] {spec.get('name')}: QLever's answer didn't look right; not used")
                    continue
                floor = int(spec.get("min_sitelinks", MIN_SITELINKS["class"]))
                found = [r for r in found if int(float(r.get("sl") or 0)) >= floor]
            spec["method"], rows = method, found
            break
        if rows is None:
            spec["method"], spec["skipped_at"] = "skipped", time.time()
            log.warning(f"  [facts] {spec.get('name')}: couldn't rank it any way; skipped")
            return []
    out = []
    for r in rows:
        q = wikidata.qid(r.get("s", ""))
        label = r.get("sLabel", "")
        if q and label and not _QID.match(label):
            out.append((q, label, r.get("sDescription", ""), int(float(r.get("sl") or 0))))
    return out


def items_query(qids: list) -> str:
    props = " ".join(f"wdt:{p}" for p in ITEM_PROPERTIES)
    return f"""
SELECT ?s ?p ?o ?oLabel ?oDescription ?osl WHERE {{
  VALUES ?s {{ {_values(qids)} }}
  VALUES ?p {{ {props} }}
  ?s ?p ?o .
  FILTER(!isLiteral(?o) || LANG(?o) = "" || LANG(?o) = "en")
  OPTIONAL {{ ?o wikibase:sitelinks ?osl }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}"""


def years_query(qids: list) -> str:
    props = " ".join(f"wd:{p}" for p in YEAR_PROPERTIES)
    return f"""
SELECT ?s ?prop ?t ?prec WHERE {{
  VALUES ?s {{ {_values(qids)} }}
  VALUES ?prop {{ {props} }}
  ?prop wikibase:claim ?claim ; wikibase:statementValue ?psv .
  ?s ?claim ?st . ?st wikibase:rank ?rank . FILTER(?rank != wikibase:DeprecatedRank)
  ?st ?psv ?v . ?v wikibase:timeValue ?t ; wikibase:timePrecision ?prec .
}}"""


def _year(timestamp: str) -> str:
    match = re.match(r"^([+-]?)(\d+)-", timestamp or "")
    if not match:
        return ""
    year = int(match.group(2))
    if year == 0:
        return ""
    return f"{year} BC" if match.group(1) == "-" else str(year)


def _number(text: str) -> str:
    try:
        value = float(text)
    except ValueError:
        return ""
    return str(int(value)) if value.is_integer() else f"{value:g}"


def parse_items(rows: list) -> list:
    """Fact rows (subject, property, value, label, description,
    sitelinks, kind) from an items query, unusable ones dropped: unknown
    values, values with no English label."""
    out = []
    for r in rows:
        subject, pid = wikidata.qid(r.get("s", "")), wikidata.qid(r.get("p", ""))
        prop = PROPERTIES.get(pid)
        if not subject or prop is None:
            continue
        if r.get("o_type") == "uri":
            value = wikidata.qid(r.get("o", ""))
            label = r.get("oLabel", "")
            if not value or not label or _QID.match(label):
                continue
            out.append((subject, pid, value, label, r.get("oDescription", ""),
                        int(float(r["osl"])) if r.get("osl") else None, "item"))
        else:
            raw = r.get("o", "").strip()
            value = _number(raw) if prop.kind == "number" else raw
            if not value or len(value) > 60:
                continue
            out.append((subject, pid, value, value, "", None, prop.kind))
    return out


def parse_years(rows: list) -> list:
    """Year facts, only those stated to the year or better: "900" meant
    as a century isn't a quiz answer."""
    out = []
    for r in rows:
        subject, pid = wikidata.qid(r.get("s", "")), wikidata.qid(r.get("prop", ""))
        if not subject or pid not in PROPERTIES or int(float(r.get("prec") or 0)) < 9:
            continue
        year = _year(r.get("t", ""))
        if year:
            out.append((subject, pid, year, year, "", None, "year"))
    return out


def facts_for(conn, qids: list) -> int:
    """Pull and store the facts of these entities. Returns how many new."""
    added = 0
    for start in range(0, len(qids), CHUNK):
        chunk = qids[start:start + CHUNK]
        rows = []
        for build, parse in ((items_query, parse_items), (years_query, parse_years)):
            parts = [chunk]
            while parts:
                part = parts.pop()
                try:
                    rows += parse(wikidata.sparql(build(part)))
                except wikidata.QueryTimeout:
                    if len(part) <= 10:
                        log.warning(f"  [facts] a facts query for {len(part)} entities timed out; skipped")
                        continue
                    half = len(part) // 2
                    parts += [part[:half], part[half:]]
        added += store.replace_facts(conn, chunk, _as_facts(rows))
    return added


def _as_facts(rows: list) -> list:
    by_pair = defaultdict(set)
    for subject, pid, value, *_ in rows:
        by_pair[(subject, pid)].add(value)
    seen, out = set(), []
    for subject, pid, value, label, description, value_fame, kind in rows:
        if (subject, pid, value) in seen:
            continue
        seen.add((subject, pid, value))
        out.append({"subject": subject, "property": pid, "value": value, "value_label": label,
                    "value_description": description or "", "value_sitelinks": value_fame,
                    "kind": kind, "values_for_subject": len(by_pair[(subject, pid)]),
                    "hardness": 0.0})
    return out


def harvest(conn, name: str, grow: bool = False, progress=None) -> dict:
    """Fill a category: the next page of each of its sets (the first page,
    unless `grow`), tagging every member, then fetching the facts of
    members not yet pulled. Returns {"members", "fetched", "new_facts"}."""
    say = progress or (lambda message: log.info(f"  [facts] {message}"))
    record = store.category(conn, name)
    if record is None:
        raise KeyError(name)
    spec = record["spec"]
    if spec.get("general"):
        return {"members": 0, "fetched": 0, "new_facts": 0}
    tagged = 0
    for entity_set in spec.get("sets", []):
        page = int(entity_set.get("page") or DEFAULT_PAGE.get(entity_set.get("size"), 1200))
        done = int(entity_set.get("fetched") or 0)
        if done and not grow:
            continue
        say(f"{name}: finding {entity_set.get('name', 'members')} ({done + 1}-{done + page})")
        rows = members(entity_set, done, page)
        if not rows and not done and entity_set.get("method") != "skipped":
            # Mapped onto something with no famous members: not for a while.
            entity_set["method"], entity_set["skipped_at"] = "skipped", time.time()
            say(f"{name}: {entity_set.get('name')} finds nothing on Wikidata; skipped")
        store.upsert_entities(conn, rows)
        store.add_members(conn, record["name"], [r[0] for r in rows])
        entity_set["fetched"] = done + len(rows)
        tagged += len(rows)
    store.save_category(conn, record["name"], spec)
    everyone = [r["qid"] for r in conn.execute("SELECT qid FROM members WHERE category = ?",
                                               (record["name"],))]
    measure(conn, everyone, say)
    # Facts only for members people actually read about.
    todo = [q for q in store.unharvested(conn, everyone)
            if (conn.execute("SELECT views FROM entities WHERE qid = ?", (q,)).fetchone()[0] or 0)
            >= levels.MIN_VIEWS]
    added = 0
    for start in range(0, len(todo), CHUNK * 5):
        say(f"{name}: fetching facts, {start + 1}-{min(len(todo), start + CHUNK * 5)} of {len(todo)} entities")
        added += facts_for(conn, todo[start:start + CHUNK * 5])
    store.mark_harvested(conn, record["name"], record["depth"] + (1 if grow else 0))
    say(f"{name}: {tagged} members tagged, {len(todo)} fetched, {added} new facts")
    return {"members": tagged, "fetched": len(todo), "new_facts": added}


def measure(conn, qids: list, say=None) -> None:
    """Views for entities not measured yet (pipeline.facts.levels)."""
    todo = store.unmeasured(conn, qids)
    for start in range(0, len(todo), 500):
        chunk = todo[start:start + 500]
        if say:
            say(f"measuring how often people read about {start + 1}-{start + len(chunk)} of {len(todo)}")
        titles = wikidata.enwiki_titles(chunk)
        store.save_views(conn, titles, wikidata.yearly_views(titles), chunk)


def refresh(conn, days: int = 180, limit: int = 3000, progress=None) -> int:
    """Pull again the facts of entities last pulled over `days` ago, so
    what's asked stays what Wikidata says now. Returns entities refreshed."""
    before = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    stale = [r[0] for r in conn.execute(
        "SELECT qid FROM entities WHERE harvested_at IS NOT NULL AND harvested_at < ? "
        "ORDER BY harvested_at LIMIT ?", (before, limit))]
    if stale:
        (progress or log.info)(f"refreshing {len(stale)} entities")
        facts_for(conn, stale)
    return len(stale)
