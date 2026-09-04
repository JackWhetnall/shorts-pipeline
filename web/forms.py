"""
Turning submitted forms into config objects.

The important change from the version this replaces: a settings save
MUTATES the existing channel rather than rebuilding one from scratch.

Rebuilding meant every save wrote the complete field set, so any field
the form didn't happen to have an input for was overwritten with a blank.
That's why the setup wizard's fields all had to be duplicated onto the
settings form — otherwise saving settings after a wizard step silently
erased it. Applying a form onto the loaded channel makes that impossible:
a field the form doesn't mention simply isn't touched.
"""

from __future__ import annotations

from core import fonts
from core.channels import (
    Cta, EndScreen, ChannelConfig, Monetization, Pacing, Socials, Style,
)

PACING_INT_FIELDS = {"caption_max_group_size", "segment_count"}
STYLE_INT_FIELDS = {"font_size", "stroke_width"}
STYLE_TEXT_FIELDS = ("base_color", "highlight_color", "stroke_color",
                     "outro_title_color", "outro_subtext_color")


def lines(text: str) -> list:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def parse_affiliate_links(text: str) -> list:
    """One per line, "Label | https://..." or a bare URL."""
    out = []
    for line in lines(text):
        if "|" in line:
            label, url = line.split("|", 1)
            out.append({"label": label.strip(), "url": url.strip()})
        else:
            out.append({"label": "", "url": line})
    return out


def format_affiliate_links(links: list) -> str:
    """The inverse, so reopening the form shows what's saved."""
    out = []
    for link in links or []:
        label = link.get("label")
        out.append(f"{label} | {link['url']}" if label else link["url"])
    return "\n".join(out)


def _maybe_float(form, name, current):
    raw = form.get(name)
    if raw is None or raw == "":
        return current
    try:
        return float(raw)
    except ValueError:
        return current


def _maybe_int(form, name, current):
    value = _maybe_float(form, name, None)
    return current if value is None else int(value)


def apply_channel_form(channel: ChannelConfig, form) -> ChannelConfig:
    """Apply a settings/new-channel form onto `channel`, in place.

    Only fields the form actually carries are touched.
    """
    channel.content_mode = form.get("content_mode", channel.content_mode)
    channel.voice = form.get("voice", channel.voice).strip()
    channel.style_prompt = form.get("style_prompt", channel.style_prompt).strip()
    channel.channel_display_name = form.get(
        "channel_display_name", channel.channel_display_name).strip()
    channel.outro_subtext = form.get("outro_subtext", channel.outro_subtext).strip()
    channel.speed = _maybe_float(form, "speed", channel.speed)

    if "avoid_imagery" in form:
        channel.avoid_imagery = lines(form.get("avoid_imagery"))

    if channel.content_mode == "static_corpus":
        channel.source = form.get("source", channel.source).strip()
    else:
        if "topics" in form:
            channel.topics = lines(form.get("topics"))

    pacing = channel.pacing
    for field in Pacing.__dataclass_fields__:
        name = f"pacing_{field}"
        if name not in form:
            continue
        current = getattr(pacing, field)
        setattr(pacing, field,
                _maybe_int(form, name, current) if field in PACING_INT_FIELDS
                else _maybe_float(form, name, current))

    style = channel.style
    face = form.get("style_font_face", "").strip()
    # Validated against the curated list rather than stored as given: this
    # ends up as a filename lookup at render time, and an unknown value
    # would silently fall back to the default months later.
    if face in fonts.FACES_BY_KEY:
        style.font_face = face
    for field in STYLE_TEXT_FIELDS:
        value = form.get(f"style_{field}")
        if value:
            setattr(style, field, value.strip())
    for field in STYLE_INT_FIELDS:
        setattr(style, field, _maybe_int(form, f"style_{field}", getattr(style, field)))
    background = form.get("style_outro_bg_color", "")
    if background.strip():
        try:
            style.outro_bg_color = tuple(int(x.strip()) for x in background.split(",") if x.strip())
        except ValueError:
            pass    # leave the existing colour rather than writing something PIL will reject

    if "youtube_url" in form:
        channel.socials = Socials(
            youtube_url=form.get("youtube_url", "").strip(),
            tiktok_url=form.get("tiktok_url", "").strip(),
            instagram_url=form.get("instagram_url", "").strip(),
        )

    if "patreon_url" in form or "merch_url" in form or "affiliate_links" in form:
        monetization = channel.monetization
        if "patreon_url" in form:
            monetization.patreon_url = form.get("patreon_url", "").strip()
        if "merch_url" in form:
            monetization.merch_url = form.get("merch_url", "").strip()
        if "affiliate_links" in form:
            monetization.affiliate_links = parse_affiliate_links(form.get("affiliate_links"))

    if "end_screen_present" in form:
        ctas = {}
        for key in ("patreon", "merch", "affiliate"):
            ctas[key] = Cta(
                enabled=form.get(f"cta_{key}_enabled") == "on",
                text=form.get(f"cta_{key}_text", "").strip(),
            )
        channel.end_screen = EndScreen(
            enabled=form.get("end_screen_enabled") == "on",
            duration_seconds=_maybe_float(form, "end_screen_duration_seconds",
                                          channel.end_screen.duration_seconds),
            ctas=ctas,
        )

    return channel
