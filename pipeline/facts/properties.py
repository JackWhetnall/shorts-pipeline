"""
Which Wikidata properties make quiz facts, and how.

Only properties whose values are stable and checkable belong here: a
capital, an author, a discoverer, a chemical symbol. Anything that
changes with time (heads of state, populations, team rosters, record
holders) is left out, because a fact store is eaten through over months
and a question must still be right on the day it's published.

Each property says:

- `phrase`: how the fact reads, "{s}" the subject and "{o}" the value,
  for the writer and for people reading the store;
- `kind`: "item" (another Wikidata item), "string", "number" or "year";
- `adjust`: how much harder than its subjects' fame alone suggests, in
  the same units as pipeline.facts.levels (doublings of obscurity). A
  country's capital is easier than the country's fame; who discovered an
  element is harder than the element's;
- `reverse`: whether it can also be asked backwards ("Paris is the
  capital of which country?"), which needs the value to belong to one
  subject only;
- `plural_ok`: rarely, a property whose several values can be asked as
  one answer. Not used yet; every fact here has one value.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Prop:
    label: str
    phrase: str
    kind: str = "item"
    adjust: float = 0.0
    reverse: bool = False


PROPERTIES = {
    # Places and countries
    "P36": Prop("capital", "The capital of {s} is {o}.", adjust=-1.0, reverse=True),
    "P38": Prop("currency", "The currency of {s} is {o}.", adjust=0.0),
    "P37": Prop("official language", "The official language of {s} is {o}.", adjust=-0.3),
    "P30": Prop("continent", "{s} is in {o}.", adjust=-1.0),
    "P17": Prop("country", "{s} is in {o}.", adjust=0.3),
    "P131": Prop("located in", "{s} is in {o}.", adjust=0.8),
    "P206": Prop("next to body of water", "{s} lies on {o}.", adjust=1.0),
    "P403": Prop("mouth of the watercourse", "{s} flows into {o}.", adjust=1.2),
    "P610": Prop("highest point", "The highest point of {s} is {o}.", adjust=1.2, reverse=True),
    "P4552": Prop("mountain range", "{s} is in the {o}.", adjust=1.0),
    "P85": Prop("anthem", "The national anthem of {s} is {o}.", adjust=1.8, reverse=True),
    "P1549": Prop("demonym", "People from {s} are called {o}.", kind="string", adjust=0.5),
    "P474": Prop("calling code", "The international calling code of {s} is {o}.", kind="string",
                 adjust=2.5, reverse=True),
    # People
    "P19": Prop("place of birth", "{s} was born in {o}.", adjust=1.6),
    "P20": Prop("place of death", "{s} died in {o}.", adjust=2.0),
    "P27": Prop("country of citizenship", "{s} was a citizen of {o}.", adjust=0.3),
    "P569": Prop("year of birth", "{s} was born in {o}.", kind="year", adjust=2.2),
    "P570": Prop("year of death", "{s} died in {o}.", kind="year", adjust=2.4),
    "P22": Prop("father", "The father of {s} is {o}.", adjust=1.2),
    "P25": Prop("mother", "The mother of {s} is {o}.", adjust=1.4),
    "P1477": Prop("birth name", "{s} was born with the name {o}.", kind="string", adjust=1.8),
    "P641": Prop("sport", "{s} is known for {o}.", adjust=-0.5),
    "P463": Prop("member of", "{s} was a member of {o}.", adjust=0.5),
    "P1303": Prop("instrument", "{s} played the {o}.", adjust=1.0),
    # Works
    "P50": Prop("author", "{s} was written by {o}.", adjust=0.0),
    "P57": Prop("director", "{s} was directed by {o}.", adjust=0.6),
    "P86": Prop("composer", "{s} was composed by {o}.", adjust=0.6),
    "P676": Prop("lyrics by", "The lyrics of {s} were written by {o}.", adjust=1.5),
    "P170": Prop("creator", "{s} was created by {o}.", adjust=0.2),
    "P175": Prop("performer", "{s} was performed by {o}.", adjust=0.2),
    "P577": Prop("year of publication", "{s} was first published or released in {o}.",
                 kind="year", adjust=2.0),
    "P144": Prop("based on", "{s} is based on {o}.", adjust=0.8),
    "P155": Prop("follows", "{s} came after {o}.", adjust=1.5),
    "P156": Prop("followed by", "{s} was followed by {o}.", adjust=1.5),
    "P179": Prop("part of the series", "{s} is part of the {o} series.", adjust=0.0),
    "P449": Prop("original broadcaster", "{s} was first broadcast on {o}.", adjust=1.5),
    "P840": Prop("narrative location", "{s} is set in {o}.", adjust=1.2),
    "P272": Prop("production company", "{s} was produced by {o}.", adjust=2.0),
    "P264": Prop("record label", "{s} was released on {o}.", adjust=2.5),
    "P123": Prop("publisher", "{s} was published by {o}.", adjust=1.8),
    "P178": Prop("developer", "{s} was developed by {o}.", adjust=0.8),
    "P176": Prop("manufacturer", "{s} is made by {o}.", adjust=0.6),
    "P1080": Prop("fictional universe", "{s} is from the fictional universe of {o}.", adjust=-0.3),
    "P1441": Prop("present in work", "{s} appears in {o}.", adjust=0.0),
    "P136": Prop("genre", "{s} is a {o}.", adjust=1.0),
    "P407": Prop("language of work", "{s} is in {o}.", adjust=0.8),
    "P135": Prop("movement", "{s} belongs to the {o} movement.", adjust=1.5),
    # Science and nature
    "P246": Prop("element symbol", "The chemical symbol of {s} is {o}.", kind="string",
                 adjust=0.3, reverse=True),
    "P1086": Prop("atomic number", "The atomic number of {s} is {o}.", kind="number",
                  adjust=1.8, reverse=True),
    "P274": Prop("chemical formula", "The chemical formula of {s} is {o}.", kind="string",
                 adjust=1.0, reverse=True),
    "P61": Prop("discoverer or inventor", "{s} was discovered or invented by {o}.", adjust=1.5),
    "P575": Prop("year of discovery", "{s} was discovered or invented in {o}.", kind="year",
                 adjust=2.5),
    "P397": Prop("parent astronomical body", "{s} orbits {o}.", adjust=0.3),
    "P225": Prop("scientific name", "The scientific name of the {s} is {o}.", kind="string",
                 adjust=2.2, reverse=True),
    "P186": Prop("made from", "{s} is made from {o}.", adjust=0.8),
    "P495": Prop("country of origin", "{s} comes from {o}.", adjust=0.3),
    # Buildings and landmarks
    "P84": Prop("architect", "{s} was designed by {o}.", adjust=1.5),
    "P149": Prop("architectural style", "{s} is built in the {o} style.", adjust=2.0),
    "P88": Prop("commissioned by", "{s} was commissioned by {o}.", adjust=1.8),
    "P571": Prop("year founded", "{s} was founded or made in {o}.", kind="year", adjust=2.2),
    # Events
    "P585": Prop("year", "{s} happened in {o}.", kind="year", adjust=1.5),
    "P276": Prop("location", "{s} took place in {o}.", adjust=0.8),
    "P1346": Prop("winner", "{s} was won by {o}.", adjust=0.5),
    # Organisations
    "P112": Prop("founded by", "{s} was founded by {o}.", adjust=0.6),
    "P159": Prop("headquarters", "{s} is headquartered in {o}.", adjust=1.2),
    # Language
    "P282": Prop("writing system", "{s} is written in the {o}.", adjust=1.2),
}

ITEM_PROPERTIES = [p for p, prop in PROPERTIES.items() if prop.kind != "year"]
YEAR_PROPERTIES = [p for p, prop in PROPERTIES.items() if prop.kind == "year"]


def phrase(pid: str, subject: str, value: str) -> str:
    prop = PROPERTIES.get(pid)
    if prop is None:
        return f"{subject}: {value}."
    return prop.phrase.format(s=subject, o=value)
