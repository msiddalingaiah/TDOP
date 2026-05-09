"""
High-level interface for the Flux compiler backend.
"""
from __future__ import annotations
import ctypes
import sys
from typing import Optional

from flux.core.parser        import parse_expr
from flux.core.builder       import FunctionBuilder
from flux.core.burg          import BurgSelector
from flux.core.linear_scan   import LinearScanAllocator
from flux.core.registry      import FunctionRegistry
from flux.core.jit           import make_callable, free_code
from flux.targets.x86_64.emitter  import X86_64Emitter
from flux.targets.x86_64.targets  import WINDOWS, LINUX

TARGET = WINDOWS if sys.platform == "win32" else LINUX

# Default session-level registry for interactive use.
_global_registry = FunctionRegistry()


def get_global_registry() -> FunctionRegistry:
    """Return the default global function registry."""
    return _global_registry


def reset_global_registry() -> None:
    """Replace the global registry with a fresh one (useful for tests)."""
    global _global_registry
    _global_registry = FunctionRegistry()


def compile_expr(sexpr: str,
                 registry: Optional[FunctionRegistry] = None,
                 **kwargs: int):
    """Parse and compile an S-expression, returning (Function, bytes).

    registry — FunctionRegistry for defun/call support.  Defaults to
               the global registry.
    **kwargs — variable bindings (name=value) for named arguments.
    """
    if registry is None:
        registry = _global_registry

    arg_names = list(kwargs.keys())

    expr     = parse_expr(sexpr, args=arg_names)
    builder  = FunctionBuilder("f")
    params   = builder.params(len(arg_names))
    selector = BurgSelector(params, builder,
                            registry=registry, target=TARGET)
    result   = selector.select(expr)
    builder.ret(result)
    fn = builder.build()

    emitter = X86_64Emitter(TARGET)
    LinearScanAllocator(TARGET).allocate(fn, emitter)
    return fn, emitter.get_code()


def compile_and_run(sexpr: str,
                    registry: Optional[FunctionRegistry] = None,
                    **kwargs: int) -> int:
    """Parse, compile, and execute a Flux S-expression.

    Supported operators: + - * / % & | ^ << >> < > = if let var set!
                         begin while defun call
    **kwargs supply named argument bindings.
    """
    if registry is None:
        registry = _global_registry

    arg_values   = list(kwargs.values())
    _, code      = compile_expr(sexpr, registry=registry, **kwargs)
    argtypes     = [ctypes.c_int64] * len(arg_values)
    func, handle = make_callable(code, ctypes.c_int64, *argtypes)
    value        = func(*arg_values)
    free_code(handle)
    return value
