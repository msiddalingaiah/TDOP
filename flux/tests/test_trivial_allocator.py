"""
Tests for the trivial register allocator.

Allocation tests verify the VReg → physical register mapping.
Pipeline tests exercise the full path: FunctionBuilder → TrivialAllocator
→ X86_64Emitter → execute in memory.
"""
import ctypes
import sys
import pytest

from flux.core.operands          import Imm
from flux.core.builder           import FunctionBuilder
from flux.core.trivial_allocator import TrivialAllocator
from flux.targets.x86_64.emitter import X86_64Emitter
from flux.targets.x86_64         import regs
from flux.targets.x86_64.targets import WINDOWS, LINUX

from tests.jit import make_callable, free_code

TARGET = WINDOWS if sys.platform == "win32" else LINUX


def compile_fn(fn):
    """Compile a Function to bytes using the trivial allocator."""
    emitter   = X86_64Emitter(TARGET)
    allocator = TrivialAllocator(TARGET)
    allocator.allocate(fn, emitter)
    return emitter.get_code()


def run(code, *args, restype=ctypes.c_int64):
    argtypes = [ctypes.c_int64] * len(args)
    func, handle = make_callable(code, restype, *argtypes)
    result = func(*args)
    free_code(handle)
    return result


# ------------------------------------------------------------------
# Allocation tests
# ------------------------------------------------------------------

class TestAllocation:

    def _alloc(self, fn):
        return TrivialAllocator(TARGET)._build_allocation(fn)

    def test_params_pinned_to_arg_registers(self):
        b = FunctionBuilder("f")
        a, x = b.params(2)
        b.ret(a)
        fn = b.build()

        alloc = self._alloc(fn)
        assert alloc[a] == TARGET.arg_registers[0]
        assert alloc[x] == TARGET.arg_registers[1]

    def test_result_vreg_gets_distinct_register(self):
        b = FunctionBuilder("f")
        a, x = b.params(2)
        r = b.add(a, x)
        b.ret(r)
        fn = b.build()

        alloc = self._alloc(fn)
        assert alloc[r] not in (alloc[a], alloc[x])

    def test_too_many_params_raises(self):
        b = FunctionBuilder("f")
        b.params(len(TARGET.arg_registers) + 1)
        v = b.load_imm(0)
        b.ret(v)
        fn = b.build()

        with pytest.raises(RuntimeError, match="argument registers"):
            TrivialAllocator(TARGET)._build_allocation(fn)


# ------------------------------------------------------------------
# Full pipeline execution tests
# ------------------------------------------------------------------

class TestPipeline:

    def test_return_constant(self):
        b = FunctionBuilder("const")
        v = b.load_imm(42)
        b.ret(v)
        assert run(compile_fn(b.build())) == 42

    def test_return_negative_constant(self):
        b = FunctionBuilder("neg")
        v = b.load_imm(-7)
        b.ret(v)
        assert run(compile_fn(b.build())) == -7

    def test_identity(self):
        b = FunctionBuilder("id")
        a, = b.params(1)
        b.ret(a)
        assert run(compile_fn(b.build()), 99) == 99

    def test_add_two_args(self):
        b = FunctionBuilder("add")
        a, x = b.params(2)
        r = b.add(a, x)
        b.ret(r)
        assert run(compile_fn(b.build()), 10, 32) == 42

    def test_sub_two_args(self):
        b = FunctionBuilder("sub")
        a, x = b.params(2)
        r = b.sub(a, x)
        b.ret(r)
        assert run(compile_fn(b.build()), 50, 8) == 42

    def test_add_immediate(self):
        b = FunctionBuilder("inc")
        a, = b.params(1)
        r = b.add(a, Imm(1))
        b.ret(r)
        assert run(compile_fn(b.build()), 41) == 42

    def test_sub_immediate(self):
        b = FunctionBuilder("dec")
        a, = b.params(1)
        r = b.sub(a, Imm(1))
        b.ret(r)
        assert run(compile_fn(b.build()), 43) == 42

    def test_chained_operations(self):
        # f(a, b, c) = (a + b) - c
        b = FunctionBuilder("chain")
        a, x, c = b.params(3)
        t = b.add(a, x)
        r = b.sub(t, c)
        b.ret(r)
        assert run(compile_fn(b.build()), 20, 30, 8) == 42

    def test_move(self):
        b = FunctionBuilder("copy")
        a, = b.params(1)
        c = b.move(a)
        b.ret(c)
        assert run(compile_fn(b.build()), 42) == 42
