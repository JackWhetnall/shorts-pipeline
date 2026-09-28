"""
How hard a fact is, measured rather than guessed.

Fame is how many Wikipedias have an article on a thing (Wikidata's
"sitelinks"): France has over 400, a mid-table footballer 15. A question
asks the player to get from what it names to its answer, so a fact is as
well known as the less famous of the two, pulled a little towards the
more famous. Its `hardness` is that fame in doublings of obscurity below
a thousand Wikipedias, plus the property's own adjustment (a capital is
easier than its country's fame suggests; a discoverer harder).

Hardness is absolute. Levels are relative to a category: within
"Harry Potter", Easy is what every fan knows, not what everyone knows.
So a category's facts are ranked by hardness and spread over the 1-10
scale by rank (`levels_for`), and a round at a level draws from facts
near it. General knowledge ranks every fact at once.
"""

from __future__ import annotations

import math

from pipeline.facts.properties import PROPERTIES

TOP = 1000


def hardness(pid: str, subject_sitelinks: int, value_sitelinks: int = None) -> float:
    s = max(1, subject_sitelinks or 1)
    if value_sitelinks:
        low, high = sorted((s, max(1, value_sitelinks)))
        fame = math.exp(0.65 * math.log(low) + 0.35 * math.log(high))
    else:
        fame = s
    prop = PROPERTIES.get(pid)
    return round(math.log2(TOP / fame) + (prop.adjust if prop else 0.0), 3)


def levels_for(hardnesses: list) -> list:
    """Each hardness's level (1-10) by its rank among these."""
    n = len(hardnesses)
    if n == 0:
        return []
    if n == 1:
        return [5.5]
    order = sorted(range(n), key=lambda i: hardnesses[i])
    out = [0.0] * n
    for rank, i in enumerate(order):
        out[i] = round(1 + 9 * rank / (n - 1), 2)
    return out
