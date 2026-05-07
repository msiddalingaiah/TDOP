from __future__ import annotations
from dataclasses import dataclass


class Expr:
    """Base class for all tree IR expression nodes.

    Every node represents a value-producing expression.  Subclasses are
    pure data containers; behaviour is supplied by the BURG selector.
    """
    pass


@dataclass(frozen=True)
class Const(Expr):
    """An integer constant."""
    value: int


@dataclass(frozen=True)
class Arg(Expr):
    """A reference to the nth function parameter (zero-based)."""
    index: int


@dataclass(frozen=True)
class Add(Expr):
    """Addition: left + right."""
    left:  Expr
    right: Expr


@dataclass(frozen=True)
class Sub(Expr):
    """Subtraction: left - right."""
    left:  Expr
    right: Expr


@dataclass(frozen=True)
class Mul(Expr):
    """Multiplication: left * right."""
    left:  Expr
    right: Expr


@dataclass(frozen=True)
class Lt(Expr):
    """Less-than comparison: left < right."""
    left:  Expr
    right: Expr


@dataclass(frozen=True)
class Gt(Expr):
    """Greater-than comparison: left > right."""
    left:  Expr
    right: Expr


@dataclass(frozen=True)
class Eq(Expr):
    """Equality comparison: left = right."""
    left:  Expr
    right: Expr


@dataclass(frozen=True)
class If(Expr):
    """Conditional expression: if cond then then_ else else_.

    cond must be a Lt, Gt, or Eq node.
    """
    cond:  Expr
    then_: Expr
    else_: Expr
