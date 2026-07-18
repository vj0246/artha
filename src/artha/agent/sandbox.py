"""Restricted expression DSL for agent-proposed features (Track B B6).

Model output is never executed directly. A proposal's ``expression`` is
parsed with :mod:`ast` and every node is checked against a whitelist:
arithmetic, numeric/string constants, and calls to the named DSL
functions below — no attribute access, no subscripts, no keywords, no
names outside the function table. Only after that audit is the tree
evaluated, with empty builtins, to produce a polars expression. The DSL
functions return per-row exprs WITHOUT grouping; the pipeline applies
``.over("canon_symbol")`` to the final expression, so every rolling or
shift window is per-symbol by construction (no cross-symbol leakage).
"""

import ast
from collections.abc import Callable
from typing import Final

import polars as pl

ALLOWED_COLUMNS: Final = frozenset({"adj_close", "close", "high", "low", "traded_value"})
MAX_WINDOW: Final = 252


class SandboxError(Exception):
    """Raised when an expression falls outside the whitelisted DSL."""


def _col(name: str) -> pl.Expr:
    if name not in ALLOWED_COLUMNS:
        raise SandboxError(f"column {name!r} not in {sorted(ALLOWED_COLUMNS)}")
    return pl.col(name)


def _dret() -> pl.Expr:
    return pl.col("adj_close") / pl.col("adj_close").shift(1) - 1


def _window(n: object) -> int:
    if not isinstance(n, int) or not 1 <= n <= MAX_WINDOW:
        raise SandboxError(f"window must be int in [1, {MAX_WINDOW}], got {n!r}")
    return n


def _shift(e: pl.Expr, n: object) -> pl.Expr:
    return e.shift(_window(n))


def _roll_mean(e: pl.Expr, n: object) -> pl.Expr:
    return e.rolling_mean(window_size=_window(n))


def _roll_std(e: pl.Expr, n: object) -> pl.Expr:
    return e.rolling_std(window_size=_window(n))


def _roll_max(e: pl.Expr, n: object) -> pl.Expr:
    return e.rolling_max(window_size=_window(n))


def _roll_min(e: pl.Expr, n: object) -> pl.Expr:
    return e.rolling_min(window_size=_window(n))


def _absv(e: pl.Expr) -> pl.Expr:
    return e.abs()


def _log1p(e: pl.Expr) -> pl.Expr:
    return (e + 1.0).log()


DSL_FUNCTIONS: Final[dict[str, Callable[..., pl.Expr]]] = {
    "col": _col,
    "dret": _dret,
    "shift": _shift,
    "roll_mean": _roll_mean,
    "roll_std": _roll_std,
    "roll_max": _roll_max,
    "roll_min": _roll_min,
    "absv": _absv,
    "log1p": _log1p,
}

_ALLOWED_NODES: Final = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.USub,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Call,
    ast.Name,
    ast.Constant,
    ast.Load,
)


def compile_expression(source: str) -> pl.Expr:
    """Audit ``source`` against the DSL whitelist, then evaluate it to a
    polars expression. Raises :class:`SandboxError` on anything else."""
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise SandboxError(f"not a valid expression: {exc}") from exc
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise SandboxError(f"disallowed syntax: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in DSL_FUNCTIONS:
                raise SandboxError("only whitelisted DSL functions may be called")
            if node.keywords:
                raise SandboxError("keyword arguments not allowed")
        if isinstance(node, ast.Name) and node.id not in DSL_FUNCTIONS:
            raise SandboxError(f"unknown name {node.id!r}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, int | float | str):
            raise SandboxError(f"constant {node.value!r} not allowed")
    value = eval(  # audited tree, empty builtins, DSL names only
        compile(tree, "<agent-feature>", "eval"), {"__builtins__": {}}, dict(DSL_FUNCTIONS)
    )
    if not isinstance(value, pl.Expr):
        raise SandboxError("expression must evaluate to a polars expression")
    return value
