"""
Integration tests for the complete Flux pipeline:

    Expr tree
      → BurgSelector         (instruction selection)
      → FunctionBuilder      (linear IR construction)
      → LinearScanAllocator  (register allocation)
      → X86_64Emitter        (code generation)
      → execute in memory
"""
import ctypes
import sys

from flux.core.tree          import Const, Arg, Add, Sub
from flux.core.builder       import FunctionBuilder
from flux.core.burg          import BurgSelector
from flux.core.linear_scan   import LinearScanAllocator
from flux.targets.x86_64.emitter  import X86_64Emitter
from flux.targets.x86_64.targets  import WINDOWS, LINUX

from tests.jit import make_callable, free_code

TARGET = WINDOWS if sys.platform == "win32" else LINUX


def compile_and_run(n_params: int, expr, *args) -> int:
    """Full pipeline: Expr → bytes → result."""
    builder  = FunctionBuilder("f")
    params   = builder.params(n_params)
    selector = BurgSelector(params, builder)
    result   = selector.select(expr)
    builder.ret(result)
    fn       = builder.build()

    emitter   = X86_64Emitter(TARGET)
    allocator = LinearScanAllocator(TARGET)
    allocator.allocate(fn, emitter)
    code = emitter.get_code()

    argtypes = [ctypes.c_int64] * len(args)
    func, handle = make_callable(code, ctypes.c_int64, *argtypes)
    value = func(*args)
    free_code(handle)
    return value


class TestIntegration:

    def test_constant(self):
        assert compile_and_run(0, Const(42)) == 42

    def test_negative_constant(self):
        assert compile_and_run(0, Const(-7)) == -7

    def test_identity(self):
        assert compile_and_run(1, Arg(0), 99) == 99

    def test_add_two_args(self):
        assert compile_and_run(2, Add(Arg(0), Arg(1)), 10, 32) == 42

    def test_sub_two_args(self):
        assert compile_and_run(2, Sub(Arg(0), Arg(1)), 50, 8) == 42

    def test_add_const_rhs(self):
        # Const on the right should be tiled as an immediate operand.
        assert compile_and_run(1, Add(Arg(0), Const(1)), 41) == 42

    def test_sub_const_rhs(self):
        assert compile_and_run(1, Sub(Arg(0), Const(1)), 43) == 42

    def test_nested_add(self):
        # (a + b) + c
        expr = Add(Add(Arg(0), Arg(1)), Arg(2))
        assert compile_and_run(3, expr, 10, 20, 12) == 42

    def test_nested_sub(self):
        # a - (b - c)
        expr = Sub(Arg(0), Sub(Arg(1), Arg(2)))
        assert compile_and_run(3, expr, 40, 10, 12) == 42

    def test_mixed_depth(self):
        # (a + b) - c
        expr = Sub(Add(Arg(0), Arg(1)), Arg(2))
        assert compile_and_run(3, expr, 20, 30, 8) == 42

    def test_deep_expression(self):
        # ((a + b) - c) + (d - 1)
        expr = Add(
            Sub(Add(Arg(0), Arg(1)), Arg(2)),
            Sub(Arg(3), Const(1))
        )
        assert compile_and_run(4, expr, 10, 20, 8, 21) == 42

    def test_const_heavy(self):
        # Verify BURG tiles multiple Consts as immediates where possible.
        # (a + 10) - 9
        expr = Sub(Add(Arg(0), Const(10)), Const(9))
        assert compile_and_run(1, expr, 41) == 42
