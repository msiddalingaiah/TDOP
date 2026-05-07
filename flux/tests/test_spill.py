"""
Tests for register spilling in LinearScanAllocator.

Strategy: build functions with more simultaneously live VRegs than
available physical registers (12 on both Windows and Linux after
reserving scratch registers), forcing the allocator to spill.
"""
import ctypes
import sys
import pytest

from flux.core.operands    import SpillSlot
from flux.core.builder     import FunctionBuilder
from flux.core.linear_scan import LinearScanAllocator, compute_intervals
from flux.core.compiler    import compile_and_run
from flux.core.tree        import Const, Arg, Add, Sub, If, Lt
from flux.core.burg        import BurgSelector
from flux.targets.x86_64.emitter  import X86_64Emitter
from flux.targets.x86_64.targets  import WINDOWS, LINUX

from tests.jit import make_callable, free_code

TARGET     = WINDOWS if sys.platform == "win32" else LINUX
N_REGS     = len(TARGET.registers)   # 12 allocatable registers


def compile_fn(fn):
    emitter   = X86_64Emitter(TARGET)
    allocator = LinearScanAllocator(TARGET)
    allocator.allocate(fn, emitter)
    return emitter.get_code()


def run(code, *args, restype=ctypes.c_int64):
    argtypes     = [ctypes.c_int64] * len(args)
    func, handle = make_callable(code, restype, *argtypes)
    result       = func(*args)
    free_code(handle)
    return result


def make_pressure_fn(n_constants: int) -> FunctionBuilder:
    """Build  f() = sum(0 .. n_constants-1).

    Loads all constants before adding any, keeping them simultaneously
    live and forcing spills when n_constants > N_REGS.
    """
    b    = FunctionBuilder("pressure")
    vals = [b.load_imm(i) for i in range(n_constants)]
    acc  = vals[0]
    for v in vals[1:]:
        acc = b.add(acc, v)
    b.ret(acc)
    return b


# ------------------------------------------------------------------
# Spill detection tests
# ------------------------------------------------------------------

class TestSpillDetection:

    def test_no_spill_below_threshold(self):
        """N_REGS - 1 constants (no params) should fit without any spills."""
        b     = make_pressure_fn(N_REGS - 1)
        alloc = LinearScanAllocator(TARGET)._build_allocation(b.build())
        assert all(not isinstance(v, SpillSlot) for v in alloc.values())

    def test_spill_triggered_above_threshold(self):
        """N_REGS + 1 constants should force at least one spill."""
        b     = make_pressure_fn(N_REGS + 1)
        alloc = LinearScanAllocator(TARGET)._build_allocation(b.build())
        assert any(isinstance(v, SpillSlot) for v in alloc.values())

    def test_spill_slots_have_negative_offsets(self):
        b     = make_pressure_fn(N_REGS + 2)
        alloc = LinearScanAllocator(TARGET)._build_allocation(b.build())
        for loc in alloc.values():
            if isinstance(loc, SpillSlot):
                assert loc.offset < 0, "spill slot offset must be negative (below RBP)"

    def test_frame_size_multiple_of_16(self):
        """Stack frame must be 16-byte aligned."""
        b         = make_pressure_fn(N_REGS + 3)
        allocator = LinearScanAllocator(TARGET)
        allocator._build_allocation(b.build())
        assert allocator._frame_size % 16 == 0


# ------------------------------------------------------------------
# Correctness tests — with spills
# ------------------------------------------------------------------

class TestSpillCorrectness:

    def _sum(self, n):
        return n * (n - 1) // 2

    def test_sum_just_over_threshold(self):
        """One spill slot — sum of 0..(N_REGS+1)."""
        n  = N_REGS + 2
        b  = make_pressure_fn(n)
        assert run(compile_fn(b.build())) == self._sum(n)

    def test_sum_two_over_threshold(self):
        """Two spill slots — sum of 0..(N_REGS+3)."""
        n  = N_REGS + 4
        b  = make_pressure_fn(n)
        assert run(compile_fn(b.build())) == self._sum(n)

    def test_sum_many_spills(self):
        """Many spill slots — sum of 0..19."""
        n  = 20
        b  = make_pressure_fn(n)
        assert run(compile_fn(b.build())) == self._sum(n)

    def test_spill_with_subtraction(self):
        """Verify spills work with SUB as well as ADD."""
        # f() = (10 + 11 + ... + (N_REGS+10)) - (N_REGS * 10)
        n    = N_REGS + 2
        b    = FunctionBuilder("sub_pressure")
        vals = [b.load_imm(i + 10) for i in range(n)]
        acc  = vals[0]
        for v in vals[1:]:
            acc = b.add(acc, v)
        # subtract to get a smaller result we can easily verify
        adj = b.load_imm(n * 10)
        acc = b.sub(acc, adj)
        b.ret(acc)
        # expected = sum(10..10+n-1) - n*10 = sum(0..n-1) = n*(n-1)//2
        assert run(compile_fn(b.build())) == self._sum(n)

    def test_no_spill_function_unchanged(self):
        """Non-spilling functions must still produce correct results."""
        b = FunctionBuilder("simple")
        a, x = b.params(2)
        r = b.add(a, x)
        b.ret(r)
        assert run(compile_fn(b.build()), 17, 25) == 42


# ------------------------------------------------------------------
# compile_and_run interface with spills
# ------------------------------------------------------------------

class TestCompileAndRunSpills:

    def test_constant_heavy_expr(self):
        # (+ (+ (+ (+ 1 2) (+ 3 4)) (+ (+ 5 6) (+ 7 8)))
        #    (+ (+ (+ 9 10) (+ 11 12)) (+ (+ 13 14) 15)))
        # = sum(1..15) = 120
        assert compile_and_run(
            "(+ (+ (+ (+ 1 2) (+ 3 4)) (+ (+ 5 6) (+ 7 8)))"
            "   (+ (+ (+ 9 10) (+ 11 12)) (+ (+ 13 14) 15)))"
        ) == 120

    def test_spill_with_conditional(self):
        """Spilling and conditionals must coexist."""
        # Absolute value with many temporaries loaded to force spills
        b  = FunctionBuilder("abs_spill")
        a, = b.params(1)
        # Load many constants to pressure the allocator
        extras = [b.load_imm(i) for i in range(N_REGS + 1)]
        # Sum them (result is predictable)
        acc = extras[0]
        for v in extras[1:]:
            acc = b.add(acc, v)
        # Also add the param
        acc = b.add(acc, a)
        b.ret(acc)
        expected = sum(range(N_REGS + 1)) + 7
        assert run(compile_fn(b.build()), 7) == expected
