"""
Tests for the linear scan allocator.

Interval tests verify live range computation.
Reuse tests confirm that registers are reclaimed and reassigned.
Pipeline tests run the full stack end-to-end.
"""
import ctypes
import sys
import pytest

from flux.core.operands    import Imm
from flux.core.builder     import FunctionBuilder
from flux.core.linear_scan import LinearScanAllocator, LiveInterval, compute_intervals
from flux.core.ir          import VReg
from flux.targets.x86_64.emitter import X86_64Emitter
from flux.targets.x86_64.targets import WINDOWS, LINUX

from tests.jit import make_callable, free_code

TARGET = WINDOWS if sys.platform == "win32" else LINUX


def compile_fn(fn):
    emitter   = X86_64Emitter(TARGET)
    allocator = LinearScanAllocator(TARGET)
    allocator.allocate(fn, emitter)
    return emitter.get_code()


def run(code, *args, restype=ctypes.c_int64):
    argtypes = [ctypes.c_int64] * len(args)
    func, handle = make_callable(code, restype, *argtypes)
    result = func(*args)
    free_code(handle)
    return result


# ------------------------------------------------------------------
# Live interval tests
# ------------------------------------------------------------------

class TestIntervals:

    def _intervals(self, n_params, *ops):
        """Build a minimal function and return its computed intervals."""
        b = FunctionBuilder("f")
        params = b.params(n_params)
        result = ops[0](b, params) if ops else params[0]
        b.ret(result)
        return compute_intervals(b.build()), params

    def test_param_starts_before_zero(self):
        b = FunctionBuilder("f")
        p, = b.params(1)
        b.ret(p)
        ivs, _ = compute_intervals(b.build()), [p]
        assert ivs[p].start == -1

    def test_param_end_extended_to_last_use(self):
        # f(a, b) = a + b
        # Both params used at instruction 0 (the add).
        b = FunctionBuilder("f")
        a, x = b.params(2)
        r = b.add(a, x)
        b.ret(r)
        ivs = compute_intervals(b.build())
        assert ivs[a].end == 0   # used at ADD (pos 0)
        assert ivs[x].end == 0

    def test_result_interval_starts_at_definition(self):
        b = FunctionBuilder("f")
        a, x = b.params(2)
        r = b.add(a, x)   # pos 0
        b.ret(r)
        ivs = compute_intervals(b.build())
        assert ivs[r].start == 0

    def test_result_end_extended_to_ret(self):
        b = FunctionBuilder("f")
        a, x = b.params(2)
        r = b.add(a, x)   # pos 0 — r defined here
        b.ret(r)           # pos 1 — r used here
        ivs = compute_intervals(b.build())
        assert ivs[r].end == 1

    def test_chained_intervals(self):
        # f(a, b, c) = (a + b) - c
        # %0=a, %1=b, %2=c params
        # pos 0: %3 = add %0, %1   → %0 ends 0, %1 ends 0, %3 starts 0
        # pos 1: %4 = sub %3, %2   → %3 ends 1, %2 ends 1, %4 starts 1
        # pos 2: ret %4             → %4 ends 2
        b = FunctionBuilder("f")
        a, x, c = b.params(3)
        t = b.add(a, x)
        r = b.sub(t, c)
        b.ret(r)
        ivs = compute_intervals(b.build())

        assert ivs[a].end == 0
        assert ivs[x].end == 0
        assert ivs[c].end == 1
        assert ivs[t].start == 0 and ivs[t].end == 1
        assert ivs[r].start == 1 and ivs[r].end == 2


# ------------------------------------------------------------------
# Register reuse tests
# ------------------------------------------------------------------

class TestRegisterReuse:

    def test_expired_param_register_is_reused(self):
        # f(a, b, c) = (a + b) - c
        # After pos 0, %0 and %1 are dead. Their arg registers should
        # become available for later results.
        b = FunctionBuilder("f")
        a, x, c = b.params(3)
        t = b.add(a, x)   # %3: a and x die here
        r = b.sub(t, c)
        b.ret(r)
        fn = b.build()

        alloc = LinearScanAllocator(TARGET)._build_allocation(fn)

        param_regs  = set(alloc[p] for p in [a, x, c])
        result_regs = set(alloc[v] for v in [t, r])

        # At least one result register must be a reused param register.
        assert result_regs & param_regs, (
            "Expected linear scan to reuse at least one expired param register"
        )

    def test_all_vregs_get_distinct_registers_at_their_live_point(self):
        # Verifies no two simultaneously-live VRegs share a register.
        # f(a, b) = (a + b) + (a + b)  — two independent adds
        b = FunctionBuilder("f")
        a, x = b.params(2)
        t1 = b.add(a, x)   # pos 0
        t2 = b.add(a, x)   # pos 1  ← a and x still live here
        r  = b.add(t1, t2) # pos 2
        b.ret(r)
        fn = b.build()

        alloc = LinearScanAllocator(TARGET)._build_allocation(fn)
        ivs   = compute_intervals(fn)

        # At each instruction position, collect live VRegs and check
        # their assigned registers are all distinct.
        all_vregs = list(ivs.keys())
        n_instrs  = sum(len(blk.instrs) for blk in fn.blocks)

        for pos in range(n_instrs):
            live_regs = [alloc[v] for v in all_vregs
                         if ivs[v].start <= pos <= ivs[v].end]
            assert len(live_regs) == len(set(live_regs)), (
                f"Register conflict at position {pos}: {live_regs}"
            )


# ------------------------------------------------------------------
# Full pipeline execution tests
# ------------------------------------------------------------------

class TestPipeline:

    def test_return_constant(self):
        b = FunctionBuilder("f")
        v = b.load_imm(42)
        b.ret(v)
        assert run(compile_fn(b.build())) == 42

    def test_return_negative(self):
        b = FunctionBuilder("f")
        v = b.load_imm(-7)
        b.ret(v)
        assert run(compile_fn(b.build())) == -7

    def test_identity(self):
        b = FunctionBuilder("f")
        a, = b.params(1)
        b.ret(a)
        assert run(compile_fn(b.build()), 99) == 99

    def test_add_two_args(self):
        b = FunctionBuilder("f")
        a, x = b.params(2)
        r = b.add(a, x)
        b.ret(r)
        assert run(compile_fn(b.build()), 10, 32) == 42

    def test_sub_two_args(self):
        b = FunctionBuilder("f")
        a, x = b.params(2)
        r = b.sub(a, x)
        b.ret(r)
        assert run(compile_fn(b.build()), 50, 8) == 42

    def test_add_immediate(self):
        b = FunctionBuilder("f")
        a, = b.params(1)
        r = b.add(a, Imm(1))
        b.ret(r)
        assert run(compile_fn(b.build()), 41) == 42

    def test_chained_operations(self):
        b = FunctionBuilder("f")
        a, x, c = b.params(3)
        t = b.add(a, x)
        r = b.sub(t, c)
        b.ret(r)
        assert run(compile_fn(b.build()), 20, 30, 8) == 42

    def test_deeper_chain(self):
        # f(a, b, c, d) = (a + b) + (c - d)
        b = FunctionBuilder("f")
        a, x, c, d = b.params(4)
        t1 = b.add(a, x)
        t2 = b.sub(c, d)
        r  = b.add(t1, t2)
        b.ret(r)
        assert run(compile_fn(b.build()), 10, 20, 15, 3) == 42
