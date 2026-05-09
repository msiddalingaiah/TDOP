from __future__ import annotations
import re
from typing import Dict, List, Optional

from flux.core.tree import (Expr, Const, Arg, Add, Sub, Mul, Div, Mod,
                            And, Or, Xor, Shl, Shr,
                            Lt, Gt, Eq, If, Let, Var,
                            MutVar, SetBang, Begin, While)


_VALID_NAME = re.compile(r'^[a-zA-Z_]\w*$')


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

        # ------------------------------------------------------------------
        # Special forms — consume tokens themselves before the generic loop
        # ------------------------------------------------------------------

        if op == 'if':
            operands: List[Expr] = []
            while tokens and tokens[0] != ')':
                operands.append(_parse_tokens(tokens, args))
            if not tokens:
                raise ValueError("Missing closing ')' for 'if'")
            tokens.pop(0)
            if len(operands) != 3:
                raise ValueError(
                    f"'if' requires exactly 3 subforms: (if cond then else), "
                    f"got {len(operands)}"
                )
            return If(operands[0], operands[1], operands[2])

        if op == 'let':
            return _parse_let(tokens, args)

        if op == 'var':
            return _parse_var(tokens, args)

        if op == 'set!':
            # (set! name expr)
            if not tokens or tokens[0] == ')':
                raise ValueError("'set!' requires a name and an expression")
            name = tokens.pop(0)
            if not _VALID_NAME.match(name):
                raise ValueError(
                    f"'set!' target must be a valid name, got '{name}'"
                )
            value = _parse_tokens(tokens, args)
            if not tokens or tokens[0] != ')':
                raise ValueError("Missing ')' for 'set!'")
            tokens.pop(0)
            return SetBang(name, value)

        if op == 'begin':
            # (begin expr1 expr2)
            operands: List[Expr] = []
            while tokens and tokens[0] != ')':
                operands.append(_parse_tokens(tokens, args))
            if not tokens:
                raise ValueError("Missing ')' for 'begin'")
            tokens.pop(0)
            if len(operands) != 2:
                raise ValueError(
                    f"'begin' requires exactly 2 expressions, got {len(operands)}"
                )
            return Begin(operands[0], operands[1])

        if op == 'while':
            return _parse_while(tokens, args)

        # ------------------------------------------------------------------
        # Binary operators
        # ------------------------------------------------------------------

        operands = []
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
            case '+':  return Add(operands[0], operands[1])
            case '-':  return Sub(operands[0], operands[1])
            case '*':  return Mul(operands[0], operands[1])
            case '/':  return Div(operands[0], operands[1])
            case '%':  return Mod(operands[0], operands[1])
            case '&':  return And(operands[0], operands[1])
            case '|':  return Or (operands[0], operands[1])
            case '^':  return Xor(operands[0], operands[1])
            case '<<': return Shl(operands[0], operands[1])
            case '>>': return Shr(operands[0], operands[1])
            case '<':  return Lt (operands[0], operands[1])
            case '>':  return Gt (operands[0], operands[1])
            case '=':  return Eq (operands[0], operands[1])
            case _:    raise ValueError(f"Unknown operator: '{op}'")

    elif token == ')':
        raise ValueError("Unexpected ')'")

    else:
        # Integer literal (including negative)
        try:
            return Const(int(token))
        except ValueError:
            pass

        # Named argument (function parameter from the caller)
        if token in args:
            return Arg(args[token])

        # Let-bound variable or other valid identifier
        if _VALID_NAME.match(token):
            return Var(token)

        raise ValueError(f"Unknown symbol: '{token}'")


def _parse_while(tokens: List[str], args: Dict[str, int]) -> Expr:
    """Parse the body of a ``while`` form after ``(while`` has been consumed.

    Syntax::

        (while cond expr ...)

    Evaluates ``cond`` (must be a comparison) before each iteration.
    Body expressions are evaluated in order for side effects (implicit
    begin), and the loop runs until the condition is false.
    Returns 0 when the loop exits.
    """
    # Parse condition.
    cond = _parse_tokens(tokens, args)

    # Parse one or more body expressions.
    exprs: List[Expr] = []
    while tokens and tokens[0] != ')':
        exprs.append(_parse_tokens(tokens, args))

    if not exprs:
        raise ValueError("'while' requires at least one body expression")
    if not tokens or tokens[0] != ')':
        raise ValueError("Missing ')' for 'while'")
    tokens.pop(0)

    # Fold multiple body expressions into nested Begins.
    body = exprs[-1]
    for e in reversed(exprs[:-1]):
        body = Begin(e, body)

    return While(cond, body)


def _parse_var(tokens: List[str], args: Dict[str, int]) -> Expr:
    """Parse the body of a ``var`` form after ``(var`` has been consumed.

    Syntax::

        (var name init expr ...)

    Declares a mutable variable ``name`` initialized to ``init``.
    All remaining expressions form the body; they are evaluated in order
    and the last one is returned (implicit begin semantics).
    """
    if not tokens or tokens[0] == ')':
        raise ValueError("'var' requires name, init, and at least one body expression")
    name = tokens.pop(0)
    if not _VALID_NAME.match(name):
        raise ValueError(f"'var' name must be a valid identifier, got '{name}'")

    init = _parse_tokens(tokens, args)

    # Body: one or more expressions, name excluded from args so it
    # resolves as a Var (mutable) reference rather than an Arg.
    body_args = {k: v for k, v in args.items() if k != name}

    exprs: List[Expr] = []
    while tokens and tokens[0] != ')':
        exprs.append(_parse_tokens(tokens, body_args))

    if not exprs:
        raise ValueError("'var' requires at least one body expression after init")

    if not tokens or tokens[0] != ')':
        raise ValueError("Missing ')' for 'var'")
    tokens.pop(0)

    # Fold multiple body expressions into nested Begins (right-associative):
    # [e1, e2, e3] → Begin(e1, Begin(e2, e3))
    body = exprs[-1]
    for e in reversed(exprs[:-1]):
        body = Begin(e, body)

    return MutVar(name, init, body)


def _parse_let(tokens: List[str], args: Dict[str, int]) -> Expr:
    """Parse the body of a ``let`` form after the opening ``(let`` has
    been consumed.

    Syntax::

        (let ((name1 expr1) (name2 expr2) ...) body)

    Implements ``let*`` semantics: each binding is in scope for
    subsequent bindings and the body.  Multiple bindings desugar to
    nested Let nodes.

    The closing ``)`` of the outer let form is consumed by the caller
    (the main ``_parse_tokens`` loop for the ``'let'`` operator case
    does NOT apply here — this function handles its own closing paren).
    """
    # Expect the binding list: ( (name val) ... )
    if not tokens or tokens[0] != '(':
        raise ValueError("'let' expects a binding list starting with '('")
    tokens.pop(0)  # consume '('

    bindings: List[tuple] = []
    bound_names: List[str] = []
    current_args = dict(args)   # updated progressively for let* semantics

    while tokens and tokens[0] != ')':
        if tokens[0] != '(':
            raise ValueError(
                f"Each binding must be '(name expr)', got '{tokens[0]}'"
            )
        tokens.pop(0)  # consume '('

        if not tokens:
            raise ValueError("Empty binding pair")
        name = tokens.pop(0)
        if not _VALID_NAME.match(name):
            raise ValueError(f"Invalid binding name: '{name}'")

        # Parse the value with the current args (let* semantics: earlier
        # bindings in this let are already excluded, so they parse as Var).
        value = _parse_tokens(tokens, current_args)

        if not tokens or tokens[0] != ')':
            raise ValueError(f"Missing ')' after value in binding '{name}'")
        tokens.pop(0)  # consume ')'

        bindings.append((name, value))
        bound_names.append(name)
        # Exclude this name from args for subsequent bindings (let* semantics).
        current_args = {k: v for k, v in current_args.items() if k != name}

    if not tokens:
        raise ValueError("Missing ')' to close binding list")
    tokens.pop(0)  # consume ')' of binding list

    # Parse the body.  Exclude let-bound names from args so they resolve
    # as Var references rather than Arg references (enabling shadowing).
    body_args = {k: v for k, v in args.items() if k not in bound_names}
    body = _parse_tokens(tokens, body_args)

    # Consume the closing ')' of the let form.
    if not tokens or tokens[0] != ')':
        raise ValueError("Missing closing ')' for 'let'")
    tokens.pop(0)

    # Build nested Let nodes (innermost = last binding).
    result = body
    for name, value in reversed(bindings):
        result = Let(name, value, result)

    return result


def parse_expr(s: str, args: Optional[List[str]] = None) -> Expr:
    """Parse an S-expression string into an Expr tree.

    Parameters
    ----------
    s:
        The S-expression to parse.
    args:
        Ordered list of argument names that appear as symbols in the
        expression, e.g. ``["x", "y"]``.  The nth name maps to
        ``Arg(n)``.

    Examples
    --------
    >>> parse_expr("(+ 1 2)")
    Add(left=Const(value=1), right=Const(value=2))

    >>> parse_expr("(let ((x 3)) (* x x))")
    Let(name='x', value=Const(value=3), body=Mul(left=Var(name='x'), right=Var(name='x')))
    """
    arg_map: Dict[str, int] = {name: i for i, name in enumerate(args or [])}
    tokens = _tokenize(s)

    if not tokens:
        raise ValueError("Empty expression")

    expr = _parse_tokens(tokens, arg_map)

    if tokens:
        raise ValueError(f"Unexpected trailing tokens: {tokens}")

    return expr
