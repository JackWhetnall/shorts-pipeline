"""
Builds a ready-to-paste YouTube description: the citation (if any) as a
reference line, then one line per active monetization CTA (see
config/channels.resolve_active_ctas — the same function video_assemble.py
uses for the end-screen video segment, so the two never disagree about
which CTAs are "active"), then the FTC-required affiliate disclosure if
an affiliate link was included.

Deliberately does not generate marketing copy — that would need its own
Claude call and wasn't asked for; this is a cheap, deterministic string
build, not a script-generation step.
"""

from config.channels import resolve_active_ctas

FTC_AFFILIATE_DISCLOSURE = "As an Amazon Associate I earn from qualifying purchases."


def generate_description(script: dict, monetization: dict, end_screen: dict) -> str:
    """script: the dict returned by script_gen.generate_script (only
    "citation" is used here). Returns the full description text."""
    lines = []
    if script.get("citation"):
        lines.append(f"Reference: {script['citation']}")

    active_ctas = resolve_active_ctas(monetization or {}, end_screen or {})
    cta_lines = []
    has_affiliate = False
    for cta in active_ctas:
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
