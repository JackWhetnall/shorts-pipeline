"""
A LaTeX-like subset to HTML, for the equation template: fractions,
roots, powers, subscripts, colour per term, the usual symbols. The same
subset the free-form scene engine understands, so the model writes one
notation everywhere.
"""

from __future__ import annotations

import html

SYMBOLS = {"times": " × ", "div": " ÷ ", "pm": " ± ", "cdot": " · ", "pi": "π", "theta": "θ",
           "le": " ≤ ", "ge": " ≥ ", "ne": " ≠ ", "approx": " ≈ ", "infty": "∞", "alpha": "α",
           "beta": "β", "gamma": "γ", "Delta": "Δ", "sum": "Σ", "to": " → ", "degree": "°",
           "percent": "%", "quad": " ", "qquad": "  ", ",": " "}
OPERATORS = "+-=<>"
COLOURS = {"accent1", "accent2", "accent3", "accent4", "accent5", "ink", "ink_soft"}


class _Parser:
    def __init__(self, src: str):
        self.s, self.i = src, 0

    def row(self, end=None) -> str:
        out = []
        while self.i < len(self.s) and self.s[self.i] != end:
            ch = self.s[self.i]
            if ch == " ":
                self.i += 1
            elif ch in "^_":
                self.i += 1
                tag = "sup" if ch == "^" else "sub"
                out.append(f"<{tag}>{self.group()}</{tag}>")
            else:
                first = not out
                piece = self.atom()
                out.append(piece.strip() if first and piece.strip() in ("+", "-", "−") else piece)
        return "".join(out)

    def group(self) -> str:
        if self.i < len(self.s) and self.s[self.i] == "{":
            self.i += 1
            inner = self.row("}")
            self.i += 1
            return inner
        return self.atom()

    def atom(self) -> str:
        ch = self.s[self.i]
        if ch == "\\":
            j = self.i + 1
            while j < len(self.s) and self.s[j].isalpha():
                j += 1
            if j == self.i + 1 and j < len(self.s):
                j += 1
            name = self.s[self.i + 1:j]
            self.i = j
            if name == "frac":
                num, den = self.group(), self.group()
                return f"<span class='frac'><span>{num}</span><span>{den}</span></span>"
            if name == "sqrt":
                return f"<span class='sqrt'>√<span class='rad'>{self.group()}</span></span>"
            if name == "color":
                colour = html.unescape(self.group()).strip()
                body = self.group()
                token = colour if colour in COLOURS else "ink"
                return f"<span class='tex-{token}'>{body}</span>"
            return html.escape(SYMBOLS.get(name, name))
        self.i += 1
        if ch in OPERATORS:
            return f" {html.escape('−' if ch == '-' else ch)} "
        return html.escape(ch)


def to_html(src: str) -> str:
    return _Parser(str(src or "")).row()


CSS = """
.tex { font-family: var(--display); font-weight: var(--dw); white-space: pre; }
.tex sup { font-size: .6em; vertical-align: .75em; line-height: 0; }
.tex sub { font-size: .6em; vertical-align: -.25em; line-height: 0; }
.tex .frac { display: inline-flex; flex-direction: column; vertical-align: middle; text-align: center;
  font-size: .8em; margin: 0 .1em; }
.tex .frac > span:first-child { border-bottom: .07em solid currentColor; padding: 0 .15em; }
.tex .sqrt .rad { border-top: .07em solid currentColor; padding: 0 .1em; }
.tex-accent1 { color: var(--a1); } .tex-accent2 { color: var(--a2); } .tex-accent3 { color: var(--a3); }
.tex-accent4 { color: var(--a4); } .tex-accent5 { color: var(--a5); } .tex-ink_soft { color: var(--soft); }
"""
