"""
The ready-to-paste video description.

Reference line, then one line per active monetization CTA, then the FTC
affiliate disclosure if any affiliate link is included. `resolve_active_ctas`
is shared with the end-screen renderer, so the video and its description
can never disagree about what's being promoted.

Deliberately a deterministic string build, not a generation call. It
needs no creativity, and adding a paid API call to produce four lines of
boilerplate would be the wrong trade.
"""

from __future__ import annotations

from core.channels import resolve_active_ctas

FTC_AFFILIATE_DISCLOSURE = "As an Amazon Associate I earn from qualifying purchases."


def generate_description(script, monetization, end_screen) -> str:
    """Body, reference, CTAs, disclosure — in that order.

    The body now comes from the script call (which already had the
    passage in front of it) rather than not existing. What this produced
    before was a single line: "Reference: Revelation 14:14".
    """
    lines = []
    if script.description_body:
        lines.append(script.description_body.strip())
    if script.citation:
        if lines:
            lines.append("")
        lines.append(f"Reference: {script.citation}")

    cta_lines = []
    has_affiliate = False
    for cta in resolve_active_ctas(monetization, end_screen):
        if cta["type"] == "affiliate":
            has_affiliate = True
            cta_lines.append(cta["text"])
            for link in cta["links"]:
                label = link.get("label")
                cta_lines.append(f"- {label}: {link['url']}" if label else f"- {link['url']}")
        else:
            cta_lines.append(f"{cta['text']}: {cta['url']}")

    if cta_lines:
        if lines:
            lines.append("")
        lines.extend(cta_lines)

    if has_affiliate:
        lines.append("")
        lines.append(FTC_AFFILIATE_DISCLOSURE)

    return "\n".join(lines).strip()


def write_meta(plan) -> None:
    """The script alongside the video, for writing a title without
    re-watching it. Always UTF-8 — older files written before that was
    fixed are cp1252 and are read back with a fallback."""
    script = plan.script
    with open(plan.meta_path, "w", encoding="utf-8") as f:
        if script.citation:
            f.write(f"Reference: {script.citation}\n\n")
        if script.title_options:
            f.write("Title options:\n")
            for title in script.title_options:
                f.write(f"  - {title}\n")
            f.write("\n")
        for i, segment in enumerate(script.segments):
            f.write(f"[segment {i}]\n")
            f.write(f"{segment.text}\n")
            # The brief is recorded so a poor footage match can be traced
            # to whether the brief was wrong or the library was thin.
            # Without it the two are indistinguishable after the fact.
            if segment.shot_brief:
                f.write(f"  shot: {segment.shot_brief}\n")
            if segment.keywords:
                f.write(f"  keywords: {', '.join(segment.keywords)}\n")
            f.write("\n")


def write_description(plan) -> None:
    text = generate_description(plan.script, plan.channel.monetization, plan.channel.end_screen)
    with open(plan.description_path, "w", encoding="utf-8") as f:
        f.write(text)
