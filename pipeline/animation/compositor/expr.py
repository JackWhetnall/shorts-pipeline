"""
Curves for plots (decision 054): y as an expression in x, written by the
storyboard ("x^2", "exp(-x^2/2)/sqrt(2*pi)", "normal(x, 0, 1)"), sampled
into points.

The expression is parsed, never executed: only numbers, x, a few named
constants, arithmetic and a fixed list of functions are allowed, and
anything else is refused. A model's text can't run code here.
"""

from __future__ import annotations

import ast
import math

FUNCTIONS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "exp": math.exp, "sqrt": math.sqrt,
    "log": math.log, "ln": math.log, "log10": math.log10, "log2": math.log2, "abs": abs,
    "floor": math.floor, "ceil": math.ceil, "min": min, "max": max,
    "atan": math.atan, "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "normal": lambda x, mu=0.0, sigma=1.0: math.exp(-((x - mu) / sigma) ** 2 / 2)
    / (sigma * math.sqrt(2 * math.pi)),
    "sigmoid": lambda x: 1 / (1 + math.exp(-x)),
}
CONSTANTS = {"pi": math.pi, "e": math.e}
BINARY = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
          ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
          ast.Pow: lambda a, b: a ** b, ast.Mod: lambda a, b: a % b}
UNARY = {ast.USub: lambda a: -a, ast.UAdd: lambda a: a}
MAX_LENGTH = 160


class BadExpression(ValueError):
    pass


def parse(text: str):
    """The expression's syntax tree, checked; raises BadExpression."""
    text = str(text or "").strip().replace("^", "**")
    if not text or len(text) > MAX_LENGTH:
        raise BadExpression("empty or too long")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise BadExpression(str(exc)) from exc
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, ast.Load)) or type(node) in BINARY or \
                type(node) in UNARY:
            continue
        if isinstance(node, ast.Name) and node.id in FUNCTIONS and id(node) not in called:
            raise BadExpression(f"{node.id} needs brackets")
        if isinstance(node, (ast.BinOp, ast.UnaryOp)):
            if type(node.op) not in BINARY and type(node.op) not in UNARY:
                raise BadExpression(f"operator {type(node.op).__name__}")
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            continue
        if isinstance(node, ast.Name) and (node.id == "x" or node.id in CONSTANTS
                                           or node.id in FUNCTIONS):
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in FUNCTIONS and not node.keywords and len(node.args) <= 3:
            continue
        raise BadExpression(f"{type(node).__name__} isn't allowed")
    return tree.body


def _eval(node, x: float) -> float:
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return x if node.id == "x" else CONSTANTS[node.id]
    if isinstance(node, ast.BinOp):
        return BINARY[type(node.op)](_eval(node.left, x), _eval(node.right, x))
    if isinstance(node, ast.UnaryOp):
        return UNARY[type(node.op)](_eval(node.operand, x))
    if isinstance(node, ast.Call):
        return float(FUNCTIONS[node.func.id](*[_eval(a, x) for a in node.args]))
    raise BadExpression(type(node).__name__)


def sample(text: str, x0: float, x1: float, n: int = 160) -> list:
    """[(x, y)] along the curve; points where it isn't defined (a division
    by zero, a log of a negative) are None, which break the line."""
    tree = parse(text)
    out = []
    for i in range(n + 1):
        x = x0 + (x1 - x0) * i / n
        try:
            y = _eval(tree, x)
            out.append((x, y) if math.isfinite(y) and abs(y) < 1e9 else None)
        except (ArithmeticError, ValueError, TypeError, OverflowError):
            out.append(None)
    return out
