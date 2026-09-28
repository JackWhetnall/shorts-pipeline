"""
Talking to Wikidata: SPARQL for facts, and Wikidata's API for finding an
item by name.

Queries go to Wikidata's own query service. It has no index by fame, so
ranking a class of hundreds of thousands (films, mountains, stars) by it
times out at 60 seconds, and timeouts spend the rate allowance. For that
one job, `sparql(..., engine="qlever")` asks QLever (University of
Freiburg), a public engine over the Wikidata dump that sorts every human
by fame in seconds. It has quirks: it answers nothing at all to a joined
subclass path (P31/P279*) or to a filter on fame, so its query is written
around both, and under load it was seen answering with empty or unsorted
results, so the harvester checks what it gets back (pipeline.facts.harvest)
and uses nothing else from it.

Wikidata is CC0, so nothing taken from it needs crediting. Requests go
one at a time with a pause between, name themselves (User-Agent), and
back off on 429 and 5xx; a query that times out is reported so the caller
can ask for less.
"""

from __future__ import annotations

import time

import requests

from core.errors import ExternalServiceError
from core.logging_setup import get_logger

log = get_logger(__name__)

SPARQL_URL = "https://query.wikidata.org/sparql"
QLEVER_URL = "https://qlever.cs.uni-freiburg.de/api/wikidata"
PREFIXES = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX schema: <http://schema.org/>
"""
API_URL = "https://www.wikidata.org/w/api.php"
USER_AGENT = ("ShortsPipelineQuizFacts/1.0 (https://github.com/JackWhetnall/shorts-pipeline; "
              "a personal quiz-video tool)")
PAUSE = 1.0                 # between requests: well inside both services' limits
TIMEOUT = 70
ATTEMPTS = 4

_last = 0.0


class QueryTimeout(ExternalServiceError):
    """The query service gave up on a query: ask for less."""


def _wait():
    global _last
    gap = time.time() - _last
    if gap < PAUSE:
        time.sleep(PAUSE - gap)
    _last = time.time()


def _get(url: str, params: dict) -> dict:
    # QLever is only ever a faster second opinion: when it refuses, the
    # caller moves on rather than waiting for it.
    attempts = 1 if url == QLEVER_URL else ATTEMPTS
    for attempt in range(attempts):
        _wait()
        try:
            accept = "application/sparql-results+json" if url in (SPARQL_URL, QLEVER_URL) else "application/json"
            response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT,
                                                                 "Accept": accept},
                                    timeout=TIMEOUT)
        except requests.Timeout:
            if url in (SPARQL_URL, QLEVER_URL):
                raise QueryTimeout("Wikidata", "the query took too long",
                                   user_message="A Wikidata query took too long.")
            response = None
        except requests.RequestException as exc:
            log.warning(f"  [facts] Wikidata request failed ({exc}); retrying")
            response = None
        if response is not None:
            if response.status_code == 200:
                return response.json()
            # The query service reports its own timeout as a 500 whose
            # body names the Java exception, or its gateway gives up (504).
            if url in (SPARQL_URL, QLEVER_URL) and (response.status_code == 504
                                      or "TimeoutException" in response.text[:3000]):
                raise QueryTimeout("Wikidata", "the query took too long",
                                   user_message="A Wikidata query took too long.")
            if response.status_code not in (429, 500, 502, 503, 504):
                raise ExternalServiceError("Wikidata", f"HTTP {response.status_code}",
                                           user_message="Wikidata refused a request.")
            if attempts == 1:
                break
            wait = float(response.headers.get("Retry-After") or 0) or 5 * (attempt + 1)
            log.warning(f"  [facts] Wikidata said {response.status_code}; waiting {wait:.0f}s")
            time.sleep(min(wait, 120))
        elif attempts > 1:
            time.sleep(5 * (attempt + 1))
    raise ExternalServiceError("Wikidata", "no answer after retries",
                               user_message="Wikidata didn't answer; try again later.")


def sparql(query: str, engine: str = "wikidata") -> list:
    """The query's result rows, each {variable: value as a string}, with
    "<var>_type", "<var>_datatype" and "<var>_lang" beside a value that
    has them. QLever gets the usual prefixes added; Wikidata knows them."""
    if engine == "qlever":
        data = _get(QLEVER_URL, {"query": PREFIXES + query})
    else:
        data = _get(SPARQL_URL, {"query": query, "format": "json"})
    rows = []
    for binding in data.get("results", {}).get("bindings", []):
        row = {}
        for name, cell in binding.items():
            row[name] = cell.get("value", "")
            row[f"{name}_type"] = cell.get("type", "")
            if cell.get("datatype"):
                row[f"{name}_datatype"] = cell["datatype"]
            if cell.get("xml:lang"):
                row[f"{name}_lang"] = cell["xml:lang"]
        rows.append(row)
    return rows


def qid(uri: str) -> str:
    """"Q42" from "http://www.wikidata.org/entity/Q42"; "" for anything else
    (a blank node standing for "unknown value", a literal)."""
    tail = (uri or "").rsplit("/", 1)[-1]
    return tail if tail[:1] in ("Q", "P") and tail[1:].isdigit() else ""


def search(name: str, limit: int = 7) -> list:
    """[{id, label, description}] for items whose name matches, best first."""
    data = _get(API_URL, {"action": "wbsearchentities", "search": name, "language": "en",
                          "uselang": "en", "type": "item", "limit": limit, "format": "json"})
    return [{"id": r.get("id", ""), "label": r.get("label", ""), "description": r.get("description", "")}
            for r in data.get("search", [])]


VIEWS_URL = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia.org/"
             "all-access/user/{title}/monthly/{start}/{end}")


def enwiki_titles(qids: list) -> dict:
    """{qid: its English Wikipedia article's title} for those that have one."""
    out = {}
    for start in range(0, len(qids), 50):
        chunk = [q for q in qids[start:start + 50] if q]
        if not chunk:
            continue
        data = _get(API_URL, {"action": "wbgetentities", "ids": "|".join(chunk), "props": "sitelinks",
                              "sitefilter": "enwiki", "format": "json"})
        for q, entity in (data.get("entities") or {}).items():
            title = ((entity.get("sitelinks") or {}).get("enwiki") or {}).get("title")
            if title:
                out[q] = title
    return out


def yearly_views(titles: dict, workers: int = 6) -> dict:
    """{qid: English Wikipedia views by people (not bots) over the last
    twelve full months}, for {qid: title}. An article with no record reads
    as 0. Wikimedia's API takes many requests a second; these go six at a
    time."""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import date

    today = date.today()
    end = date(today.year, today.month, 1)
    start = date(end.year - 1, end.month, 1)
    span = {"start": start.strftime("%Y%m%d00"), "end": end.strftime("%Y%m%d00")}

    def one(item):
        qid, title = item
        url = VIEWS_URL.format(title=requests.utils.quote(title.replace(" ", "_"), safe=""), **span)
        for attempt in range(3):
            try:
                response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            except requests.RequestException:
                time.sleep(2 * (attempt + 1))
                continue
            if response.status_code == 200:
                return qid, sum(i.get("views", 0) for i in response.json().get("items", []))
            if response.status_code == 404:
                return qid, 0
            time.sleep(2 * (attempt + 1))
        return qid, None                      # unknown: measured again next time

    with ThreadPoolExecutor(workers) as pool:
        return {q: v for q, v in pool.map(one, titles.items()) if v is not None}


def labels(qids: list) -> dict:
    """{qid: (label, description)} in English, for up to 50 at a time."""
    out = {}
    for start in range(0, len(qids), 50):
        chunk = [q for q in qids[start:start + 50] if q]
        if not chunk:
            continue
        data = _get(API_URL, {"action": "wbgetentities", "ids": "|".join(chunk),
                              "props": "labels|descriptions", "languages": "en", "format": "json"})
        for q, entity in (data.get("entities") or {}).items():
            out[q] = ((entity.get("labels", {}).get("en") or {}).get("value", ""),
                      (entity.get("descriptions", {}).get("en") or {}).get("value", ""))
    return out
