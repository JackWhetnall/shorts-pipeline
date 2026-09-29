"""
How hard a fact is, measured rather than guessed.

Fame is how often people read about a thing: its English Wikipedia
article's views over the last year (Earth 3.5 million, Mars 1.3 million,
a numbered asteroid a few thousand). The number of Wikipedias covering it
was tried first and misled: bots have written asteroids into dozens of
them, so "221 Eos orbits the Sun" came out as easy as anything.

A question names one thing and asks for another, and both matter: the
thing named has to be recognised, and the answer recalled (its fame is
how many Wikipedias cover it, which is fine for answers). Weighting the
thing named alone rated "Who discovered Proxima Centauri?" (Robert
Innes) as easy as anything. `hardness` is
that, in doublings of obscurity, plus the property's own adjustment (a
capital is easier than its country's fame suggests; a discoverer harder).
Anything read fewer than MIN_VIEWS times a year is too obscure to ask
about at all.

Hardness is absolute. Levels are relative to a category: within
"Harry Potter", Easy is what every fan knows, not what everyone knows.
So a category's facts are ranked by hardness and spread over the 1-10
scale by rank (`levels_for`), and a round at a level draws from facts
near it. General knowledge ranks every fact at once.
"""

from __future__ import annotations

import math

from pipeline.facts.properties import PROPERTIES

TOP_VIEWS = 5_000_000          # a year's views of about the best-known things
TOP_SITELINKS = 400
MIN_VIEWS = 15_000             # about 40 readers a day: below this, too obscure to ask


def hardness(pid: str, subject_views: int, value_sitelinks: int = None) -> float:
    named = math.log2(TOP_VIEWS / max(1, subject_views or 1))
    answer = math.log2(TOP_SITELINKS / max(1, value_sitelinks)) if value_sitelinks else named
    prop = PROPERTIES.get(pid)
    return round(0.55 * named + 0.45 * answer + (prop.adjust if prop else 0.0), 3)


# Only the best-known share of a category's facts is spread over the
# 1-10 scale; the rest sit at 10 and are almost never asked. Spread over
# all of them, Fiendish Geography meant "the highest peak of Euboea".
FAMOUS_SHARE = 0.4


def levels_for(hardnesses: list, share: float = FAMOUS_SHARE) -> list:
    """Each hardness's level (1-10) by its rank among these, the easiest
    `share` of them spread over the scale."""
    n = len(hardnesses)
    if n == 0:
        return []
    if n == 1:
        return [5.5]
    order = sorted(range(n), key=lambda i: hardnesses[i])
    out = [0.0] * n
    for rank, i in enumerate(order):
        out[i] = round(1 + 9 * min(1.0, rank / ((n - 1) * share)), 2)
    return out
