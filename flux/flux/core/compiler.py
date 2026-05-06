"""
High-level interface for the Flux compiler backend.

Parses an S-expression, compiles it to native code via the full pipeline,
and executes it immediately, returning the integer result.
"""
from __future__ import annotations
import ctypes
import sys
from typing import Any

from flux.core.parser        import parse_expr
from flux.core.builder       import FunctionBuilder
from flux.core.burg          import BurgSelector
from flux.core.linear_scan   import LinearScanAllocator
from flux.core.jit           import make_callable, free_code
from flux.targets.x86_64.emitter  import X86_64Emitter
from flux.targets.x86_64.targets  import WINDOWS, LINUX

TARGET = WINDOWS if sys.platform == "win32" else LINUX


def compile_expr(sexpr: str, **kwargs: int):
    """Parse and compile an S-expression, returning (Function, bytes).

    Does not execute the generated code.  Useful for inspecting the
    intermediate representation or the raw machine code bytes.
    """
    arg_names  = list(kwargs.keys())
    arg_values = [kwargs[name] for name in arg_names]   # noqa: F841 — returned by caller

    expr     = parse_expr(sexpr, args=arg_names)
    builder  = FunctionBuilder("f")
    params   = builder.params(len(arg_names))
    selector = BurgSelector(params, builder)
    result   = selector.select(expr)
    builder.ret(result)
    fn = builder.build()

    emitter = X86_64Emitter(TARGET)
    LinearScanAllocator(TARGET).allocate(fn, emitter)
    return fn, emitter.get_code()


def compile_and_run(sexpr: str, **kwargs: int) -> int:
    """Parse, compile, and execute a simple arithmetic S-expression.

    Keyword arguments supply named variable bindings.  Variable names
    must appear in the expression; their order determines the function
    signature.

    Supported operators: ``+``  ``-``  ``*``
    Supported atoms:     integer literals, variable names

    Parameters
    ----------
    sexpr:
        The S-expression to evaluate, e.g. ``"(+ (* x 3) (- y 1))"``
    **kwargs:
        Variable bindings, e.g. ``x=10, y=5``

    Returns
    -------
    int
        The 64-bit integer result of evaluating the expression.

    Examples
    --------
    >>> compile_and_run("(+ 1 2)")
    3
    >>> compile_and_run("(* x (+ y 1))", x=6, y=6)
    42
    """
    arg_values   = list(kwargs.values())
    _, code      = compile_expr(sexpr, **kwargs)
    argtypes     = [ctypes.c_int64] * len(arg_values)
    func, handle = make_callable(code, ctypes.c_int64, *argtypes)
    value        = func(*arg_values)
    free_code(handle)
    return value
