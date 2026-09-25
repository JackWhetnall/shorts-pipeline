"""
One filled example of every template: for the gallery page (what each
looks like in a channel's look) and the tests.
"""

SAMPLES = {
    "big_number": {"kicker": "Kids who catch yawns", "value": 4, "prefix": "Age ", "suffix": "+",
                   "caption": "Younger than four, almost nobody catches a yawn", "icon": "baby"},
    "versus": {"title": "Who makes you yawn?", "left": {"label": "Your dog", "value": "Often", "icon": "dog"},
               "right": {"label": "A stranger", "value": "Rarely", "icon": "person"},
               "verdict": "The closer you are, the more it spreads"},
    "list": {"title": "Signs of a contagious yawn", "items": [
        {"text": "You see someone yawn", "icon": "eyes"},
        {"text": "Your jaw starts to stretch", "icon": "yawning face"},
        {"text": "You yawn within seconds", "icon": "stopwatch"}], "highlight": 2},
    "steps": {"title": "How a yawn spreads", "steps": [
        {"text": "You see a yawn", "icon": "eyes"}, {"text": "Empathy circuits fire", "icon": "brain"},
        {"text": "Your body copies it", "icon": "yawning face"}]},
    "timeline": {"title": "Catching yawns as we grow", "events": [
        {"when": "Age 1", "text": "Babies don't catch them"}, {"when": "Age 4", "text": "It starts to happen"},
        {"when": "Adult", "text": "About half of us catch them"}]},
    "bars": {"title": "Chance you'll catch it", "unit": "%", "bars": [
        {"label": "Family", "value": 70}, {"label": "Friends", "value": 50},
        {"label": "Strangers", "value": 20}], "highlight": 0},
    "myth_fact": {"myth": "You yawn because you're tired", "fact": "Seeing a yawn is enough to trigger one"},
    "definition": {"term": "Echophenomena", "kind": "psychology",
                   "definition": "Copying what others do without meaning to, like yawns",
                   "example": "Catching a yawn is the most common one"},
    "quote": {"text": "Contagious yawning is a window into empathy.", "who": "Researchers, 2010"},
    "equation": {"title": "Pythagoras", "lines": [
        {"tex": r"\color{accent1}{a^2} + \color{accent2}{b^2} = \color{accent4}{c^2}"},
        {"tex": r"c = \sqrt{8^2 + 6^2} = 10"}], "note": "The ladder is ten feet long"},
    "one_in_n": {"n": 10, "k": 5, "icon": "person", "caption": "About half of adults catch a yawn"},
    "scale": {"title": "Sun vs Earth", "items": [
        {"label": "Earth", "value": 1, "icon": "globe showing europe-africa"},
        {"label": "Sun", "value": 109, "icon": "sun"}], "caption": "109 Earths fit across the Sun"},
}


def sample_times(name: str, slots: dict, duration: float = 6.0) -> dict:
    """Beats spread evenly across the first two thirds of the scene."""
    from pipeline.templates.library import TEMPLATES
    beats = TEMPLATES[name]["beats"](slots)
    step = (duration * 0.66) / max(1, len(beats))
    return {b: round(0.2 + i * step, 2) for i, b in enumerate(beats)}
