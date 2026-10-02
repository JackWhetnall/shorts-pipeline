"""
Pub-quiz websites: reading pages of questions and answers, politely.

- **robots.txt is obeyed**, including any crawl delay it asks for; a site
  that disallows us is skipped (Reddit does).
- **Slow:** at least 4 seconds between pages on one site.
- **Contained:** from each starting page, links are followed only within
  the same site and only to pages that look like quiz pages, up to
  MAX_PAGES a site.
- **What's kept:** what a page's questions and answers are, read out of
  it by Haiku, into the intake table with the page's address. It is
  never stored as the bank's wording: intake rewrites every question in
  our own words before it goes in (pipeline.facts.intake), so what's
  taken is the fact, not the site's text.

The starting pages are listed in `config/quiz_sources.txt`, one per line.
"""

from __future__ import annotations

import re
import time
import urllib.robotparser
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

from core.logging_setup import get_logger
from core.paths import PROJECT_ROOT

log = get_logger(__name__)

SOURCES_PATH = PROJECT_ROOT / "config" / "quiz_sources.txt"
USER_AGENT = "ShortsPipelineQuizImporter/1.0 (personal pub-quiz channel; one page every few seconds)"
MIN_DELAY = 4.0
MAX_PAGES = 60
QUIZ_WORDS = ("quiz", "question", "trivia", "answers")
TEXT_CHUNK = 9000             # characters of a page read in one go
DEFAULT_SOURCES = """# Pages of pub-quiz questions to read (pipeline.facts.sources.web), one per line.
# Lines starting with # are ignored. Sites whose robots.txt says no are skipped.
https://www.peacockquizzes.com/pub-quiz-questions-and-answers/
https://paulcooper.uk/2021/01/01/100-pub-quiz-trivia-questions-part-1/
https://nerdsip.com/pub-quiz/
https://pubquizquestionshq.com/
"""

EXTRACT_SYSTEM = """
You read a web page of quiz questions and list every question it gives
with its answer, as given. Skip anything that isn't a question with a
stated answer: menus, adverts, comments, picture rounds, multiple-choice
options without a stated answer. Keep each question's meaning and answer
exactly; tidy only its spelling and spacing.
""".strip()

EXTRACT_SCHEMA = {"type": "object", "properties": {"questions": {"type": "array", "items": {
    "type": "object", "properties": {"question": {"type": "string"}, "answer": {"type": "string"}},
    "required": ["question", "answer"], "additionalProperties": False}}},
    "required": ["questions"], "additionalProperties": False}


def starting_pages() -> list:
    if not SOURCES_PATH.exists():
        SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)
        SOURCES_PATH.write_text(DEFAULT_SOURCES, encoding="utf-8")
    return [line.strip() for line in SOURCES_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")]


class _Text(HTMLParser):
    """A page's readable text and its links, skipping scripts, styles and
    the page's furniture."""
    SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg"}

    def __init__(self):
        super().__init__()
        self.parts, self.links, self._skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in ("p", "li", "br", "h1", "h2", "h3", "h4", "div", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", "".join(self.parts))).strip()


class _Site:
    """robots.txt and the pace for one site."""

    def __init__(self, root: str):
        self.root = root
        self.robots = urllib.robotparser.RobotFileParser()
        try:
            response = requests.get(root + "/robots.txt", timeout=20, headers={"User-Agent": USER_AGENT})
            self.robots.parse(response.text.splitlines() if response.status_code == 200 else [])
        except requests.RequestException:
            self.robots.parse([])
        self.delay = max(MIN_DELAY, float(self.robots.crawl_delay(USER_AGENT) or 0))
        self.last = 0.0

    def allowed(self, url: str) -> bool:
        return self.robots.can_fetch(USER_AGENT, url)

    def get(self, url: str, sleep=time.sleep) -> str:
        wait = self.last + self.delay - time.time()
        if wait > 0:
            sleep(wait)
        self.last = time.time()
        response = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.text


def _quizzy(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(word in path for word in QUIZ_WORDS)


def crawl(start_urls: list, seen: set, say=None, sleep=time.sleep, max_pages: int = MAX_PAGES):
    """Yield (url, readable text) for each page read, starting pages first,
    then quiz-looking pages they link to on the same site. `seen` holds
    pages already read on an earlier run; they're not read again."""
    sites = {}
    for start in start_urls:
        parts = urlparse(start)
        root = f"{parts.scheme}://{parts.netloc}"
        site = sites.setdefault(root, _Site(root))
        if not site.allowed(start):
            log.info(f"  [web] {root}: its robots.txt doesn't allow us; skipped")
            if say:
                say(f"{parts.netloc}: its robots.txt says no, so it's skipped")
            continue
        queue, read = [start.split("#")[0]], 0
        while queue and read < max_pages:
            url = queue.pop(0)
            if url in seen or not site.allowed(url):
                continue
            seen.add(url)
            try:
                page = site.get(url, sleep)
            except requests.RequestException as exc:
                log.info(f"  [web] couldn't read {url} ({exc})")
                continue
            read += 1
            parsed = _Text()
            parsed.feed(page)
            for href in parsed.links:
                link = urljoin(url, href).split("#")[0].split("?")[0]
                if urlparse(link).netloc == parts.netloc and _quizzy(link) and link not in seen \
                        and link not in queue:
                    queue.append(link)
            if say:
                say(f"read {url}")
            yield url, parsed.text()


def extract(text: str) -> list:
    """The questions and answers a page's text gives, as on the page (Haiku,
    about half a cent per 9,000 characters). Rewritten later, never kept
    as they are."""
    from pipeline.llm import call_json
    out = []
    for start in range(0, len(text), TEXT_CHUNK):
        piece = text[start:start + TEXT_CHUNK]
        if not re.search(r"\?", piece):
            continue
        data = call_json(EXTRACT_SYSTEM, piece, EXTRACT_SCHEMA, operation="intake_extract",
                         model="claude-haiku-4-5", max_tokens=8000, effort=None)
        out += [q for q in data.get("questions") or [] if q.get("question") and q.get("answer")]
    return out
