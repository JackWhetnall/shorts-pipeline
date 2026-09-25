"""
A channel's art direction as the templates' stylesheet.

The palette, fonts and line weight come from the channel's own art
direction (pipeline.scenes.art), so a template looks like that channel's
scenes and cards. Each preset adds its finish: sticker cards on Clean
flat, chalk wobble and board grain on Chalkboard, glow on Neon, paper
grain and ink rules on Parchment. Text colours on filled shapes are picked
by contrast, never assumed: white text on a white card is how labels went
invisible in the first Curiosity Leak video.
"""

from __future__ import annotations


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_on(fill: str, *candidates: str) -> str:
    """Whichever candidate reads best on `fill` (white and near-black are
    always among them: a chalk channel's ink and white are both light)."""
    options = [c for c in candidates if c] + ["#FFFFFF", "#15161C"]
    return max(options, key=lambda c: contrast(c, fill))


def _family(name: str) -> str:
    return f"'{name}', 'Segoe UI', sans-serif"


FINISH = {
    "clean_flat": """
      .card { background: var(--card); border: 6px solid var(--ink); border-radius: 28px;
              box-shadow: 0 12px 0 rgba(0,0,0,.14); }
      .chip { border: 5px solid var(--ink); box-shadow: 0 8px 0 rgba(0,0,0,.12); }
      .bg-pattern { background-image: radial-gradient(var(--pattern) 3.2px, transparent 3.4px);
                    background-size: 48px 48px; }
    """,
    "chalkboard": """
      .card { background: rgba(255,255,255,.04); border: 5px solid var(--ink); border-radius: 18px; }
      .chip { border: 4px solid var(--ink); }
      .stage { filter: url(#sketch); }
      .bg-grain { opacity: .12; }
    """,
    "neon": """
      .card { background: rgba(255,255,255,.04); border: 4px solid var(--a2); border-radius: 24px;
              box-shadow: 0 0 22px var(--a2), inset 0 0 18px rgba(43,217,254,.18); }
      .chip { border: 4px solid var(--a1); box-shadow: 0 0 16px var(--a1); }
      .glow, .hero, .title { text-shadow: 0 0 18px currentColor, 0 0 42px currentColor; }
      .bg-pattern { background-image: linear-gradient(var(--pattern) 2px, transparent 2px),
                    linear-gradient(90deg, var(--pattern) 2px, transparent 2px);
                    background-size: 64px 64px; }
    """,
    "parchment": """
      .card { background: rgba(255,255,255,.35); border: 3px solid var(--ink); border-radius: 6px;
              box-shadow: 0 4px 0 rgba(59,42,26,.12); }
      .chip { border: 3px solid var(--ink); }
      .stage { filter: url(#sketch); }
      .bg-grain { opacity: .16; }
    """,
}


def css(style: dict) -> str:
    """The stylesheet for one art direction."""
    c = style["colors"]
    bg = style["background"]["color"]
    card = c["label_fill"]
    vars_ = {
        "--bg": bg, "--ink": c["ink"], "--soft": c["ink_soft"], "--card": card,
        "--pattern": style["background"].get("pattern_color") or "rgba(0,0,0,.06)",
        "--vignette": str(style["background"].get("vignette") or 0),
        "--display": _family(style["font_display"]), "--text": _family(style["font_text"]),
        "--dw": str(style.get("font_display_weight", 700)), "--tw": str(style.get("font_text_weight", 600)),
        "--stroke": f"{style.get('stroke_width', 10)}px",
        "--on-card": text_on(card, c["ink"], bg),
    }
    for i in range(1, 6):
        accent = c[f"accent{i}"]
        vars_[f"--a{i}"] = accent
        vars_[f"--on-a{i}"] = text_on(accent, c["ink"], bg)
    declared = "".join(f"{k}:{v};" for k, v in vars_.items())
    # Last, so no finish's card background can cover an accent fill: that
    # left white text on a white card, the invisible-label failure.
    return (BASE.replace("/*VARS*/", declared) + FINISH.get(style["key"], "")
            + ".card.filled, .chip.filled { background: var(--fill); color: var(--on); }"
            ".card.filled .body { color: var(--on) !important; }")


BASE = """
:root { /*VARS*/ }
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: 1080px; height: 1920px; overflow: hidden; background: var(--bg); }
body { font-family: var(--text); font-weight: var(--tw); color: var(--ink); }
.bg { position: absolute; inset: 0; background: var(--bg); overflow: hidden; }
.bg-pattern { position: absolute; inset: -60px;
  transform: translateY(calc(var(--t, 0) * -6px)); }
.bg-vignette { position: absolute; inset: 0;
  background: radial-gradient(ellipse at 50% 38%, transparent 55%, rgba(0,0,0,var(--vignette)) 100%); }
.bg-grain { position: absolute; inset: 0; opacity: 0; mix-blend-mode: overlay; }
/* The stage: above the captions' space (they start at about y 1320),
   drifting in very slightly across the scene so nothing sits frozen. */
.stage { position: absolute; left: 40px; top: 140px; width: 1000px; height: 1150px;
  display: flex; flex-direction: column; justify-content: center; gap: 34px;
  transform: scale(calc(1 + 0.03 * var(--t, 0) / var(--T, 1))); transform-origin: 50% 40%; }
.title { font-family: var(--display); font-weight: var(--dw); font-size: 76px; line-height: 1.05;
  text-align: center; color: var(--ink); }
.kicker { font-family: var(--text); font-weight: var(--tw); font-size: 42px; letter-spacing: .12em;
  text-transform: uppercase; color: var(--soft); text-align: center; }
.hero { font-family: var(--display); font-weight: var(--dw); line-height: 1; text-align: center; }
.body { font-size: 50px; line-height: 1.2; }
.chip { display: inline-flex; align-items: center; justify-content: center; border-radius: 999px;
  font-family: var(--display); font-weight: var(--dw); }
.icon { width: 100%; height: 100%; object-fit: contain; }
.card { position: relative; }
.a1 { --fill: var(--a1); --on: var(--on-a1); } .a2 { --fill: var(--a2); --on: var(--on-a2); }
.a3 { --fill: var(--a3); --on: var(--on-a3); } .a4 { --fill: var(--a4); --on: var(--on-a4); }
.a5 { --fill: var(--a5); --on: var(--on-a5); }
.filled { background: var(--fill); color: var(--on); }
.accent-text { color: var(--fill); }
/* Entrances, driven by the engine's --p (linear), --e (eased), --q (exit). */
[data-in] { opacity: calc(min(1, var(--p, 0) * 3) * (1 - var(--q, 0))); }
[data-anim="rise"] { transform: translateY(calc((1 - var(--e, 0)) * 70px)); }
[data-anim="pop"] { transform: scale(calc(0.4 + 0.6 * var(--e, 0))); }
[data-anim="slide-left"] { transform: translateX(calc((1 - var(--e, 0)) * -160px)); }
[data-anim="slide-right"] { transform: translateX(calc((1 - var(--e, 0)) * 160px)); }
[data-anim="fade"] { opacity: calc(var(--e, 0) * (1 - var(--q, 0))); }
[data-anim="wipe"] { clip-path: inset(0 calc((1 - var(--e, 0)) * 100%) 0 0); opacity: calc(1 - var(--q, 0)); }
[data-anim="draw"] { opacity: calc(min(1, var(--p, 0) * 8) * (1 - var(--q, 0))); }
[data-anim="grow"] { transform: scaleX(var(--e, 0)); transform-origin: 0 50%; opacity: 1; }
[data-anim="grow-up"] { transform: scaleY(var(--e, 0)); transform-origin: 50% 100%; opacity: 1; }
[data-anim="strike"] { transform: scaleX(var(--e, 0)); transform-origin: 0 50%; opacity: 1; }
"""
