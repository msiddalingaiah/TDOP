from __future__ import annotations
import re
from typing import Dict, List, Optional

from flux.core.tree import Expr, Const, Arg, Add, Sub, Mul


def _tokenize(s: str) -> List[str]:
    """Split an S-expression string into a flat token list."""
    return re.findall(r'[()]|[^\s()]+', s)


def _parse_tokens(tokens: List[str], args: Dict[str, int]) -> Expr:
    """Recursively consume tokens and return an Expr node."""
    if not tokens:
        raise ValueError("Unexpected end of input")

    token = tokens.pop(0)

    if token == '(':
        if not tokens:
            raise ValueError("Unexpected end of input after '('")

        op = tokens.pop(0)

        operands: List[Expr] = []
        while tokens and tokens[0] != ')':
            operands.append(_parse_tokens(tokens, args))

        if not tokens:
            raise ValueError(f"Missing closing ')' for operator '{op}'")
        tokens.pop(0)   # consume ')'

        if len(operands) != 2:
            raise ValueError(
                f"Operator '{op}' requires exactly 2 operands, "
                f"got {len(operands)}"
            )

        match op:
            case '+': return Add(operands[0], operands[1])
            case '-': return Sub(operands[0], operands[1])
            case '*': return Mul(operands[0], operands[1])
            case _:   raise ValueError(f"Unknown operator: '{op}'")

    elif token == ')':
        raise ValueError("Unexpected ')'")

    else:
        # Integer literal (including negative)
        try:
            return Const(int(token))
        except ValueError:
            pass

        # Named argument
        if token in args:
            return Arg(args[token])

        raise ValueError(f"Unknown symbol: '{token}'")


def parse_expr(s: str, args: Optional[List[str]] = None) -> Expr:
    """Parse an S-expression string into an Expr tree.

    Parameters
    ----------
    s:
        The S-expression to parse, e.g. ``"(+ (* x 3) (- y 1))"``
    args:
        Ordered list of argument names that may appear as symbols,
        e.g. ``["x", "y"]``.  The nth name maps to ``Arg(n)``.

    Examples
    --------
    >>> parse_expr("(+ 1 2)")
    Add(left=Const(value=1), right=Const(value=2))

    >>> parse_expr("(* x 3)", args=["x"])
    Mul(left=Arg(index=0), right=Const(value=3))
    """
    arg_map: Dict[str, int] = {name: i for i, name in enumerate(args or [])}
    tokens = _tokenize(s)

    if not tokens:
        raise ValueError("Empty expression")

    expr = _parse_tokens(tokens, arg_map)

    if tokens:
        raise ValueError(f"Unexpected trailing tokens: {tokens}")

    return expr
