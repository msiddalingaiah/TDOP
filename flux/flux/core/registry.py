"""
FunctionRegistry — stores compiled Flux functions and manages the
pointer holders that enable indirect calls and recursion.

Each declared function gets a ctypes.c_uint64 pointer holder before its
body is compiled.  Call sites embed the holder's address and dereference
it at runtime.  After compilation the holder is filled in with the
function's actual address.  This lets recursive (and mutually recursive)
call sites reference a function before it is fully compiled.
"""
from __future__ import annotations
import ctypes
from typing import Dict, Any


class FunctionRegistry:
    """Registry of Flux-compiled functions.

    Usage::

        reg = FunctionRegistry()

        # declare before compiling so recursive calls can reference it
        reg.declare("fact", n_params=1)

        # compile and register
        reg.compile_and_register("fact", ir_fn, target)

        # call
        reg.call("fact", 10)   # → 3628800
    """

    def __init__(self) -> None:
        # Array-of-1 so ctypes.addressof works on the element
        self._holders:   Dict[str, Any] = {}   # name → (c_uint64 * 1)
        self._callables: Dict[str, Any] = {}   # name → ctypes callable
        self._handles:   Dict[str, Any] = {}   # name → memory handle
        self._n_params:  Dict[str, int] = {}   # name → param count

    # ------------------------------------------------------------------
    # Declaration
    # ------------------------------------------------------------------

    def declare(self, name: str, n_params: int) -> None:
        """Pre-declare *name*, allocating its pointer holder.

        Must be called before compiling any function that calls *name*
        so call sites can embed the holder's address.
        Safe to call multiple times — subsequent calls are no-ops.
        """
        if name not in self._holders:
            self._holders[name]  = (ctypes.c_uint64 * 1)(0)
            self._n_params[name] = n_params

    def get_ptr_holder_addr(self, name: str) -> int:
        """Return the stable address of *name*'s pointer holder."""
        if name not in self._holders:
            raise RuntimeError(
                f"Undeclared function '{name}' — "
                f"call declare() before compiling callers."
            )
        return ctypes.addressof(self._holders[name])

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, name: str, code: bytes) -> None:
        """Create a callable from *code* and fill in the pointer holder."""
        from flux.core.jit import make_callable
        n        = self._n_params.get(name, 0)
        argtypes = [ctypes.c_int64] * n
        func, handle = make_callable(code, ctypes.c_int64, *argtypes)

        self._callables[name] = func
        self._handles[name]   = handle

        # Fill the pointer holder with the function's address.
        func_ptr = ctypes.cast(func, ctypes.c_void_p).value
        self._holders[name][0] = func_ptr

    def compile_and_register(self, name: str, fn, target) -> None:
        """Compile IR function *fn* for *target* and register it."""
        from flux.core.linear_scan      import LinearScanAllocator
        from flux.targets.x86_64.emitter import X86_64Emitter
        emitter = X86_64Emitter(target)
        LinearScanAllocator(target).allocate(fn, emitter)
        self.register(name, emitter.get_code())

    # ------------------------------------------------------------------
    # Invocation
    # ------------------------------------------------------------------

    def call(self, name: str, *args: int) -> int:
        """Call a compiled function by name and return the result."""
        if name not in self._callables:
            raise RuntimeError(f"Function '{name}' is not compiled yet.")
        return self._callables[name](*args)

    def __contains__(self, name: str) -> bool:
        return name in self._callables
