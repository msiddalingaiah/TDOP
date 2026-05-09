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


@dataclass(frozen=True)
class Let(Expr):
    """Let binding: evaluate value, bind it to name, evaluate body.

    Implements let* semantics — each binding is in scope for subsequent
    bindings and the body.  Bindings are immutable (single assignment).
    No memory operations are emitted; the bound value lives in a VReg
    and is spilled by the allocator only if register pressure demands it.
    """
    name:  str
    value: Expr
    body:  Expr


@dataclass(frozen=True)
class Var(Expr):
    """A reference to a let-bound or mutable variable."""
    name: str


@dataclass(frozen=True)
class MutVar(Expr):
    """Mutable variable declaration: (var name init body).

    Allocates a stack slot for name, stores init to it, then evaluates
    body with name in scope as a mutable variable.
    """
    name: str
    init: Expr
    body: Expr


@dataclass(frozen=True)
class SetBang(Expr):
    """Mutable variable assignment: (set! name value).

    Stores value to the mutable variable named name and returns the
    new value.  name must be in scope as a mutable variable.
    """
    name:  str
    value: Expr


@dataclass(frozen=True)
class Begin(Expr):
    """Expression sequencing: (begin first second).

    Evaluates first for its side effects, then evaluates and returns
    second.
    """
    first:  Expr
    second: Expr


@dataclass(frozen=True)
class While(Expr):
    """While loop: evaluate body while cond is true, return 0.

    cond must be a Lt, Gt, or Eq node.
    body is evaluated for side effects each iteration.
    Mutable variables (var/set!) carry state across iterations.
    """
    cond: Expr
    body: Expr


@dataclass(frozen=True)
class Div(Expr):
    """Integer division: left // right."""
    left:  Expr
    right: Expr


@dataclass(frozen=True)
class Mod(Expr):
    """Integer modulo: left % right."""
    left:  Expr
    right: Expr


@dataclass(frozen=True)
class And(Expr):
    """Bitwise AND: left & right."""
    left:  Expr
    right: Expr


@dataclass(frozen=True)
class Or(Expr):
    """Bitwise OR: left | right."""
    left:  Expr
    right: Expr


@dataclass(frozen=True)
class Xor(Expr):
    """Bitwise XOR: left ^ right."""
    left:  Expr
    right: Expr


@dataclass(frozen=True)
class Shl(Expr):
    """Left shift: left << right."""
    left:  Expr
    right: Expr


@dataclass(frozen=True)
class Shr(Expr):
    """Arithmetic right shift: left >> right (sign-extending)."""
    left:  Expr
    right: Expr


@dataclass(frozen=True)
class Call(Expr):
    """Function call: (call name arg ...)

    Calls a Flux function registered in the FunctionRegistry.
    args is a tuple of Expr nodes (one per argument).
    """
    name: str
    args: tuple   # Tuple[Expr, ...]


@dataclass(frozen=True)
class Defun(Expr):
    """Function definition: (defun name (params ...) body ...)

    Compiles the body as a named function, registers it in the
    FunctionRegistry, and returns 0 as its value.
    params is a tuple of parameter name strings.
    """
    name:   str
    params: tuple   # Tuple[str, ...]
    body:   Expr
