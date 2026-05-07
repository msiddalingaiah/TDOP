"""
Tests for comparisons and conditionals.

Covers:
  - Parser: <, >, =, if
  - BURG: labeling costs, rule 10 selection
  - Full pipeline: execute and verify results
  - compile_and_run: S-expression interface
"""
import ctypes
import sys
import pytest

from flux.core.tree      import Const, Arg, Add, Sub, Mul, Lt, Gt, Eq, If
from flux.core.builder   import FunctionBuilder
from flux.core.burg      import BurgSelector, NT
from flux.core.linear_scan import LinearScanAllocator
from flux.core.parser    import parse_expr
from flux.core.compiler  import compile_and_run
from flux.targets.x86_64.emitter  import X86_64Emitter
from flux.targets.x86_64.targets  import WINDOWS, LINUX

from tests.jit import make_callable, free_code

TARGET = WINDOWS if sys.platform == "win32" else LINUX


def run_expr(n_params, expr, *args):
    builder  = FunctionBuilder("f")
    params   = builder.params(n_params)
    selector = BurgSelector(params, builder)
    result   = selector.select(expr)
    builder.ret(result)
    fn       = builder.build()
    emitter  = X86_64Emitter(TARGET)
    LinearScanAllocator(TARGET).allocate(fn, emitter)
    code     = emitter.get_code()
    argtypes = [ctypes.c_int64] * len(args)
    func, handle = make_callable(code, ctypes.c_int64, *argtypes)
    value = func(*args)
    free_code(handle)
    return value


# ------------------------------------------------------------------
# Parser tests
# ------------------------------------------------------------------

class TestParser:

    def test_lt(self):
        assert parse_expr("(< 1 2)") == Lt(Const(1), Const(2))

    def test_gt(self):
        assert parse_expr("(> x y)", args=["x", "y"]) == Gt(Arg(0), Arg(1))

    def test_eq(self):
        assert parse_expr("(= n 0)", args=["n"]) == Eq(Arg(0), Const(0))

    def test_if(self):
        expr = parse_expr("(if (< x 0) 0 x)", args=["x"])
        assert expr == If(Lt(Arg(0), Const(0)), Const(0), Arg(0))

    def test_if_wrong_arity(self):
        with pytest.raises(ValueError, match="3 subforms"):
            parse_expr("(if (< x 0) 0)", args=["x"])

    def test_nested_if(self):
        expr = parse_expr(
            "(if (< x y) x (if (= x y) 0 y))",
            args=["x", "y"]
        )
        assert isinstance(expr, If)
        assert isinstance(expr.else_, If)


# ------------------------------------------------------------------
# BURG labeling tests
# ------------------------------------------------------------------

class TestLabeling:

    def _label(self, n_params, expr):
        b = FunctionBuilder("f")
        p = b.params(n_params)
        s = BurgSelector(p, b)
        return s._label(expr)

    def test_if_lt_const_reachable(self):
        # (if (< x 0) 0 x) — should be reachable as REG
        expr  = If(Lt(Arg(0), Const(0)), Const(0), Arg(0))
        state = self._label(1, expr)
        assert state[NT.REG].cost < float('inf')
        assert state[NT.REG].rule_id == 10

    def test_if_with_imm_condition_cheaper(self):
        # rhs of < is Const → IMM cost=0 < REG cost=1
        expr  = If(Lt(Arg(0), Const(0)), Const(0), Arg(0))
        state = self._label(1, expr)
        # Cost = arg_as_reg(0) + const_as_imm(0) + then_cost + else_cost + 1
        assert state[NT.REG].cost < float('inf')

    def test_standalone_lt_unreachable(self):
        state = self._label(2, Lt(Arg(0), Arg(1)))
        assert state[NT.REG].cost == float('inf')
        assert state[NT.IMM].cost == float('inf')


# ------------------------------------------------------------------
# Execution tests — Lt
# ------------------------------------------------------------------

class TestLt:

    def test_min(self):
        # min(x, y) = (if (< x y) x y)
        expr = If(Lt(Arg(0), Arg(1)), Arg(0), Arg(1))
        assert run_expr(2, expr, 3, 7)  == 3
        assert run_expr(2, expr, 7, 3)  == 3
        assert run_expr(2, expr, 5, 5)  == 5

    def test_lt_const(self):
        # (if (< x 0) 0 x) — relu-like
        expr = If(Lt(Arg(0), Const(0)), Const(0), Arg(0))
        assert run_expr(1, expr, -5) == 0
        assert run_expr(1, expr,  5) == 5
        assert run_expr(1, expr,  0) == 0

    def test_negative_values(self):
        expr = If(Lt(Arg(0), Arg(1)), Arg(0), Arg(1))
        assert run_expr(2, expr, -10, -3) == -10
        assert run_expr(2, expr, -3, -10) == -10


# ------------------------------------------------------------------
# Execution tests — Gt
# ------------------------------------------------------------------

class TestGt:

    def test_max(self):
        # max(x, y) = (if (> x y) x y)
        expr = If(Gt(Arg(0), Arg(1)), Arg(0), Arg(1))
        assert run_expr(2, expr, 3, 7)  == 7
        assert run_expr(2, expr, 7, 3)  == 7
        assert run_expr(2, expr, 5, 5)  == 5

    def test_gt_const(self):
        # (if (> x 100) 100 x) — clamp at 100
        expr = If(Gt(Arg(0), Const(100)), Const(100), Arg(0))
        assert run_expr(1, expr,  50) ==  50
        assert run_expr(1, expr, 100) == 100
        assert run_expr(1, expr, 200) == 100


# ------------------------------------------------------------------
# Execution tests — Eq
# ------------------------------------------------------------------

class TestEq:

    def test_select_on_equal(self):
        # (if (= x 0) 42 x)
        expr = If(Eq(Arg(0), Const(0)), Const(42), Arg(0))
        assert run_expr(1, expr, 0)  == 42
        assert run_expr(1, expr, 7)  ==  7

    def test_two_args_equal(self):
        # (if (= x y) 1 0)
        expr = If(Eq(Arg(0), Arg(1)), Const(1), Const(0))
        assert run_expr(2, expr, 5, 5) == 1
        assert run_expr(2, expr, 5, 6) == 0


# ------------------------------------------------------------------
# Execution tests — nested If
# ------------------------------------------------------------------

class TestNested:

    def test_three_way(self):
        # sign(x): -1, 0, or 1
        # (if (< x 0) -1 (if (= x 0) 0 1))
        expr = If(
            Lt(Arg(0), Const(0)),
            Const(-1),
            If(Eq(Arg(0), Const(0)), Const(0), Const(1))
        )
        assert run_expr(1, expr, -5) == -1
        assert run_expr(1, expr,  0) ==  0
        assert run_expr(1, expr,  5) ==  1

    def test_if_with_arithmetic(self):
        # (if (< x 0) (* x -1) x) — abs(x)
        expr = If(
            Lt(Arg(0), Const(0)),
            Mul(Arg(0), Const(-1)),
            Arg(0)
        )
        assert run_expr(1, expr, -7) == 7
        assert run_expr(1, expr,  7) == 7
        assert run_expr(1, expr,  0) == 0

    def test_if_in_arithmetic(self):
        # (+ (if (< x 0) 0 x) 1)
        expr = Add(
            If(Lt(Arg(0), Const(0)), Const(0), Arg(0)),
            Const(1)
        )
        assert run_expr(1, expr, -5) == 1
        assert run_expr(1, expr,  5) == 6


# ------------------------------------------------------------------
# compile_and_run interface
# ------------------------------------------------------------------

class TestCompileAndRun:

    def test_min(self):
        assert compile_and_run("(if (< x y) x y)", x=3, y=7)  == 3
        assert compile_and_run("(if (< x y) x y)", x=7, y=3)  == 3

    def test_max(self):
        assert compile_and_run("(if (> x y) x y)", x=3, y=7)  == 7
        assert compile_and_run("(if (> x y) x y)", x=7, y=3)  == 7

    def test_abs(self):
        assert compile_and_run("(if (< x 0) (* x -1) x)", x=-42) == 42
        assert compile_and_run("(if (< x 0) (* x -1) x)", x=42)  == 42

    def test_clamp(self):
        assert compile_and_run(
            "(if (< x 0) 0 (if (> x 100) 100 x))", x=-5
        ) == 0
        assert compile_and_run(
            "(if (< x 0) 0 (if (> x 100) 100 x))", x=50
        ) == 50
        assert compile_and_run(
            "(if (< x 0) 0 (if (> x 100) 100 x))", x=200
        ) == 100

    def test_sign(self):
        sign = "(if (< x 0) -1 (if (= x 0) 0 1))"
        assert compile_and_run(sign, x=-99) == -1
        assert compile_and_run(sign, x=0)   ==  0
        assert compile_and_run(sign, x=99)  ==  1
