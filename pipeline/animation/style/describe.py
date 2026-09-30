"""
A style from a description: someone says what they picture ("cute stubby
paper people acting out history", "minimal 3D meeples for logic
puzzles") and gets the answers to the style questions that come closest,
the notes that carry what the options can't, and why (decision 053).

The model chooses only among the grammar's options (a schema enum per
question) and its answers go through the same conditions as anyone's, so
a description can only ever land on a combination that makes sense; an
answer that didn't fit is replaced and said so.
"""

from __future__ import annotations

from pipeline.animation import style
from pipeline.llm import call_json

GUIDE = """
You turn a description of an animated video style into answers to a fixed set of questions, so
the style can be built. For each question choose the option that comes closest to what the
person pictures; the options only make sense in certain combinations, which each option states,
so choose them in order and keep to options that fit the answers before. Use an option's
"custom" (something else) only when nothing listed is close, and then describe it in a few
words. Put anything the options can't capture (a particular colour, a period, a texture, a
character detail) into style notes, briefly, as instructions for an illustrator. Suggest a
palette of six colours only if the description implies one. Explain your choices in two
sentences a person would find useful.
""".strip()


def _menu() -> str:
    lines = []
    for q in style.questions():
        lines.append(f"\n{q['id']}: {q['ask']}")
        for o in q["options"]:
            cond = []
            if o.get("when"):
                cond.append(f"only when {o['when']}")
            if o.get("not"):
                cond.append(f"not when {o['not']}")
            lines.append(f"  - {o['id']}: {o['label']}. {o.get('hint', '')}"
                         + (f" ({'; '.join(cond)})" if cond else ""))
    return "\n".join(lines)


def schema() -> dict:
    props = {q["id"]: {"type": "string", "enum": [o["id"] for o in q["options"]] + [""]}
             for q in style.questions()}
    custom = [q["id"] for q in style.questions() if any(o.get("custom") for o in q["options"])]
    props.update({f"custom_{c}": {"type": "string"} for c in custom})
    props.update({"style_notes": {"type": "string"},
                  "palette": {"type": "array", "items": {"type": "string"}},
                  "why": {"type": "string"}})
    return {"type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}


def describe(text: str, channel=None) -> dict:
    """{"style", "changed", "notes", "palette", "why", "summary"}."""
    about = ""
    if channel is not None:
        about = f"The channel: {getattr(channel, 'channel_display_name', '') or channel.key}. " \
                f"{(getattr(channel, 'style_prompt', '') or '')[:600]}"
    user = f"THE QUESTIONS:{_menu()}\n\n{about}\n\nTHE DESCRIPTION:\n{text.strip()[:1500]}"
    data = call_json(GUIDE, user, schema(), operation="animation_style_describe",
                     max_tokens=6000, effort="medium")
    given = {q["id"]: data.get(q["id"]) for q in style.questions() if data.get(q["id"])}
    given["custom"] = {k[len("custom_"):]: v for k, v in data.items()
                       if k.startswith("custom_") and str(v or "").strip()}
    answers, changed = style.normalise(given)
    palette = [c for c in data.get("palette") or [] if style.HEX_RE.match(str(c))][:6]
    return {"style": answers, "changed": changed,
            "notes": " ".join(str(data.get("style_notes") or "").split())[:600],
            "palette": palette if len(palette) >= 4 else [],
            "why": " ".join(str(data.get("why") or "").split()),
            "summary": style.summary(answers)}
