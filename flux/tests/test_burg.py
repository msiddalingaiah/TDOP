"""
Tests for the BURG instruction selector.

Labeling tests verify costs and rule selection without executing code.
Pipeline tests exercise the full path:
    Expr tree → BurgSelector → FunctionBuilder → TrivialAllocator
              → X86_64Emitter → execute in memory.
"""
import ctypes
import sys
import pytest

from flux.core.operands          import Imm
from flux.core.builder           import FunctionBuilder
from flux.core.burg              import BurgSelector, NT, INF
from flux.core.trivial_allocator import TrivialAllocator
from flux.core.tree              import Const, Arg, Add, Sub
from flux.targets.x86_64.emitter import X86_64Emitter
from flux.targets.x86_64.targets import WINDOWS, LINUX

from tests.jit import make_callable, free_code

TARGET = WINDOWS if sys.platform == "win32" else LINUX


def make_selector(n_params: int):
    """Return a (selector, builder, params) tuple ready for use."""
    builder  = FunctionBuilder("f")
    params   = builder.params(n_params)
    selector = BurgSelector(params, builder)
    return selector, builder, params


def compile_expr(n_params: int, expr) -> bytes:
    """Compile an Expr tree to executable bytes."""
    selector, builder, _ = make_selector(n_params)
    result = selector.select(expr)
    builder.ret(result)
    fn      = builder.build()
    emitter = X86_64Emitter(TARGET)
    TrivialAllocator(TARGET).allocate(fn, emitter)
    return emitter.get_code()


def run(code, *args, restype=ctypes.c_int64):
    argtypes = [ctypes.c_int64] * len(args)
    func, handle = make_callable(code, restype, *argtypes)
    result = func(*args)
    free_code(handle)
    return result


# ------------------------------------------------------------------
# Labeling tests — verify DP costs and rule selection
# ------------------------------------------------------------------

class TestLabeling:

    def _label(self, n_params, expr):
        selector, _, _ = make_selector(n_params)
        return selector._label(expr)

    def test_const_imm_cost_zero(self):
        state = self._label(0, Const(42))
        assert state[NT.IMM].cost == 0
        assert state[NT.IMM].rule_id == 1

    def test_const_reg_cost_one(self):
        state = self._label(0, Const(42))
        assert state[NT.REG].cost == 1
        assert state[NT.REG].rule_id == 2

    def test_arg_reg_cost_zero(self):
        state = self._label(1, Arg(0))
        assert state[NT.REG].cost == 0
        assert state[NT.REG].rule_id == 3

    def test_arg_imm_unreachable(self):
        state = self._label(1, Arg(0))
        assert state[NT.IMM].cost == INF

    def test_add_arg_arg_selects_reg_reg(self):
        # Add(Arg, Arg): rhs cannot be imm → must use rule 4 (reg+reg)
        state = self._label(2, Add(Arg(0), Arg(1)))
        assert state[NT.REG].rule_id == 4
        assert state[NT.REG].cost == 1   # 0 + 0 + 1

    def test_add_arg_const_selects_reg_imm(self):
        # Add(Arg, Const): imm cheaper than reg for Const → rule 5 wins
        state = self._label(1, Add(Arg(0), Const(1)))
        assert state[NT.REG].rule_id == 5
        assert state[NT.REG].cost == 1   # 0 + 0 + 1

    def test_add_arg_const_cheaper_than_reg_reg(self):
        # rule 5 cost (1) < rule 4 cost (2) when rhs is Const
        state = self._label(1, Add(Arg(0), Const(1)))
        cost_reg_reg = 0 + 1 + 1   # lhs=0, rhs as reg=1, base=1
        cost_reg_imm = 0 + 0 + 1   # lhs=0, rhs as imm=0, base=1
        assert state[NT.REG].cost == cost_reg_imm
        assert cost_reg_imm < cost_reg_reg

    def test_sub_arg_arg_selects_reg_reg(self):
        state = self._label(2, Sub(Arg(0), Arg(1)))
        assert state[NT.REG].rule_id == 6

    def test_sub_arg_const_selects_reg_imm(self):
        state = self._label(1, Sub(Arg(0), Const(1)))
        assert state[NT.REG].rule_id == 7


# ------------------------------------------------------------------
# Full pipeline execution tests
# ------------------------------------------------------------------

class TestPipeline:

    def test_constant(self):
        assert run(compile_expr(0, Const(42))) == 42

    def test_negative_constant(self):
        assert run(compile_expr(0, Const(-7))) == -7

    def test_identity(self):
        assert run(compile_expr(1, Arg(0)), 99) == 99

    def test_add_two_args(self):
        assert run(compile_expr(2, Add(Arg(0), Arg(1))), 10, 32) == 42

    def test_add_arg_and_const(self):
        assert run(compile_expr(1, Add(Arg(0), Const(1))), 41) == 42

    def test_sub_two_args(self):
        assert run(compile_expr(2, Sub(Arg(0), Arg(1))), 50, 8) == 42

    def test_sub_arg_and_const(self):
        assert run(compile_expr(1, Sub(Arg(0), Const(1))), 43) == 42

    def test_nested_add(self):
        # (a + b) + c
        expr = Add(Add(Arg(0), Arg(1)), Arg(2))
        assert run(compile_expr(3, expr), 10, 20, 12) == 42

    def test_mixed_nested(self):
        # (a + b) - c
        expr = Sub(Add(Arg(0), Arg(1)), Arg(2))
        assert run(compile_expr(3, expr), 20, 30, 8) == 42

    def test_const_rhs_uses_imm_encoding(self):
        # Verify the IR contains an ADD with an Imm operand, not a loaded reg.
        from flux.core.ir import Opcode
        builder  = FunctionBuilder("f")
        params   = builder.params(1)
        selector = BurgSelector(params, builder)
        result   = selector.select(Add(Arg(0), Const(10)))
        builder.ret(result)
        fn = builder.build()

        add_instr = fn.blocks[0].instrs[0]
        assert add_instr.opcode == Opcode.ADD
        assert add_instr.operands[1] == Imm(10)
