"""
Tests for let bindings.

Covers:
  - Parser: (let ((x e)) body), multiple bindings, nesting, shadowing
  - BURG: rule 11 (Let) and rule 12 (Var), scope management
  - Full pipeline: compile and execute
  - compile_and_run: S-expression interface
  - Interaction with if, arithmetic, and REPL bindings
"""
import ctypes
import sys
import pytest

from flux.core.tree      import Const, Arg, Add, Mul, Let, Var, If, Lt
from flux.core.builder   import FunctionBuilder
from flux.core.burg      import BurgSelector, NT
from flux.core.parser    import parse_expr
from flux.core.compiler  import compile_and_run
from flux.targets.x86_64.emitter  import X86_64Emitter
from flux.targets.x86_64.targets  import WINDOWS, LINUX
from flux.core.linear_scan import LinearScanAllocator

from tests.jit import make_callable, free_code

TARGET = WINDOWS if sys.platform == "win32" else LINUX


def run_tree(n_params, expr, *args):
    """Compile and execute a tree expression."""
    builder  = FunctionBuilder("f")
    params   = builder.params(n_params)
    selector = BurgSelector(params, builder)
    result   = selector.select(expr)
    builder.ret(result)
    fn       = builder.build()
    emitter  = X86_64Emitter(TARGET)
    LinearScanAllocator(TARGET).allocate(fn, emitter)
    code = emitter.get_code()
    argtypes = [ctypes.c_int64] * len(args)
    func, handle = make_callable(code, ctypes.c_int64, *argtypes)
    value = func(*args)
    free_code(handle)
    return value


# ------------------------------------------------------------------
# Parser tests
# ------------------------------------------------------------------

class TestParser:

    def test_single_binding(self):
        expr = parse_expr("(let ((x 5)) x)")
        assert expr == Let("x", Const(5), Var("x"))

    def test_body_uses_binding(self):
        expr = parse_expr("(let ((x 3)) (* x x))")
        assert expr == Let("x", Const(3), Mul(Var("x"), Var("x")))

    def test_multiple_bindings_desugar_to_nested(self):
        expr = parse_expr("(let ((x 3) (y 4)) (+ x y))")
        assert expr == Let("x", Const(3),
                       Let("y", Const(4),
                       Add(Var("x"), Var("y"))))

    def test_let_with_arg(self):
        expr = parse_expr("(let ((y 1)) (+ x y))", args=["x"])
        assert expr == Let("y", Const(1), Add(Arg(0), Var("y")))

    def test_nested_let(self):
        expr = parse_expr("(let ((x 3)) (let ((y (* x x))) y))")
        assert expr == Let("x", Const(3),
                       Let("y", Mul(Var("x"), Var("x")),
                       Var("y")))

    def test_let_binding_shadows_arg(self):
        # x is an arg, but let re-binds it; body should see Var("x")
        expr = parse_expr("(let ((x 10)) (* x 2))", args=["x"])
        assert isinstance(expr, Let)
        assert expr.name == "x"
        assert expr.value == Const(10)
        # body uses Var("x"), not Arg(0)
        assert expr.body == Mul(Var("x"), Const(2))

    def test_missing_binding_list_raises(self):
        with pytest.raises(ValueError, match="binding list"):
            parse_expr("(let x 5)")

    def test_missing_body_raises(self):
        # (let ((x 5))) has no body — the closing ) is hit while parsing body
        with pytest.raises(ValueError):
            parse_expr("(let ((x 5)))")

    def test_empty_bindings_with_body(self):
        # (let () body) — no bindings, just evaluate body
        expr = parse_expr("(let () 42)")
        assert expr == Const(42)

    def test_invalid_binding_name_raises(self):
        with pytest.raises(ValueError, match="Invalid binding name"):
            parse_expr("(let ((+ 5)) 1)")


# ------------------------------------------------------------------
# BURG tests
# ------------------------------------------------------------------

class TestBURG:

    def _label(self, n_params, expr):
        b = FunctionBuilder("f")
        p = b.params(n_params)
        s = BurgSelector(p, b)
        return s._label(expr)

    def test_var_reachable_as_reg(self):
        # Var is always REG with cost 0 (scope check happens at reduction)
        state = self._label(0, Var("x"))
        assert state[NT.REG].cost == 0
        assert state[NT.REG].rule_id == 12

    def test_let_reachable_as_reg(self):
        expr  = Let("x", Const(5), Var("x"))
        state = self._label(0, expr)
        assert state[NT.REG].cost < float('inf')
        assert state[NT.REG].rule_id == 11

    def test_let_cost_is_sum_of_parts(self):
        # Let cost = value[REG].cost + body[REG].cost
        # Const(5) as REG costs 1 (load_imm); Var("x") as REG costs 0
        expr  = Let("x", Const(5), Var("x"))
        state = self._label(0, expr)
        assert state[NT.REG].cost == 1    # 1 (load_imm) + 0 (var lookup)

    def test_unbound_var_raises_at_reduction(self):
        # Must reuse the same node object: cache is keyed by id(node).
        b    = FunctionBuilder("f")
        s    = BurgSelector([], b)
        node = Var("z")
        s._label(node)   # labeling succeeds
        with pytest.raises(RuntimeError, match="Unbound variable"):
            s._reduce(node, NT.REG)   # reduction fails (not in scope)

    def test_scope_restored_after_let(self):
        # After reducing a Let, the name is no longer in scope.
        b    = FunctionBuilder("f")
        s    = BurgSelector([], b)
        expr = Let("x", Const(1), Var("x"))  # reuse same object
        s._label(expr)
        s._reduce(expr, NT.REG)
        assert "x" not in s.scope

    def test_shadowing_restores_outer(self):
        # Outer x=1, inner let re-binds x=2, outer x restored after.
        b   = FunctionBuilder("f")
        p   = b.params(1)
        s   = BurgSelector(p, b)
        s.scope["x"] = p[0]  # simulate outer binding

        inner = Let("x", Const(2), Var("x"))
        s._label(inner)
        result = s._reduce(inner, NT.REG)
        assert isinstance(result, type(p[0]))
        # After reduction, outer binding is restored
        assert s.scope["x"] == p[0]


# ------------------------------------------------------------------
# Execution tests
# ------------------------------------------------------------------

class TestExecution:

    def test_simple_let(self):
        expr = Let("x", Const(42), Var("x"))
        assert run_tree(0, expr) == 42

    def test_let_arithmetic(self):
        # (let ((x 6)) (* x 7))
        expr = Let("x", Const(6), Mul(Var("x"), Const(7)))
        assert run_tree(0, expr) == 42

    def test_let_with_arg(self):
        # (let ((y 1)) (+ a y))  with a=41
        expr = Let("y", Const(1), Add(Arg(0), Var("y")))
        assert run_tree(1, expr, 41) == 42

    def test_multiple_bindings(self):
        # (let ((x 6) (y 7)) (* x y))
        expr = Let("x", Const(6), Let("y", Const(7), Mul(Var("x"), Var("y"))))
        assert run_tree(0, expr) == 42

    def test_nested_let(self):
        # (let ((x 3)) (let ((y (* x x))) (+ x y))) = 3 + 9 = 12
        expr = Let("x", Const(3),
               Let("y", Mul(Var("x"), Var("x")),
               Add(Var("x"), Var("y"))))
        assert run_tree(0, expr) == 12

    def test_let_used_multiple_times(self):
        # (let ((x 21)) (+ x x)) = 42
        expr = Let("x", Const(21), Add(Var("x"), Var("x")))
        assert run_tree(0, expr) == 42

    def test_let_in_conditional(self):
        # (let ((abs_x (if (< a 0) (* a -1) a))) abs_x)  with a=-42
        expr = Let("abs_x",
                   If(Lt(Arg(0), Const(0)), Mul(Arg(0), Const(-1)), Arg(0)),
                   Var("abs_x"))
        assert run_tree(1, expr, -42) == 42
        assert run_tree(1, expr,  42) == 42

    def test_let_shadows_arg(self):
        # Arg(0) = 99, but let re-binds x to 42; body should return 42
        # (let ((x 42)) x)  with x=99 as arg
        b = FunctionBuilder("f")
        p = b.params(1)   # arg x=99
        s = BurgSelector(p, b)
        # Body: just returns the let-bound x (Var), not the arg
        expr = Let("x", Const(42), Var("x"))
        s._label(expr)
        result_vreg = s._reduce(expr, NT.REG)
        b.ret(result_vreg)
        fn = b.build()
        emitter = X86_64Emitter(TARGET)
        LinearScanAllocator(TARGET).allocate(fn, emitter)
        code = emitter.get_code()
        func, handle = make_callable(code, ctypes.c_int64, ctypes.c_int64)
        value = func(99)
        free_code(handle)
        assert value == 42


# ------------------------------------------------------------------
# compile_and_run interface
# ------------------------------------------------------------------

class TestCompileAndRun:

    def test_simple_let(self):
        assert compile_and_run("(let ((x 6)) (* x 7))") == 42

    def test_multiple_bindings(self):
        assert compile_and_run("(let ((x 6) (y 7)) (* x y))") == 42

    def test_nested_let(self):
        assert compile_and_run(
            "(let ((x 3)) (let ((y (* x x))) (+ x y)))"
        ) == 12

    def test_let_with_arg(self):
        assert compile_and_run("(let ((y 10)) (+ a y))", a=32) == 42

    def test_let_used_multiple_times(self):
        # Verifies the bound VReg stays alive across multiple uses.
        assert compile_and_run("(let ((x 21)) (+ x x))") == 42

    def test_let_in_if(self):
        assert compile_and_run(
            "(if (< x 0) (let ((neg (* x -1))) neg) x)", x=-42
        ) == 42

    def test_if_in_let_value(self):
        assert compile_and_run(
            "(let ((abs_x (if (< x 0) (* x -1) x))) abs_x)", x=-7
        ) == 7

    def test_complex_let(self):
        # hypotenuse-squared: a² + b²
        assert compile_and_run(
            "(let ((a2 (* a a)) (b2 (* b b))) (+ a2 b2))", a=3, b=4
        ) == 25

    def test_let_forces_evaluation_order(self):
        # Each binding is evaluated in order; y can use x
        assert compile_and_run(
            "(let ((x 6) (y (* x 7))) y)", x=0
        ) == 42   # y = (let-x=6) * 7 = 42, not (repl-x=0) * 7
