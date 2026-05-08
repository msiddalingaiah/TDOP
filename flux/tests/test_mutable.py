"""
Tests for mutable variables: (var x init body), (set! x expr), (begin e1 e2).

Coverage
--------
Parser    — var, set!, begin syntax and error cases
IR        — LOAD_VAR and STORE_VAR instructions, MutableVar operand
BURG      — rules 13/14/15, mut_scope management
Allocator — frame layout with mutable vars, spill slot offset coordination
Execution — compile and run via compile_and_run and direct tree API
"""
import ctypes
import sys
import pytest

from flux.core.tree      import Const, Arg, Add, Sub, Mul, If, Lt, Let, Var
from flux.core.tree      import MutVar, SetBang, Begin
from flux.core.builder   import FunctionBuilder
from flux.core.burg      import BurgSelector
from flux.core.ir        import Opcode
from flux.core.operands  import MutableVar, SpillSlot
from flux.core.parser    import parse_expr
from flux.core.compiler  import compile_and_run
from flux.core.linear_scan import LinearScanAllocator

from flux.targets.x86_64.emitter  import X86_64Emitter
from flux.targets.x86_64.targets  import WINDOWS, LINUX

from tests.jit import make_callable, free_code

TARGET = WINDOWS if sys.platform == "win32" else LINUX


def run_tree(n_params, expr, *args):
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

    def test_var_single(self):
        expr = parse_expr("(var x 5 x)")
        assert expr == MutVar("x", Const(5), Var("x"))

    def test_set_bang(self):
        expr = parse_expr("(var x 0 (set! x 42))")
        assert expr == MutVar("x", Const(0), SetBang("x", Const(42)))

    def test_begin(self):
        expr = parse_expr("(begin 1 2)")
        assert expr == Begin(Const(1), Const(2))

    def test_var_with_set_and_begin(self):
        # (var x 0 (begin (set! x 42) x))
        expr = parse_expr("(var x 0 (begin (set! x 42) x))")
        assert expr == MutVar("x", Const(0),
                              Begin(SetBang("x", Const(42)), Var("x")))

    def test_set_bang_uses_new_value(self):
        # (var x 0 (set! x (+ x 1)))
        expr = parse_expr("(var x 0 (set! x (+ x 1)))")
        assert isinstance(expr, MutVar)
        assert isinstance(expr.body, SetBang)

    def test_var_excludes_name_from_args(self):
        # x is an arg, but var re-declares x as mutable in body
        expr = parse_expr("(var x 10 (* x 2))", args=["x"])
        assert isinstance(expr, MutVar)
        assert expr.name == "x"
        assert isinstance(expr.body, Mul)
        assert isinstance(expr.body.left, Var)   # Var, not Arg

    def test_var_missing_body_raises(self):
        with pytest.raises(ValueError):
            parse_expr("(var x 5)")

    def test_var_implicit_begin_two_exprs(self):
        # (var x 0 (set! x 42) x) → MutVar with Begin body
        expr = parse_expr("(var x 0 (set! x 42) x)")
        assert isinstance(expr, MutVar)
        assert isinstance(expr.body, Begin)
        assert expr.body.second == Var("x")

    def test_var_implicit_begin_three_exprs(self):
        # (var x 1 (set! x 2) (set! x 3) x)
        # → MutVar(Begin(set!2, Begin(set!3, x)))
        expr = parse_expr("(var x 1 (set! x 2) (set! x 3) x)")
        assert isinstance(expr, MutVar)
        assert isinstance(expr.body, Begin)
        assert isinstance(expr.body.second, Begin)

    def test_var_single_body_no_begin(self):
        # Single body expression — no Begin wrapper needed
        expr = parse_expr("(var x 42 x)")
        assert isinstance(expr, MutVar)
        assert expr.body == Var("x")   # not wrapped in Begin

    def test_set_bang_invalid_name_raises(self):
        with pytest.raises(ValueError, match="valid name"):
            parse_expr("(var x 0 (set! 123 1))")

    def test_begin_wrong_arity_raises(self):
        with pytest.raises(ValueError, match="exactly 2"):
            parse_expr("(begin 1 2 3)")


# ------------------------------------------------------------------
# IR structure tests
# ------------------------------------------------------------------

class TestIR:

    def test_alloc_mutable_var_slots(self):
        b = FunctionBuilder("f")
        v0 = b.alloc_mutable_var()
        v1 = b.alloc_mutable_var()
        assert v0.index == 0 and v0.offset == -8
        assert v1.index == 1 and v1.offset == -16

    def test_load_var_emits_load_var_opcode(self):
        b = FunctionBuilder("f")
        v = b.alloc_mutable_var()
        b.load_var(v)
        fn = b.build()
        instr = fn.blocks[0].instrs[0]
        assert instr.opcode == Opcode.LOAD_VAR
        assert instr.operands[0] == v

    def test_store_var_emits_store_var_opcode(self):
        b = FunctionBuilder("f")
        v   = b.alloc_mutable_var()
        imm = b.load_imm(42)
        b.store_var(v, imm)
        fn = b.build()
        store_instr = fn.blocks[0].instrs[1]
        assert store_instr.opcode    == Opcode.STORE_VAR
        assert store_instr.operands[0] == v
        assert store_instr.operands[1] == imm
        assert store_instr.result    is None

    def test_function_n_vars_count(self):
        b = FunctionBuilder("f")
        b.alloc_mutable_var()
        b.alloc_mutable_var()
        v = b.load_imm(0)
        b.ret(v)
        assert b.build().n_vars == 2


# ------------------------------------------------------------------
# Frame layout tests
# ------------------------------------------------------------------

class TestFrameLayout:

    def test_mutable_var_triggers_frame(self):
        b  = FunctionBuilder("f")
        sel = BurgSelector([], b)
        node = MutVar("x", Const(1), Var("x"))
        result = sel.select(node)
        b.ret(result)
        fn = b.build()
        assert fn.n_vars == 1

    def test_spill_slots_offset_below_var_area(self):
        """Spill slots must not overlap with mutable var slots."""
        N_REGS = len(TARGET.registers)
        b = FunctionBuilder("f")
        # Allocate one mutable var
        b.alloc_mutable_var()
        # Create enough VRegs to force spilling
        vals = [b.load_imm(i) for i in range(N_REGS + 1)]
        acc  = vals[0]
        for v in vals[1:]:
            acc = b.add(acc, v)
        b.ret(acc)
        fn = b.build()

        alloc = LinearScanAllocator(TARGET)._build_allocation(fn)
        spills = {v: loc for v, loc in alloc.items()
                  if isinstance(loc, SpillSlot)}

        for loc in spills.values():
            # Spill slots must be below the var area ([rbp - 8] is var 0)
            assert loc.offset < -(fn.n_vars * 8), (
                f"Spill slot {loc} overlaps with mutable var area "
                f"(n_vars={fn.n_vars})"
            )

    def test_frame_size_covers_both_vars_and_spills(self):
        N_REGS = len(TARGET.registers)
        b = FunctionBuilder("f")
        b.alloc_mutable_var()   # 1 var slot = 8 bytes
        vals = [b.load_imm(i) for i in range(N_REGS + 1)]
        acc = vals[0]
        for v in vals[1:]: acc = b.add(acc, v)
        b.ret(acc)
        fn = b.build()

        allocator = LinearScanAllocator(TARGET)
        allocator._build_allocation(fn)

        # Frame must include space for var (8 bytes) + spills
        assert allocator._frame_size >= 8 + 8   # at least 1 var + 1 spill
        assert allocator._frame_size % 16 == 0


# ------------------------------------------------------------------
# Execution tests
# ------------------------------------------------------------------

class TestExecution:

    def test_simple_var_read(self):
        # (var x 42 x) → 42
        expr = MutVar("x", Const(42), Var("x"))
        assert run_tree(0, expr) == 42

    def test_var_with_arithmetic(self):
        # (var x 6 (* x 7)) → 42
        expr = MutVar("x", Const(6), Mul(Var("x"), Const(7)))
        assert run_tree(0, expr) == 42

    def test_set_bang_updates_value(self):
        # (var x 0 (begin (set! x 42) x)) → 42
        expr = MutVar("x", Const(0),
                      Begin(SetBang("x", Const(42)), Var("x")))
        assert run_tree(0, expr) == 42

    def test_set_bang_uses_old_value(self):
        # (var x 21 (begin (set! x (* x 2)) x)) → 42
        expr = MutVar("x", Const(21),
                      Begin(SetBang("x", Mul(Var("x"), Const(2))),
                            Var("x")))
        assert run_tree(0, expr) == 42

    def test_multiple_mutations(self):
        # (var x 1
        #   (begin (set! x (* x 2))
        #   (begin (set! x (* x 3))
        #   (begin (set! x (* x 7))
        #          x))))
        # = 1 * 2 * 3 * 7 = 42
        expr = MutVar("x", Const(1),
               Begin(SetBang("x", Mul(Var("x"), Const(2))),
               Begin(SetBang("x", Mul(Var("x"), Const(3))),
               Begin(SetBang("x", Mul(Var("x"), Const(7))),
                     Var("x")))))
        assert run_tree(0, expr) == 42

    def test_two_mutable_vars(self):
        # (var a 6 (var b 7 (* a b))) → 42
        expr = MutVar("a", Const(6),
               MutVar("b", Const(7),
               Mul(Var("a"), Var("b"))))
        assert run_tree(0, expr) == 42

    def test_var_with_arg(self):
        # (var acc 0 (begin (set! acc (+ acc n)) acc))  n=42
        expr = MutVar("acc", Const(0),
               Begin(SetBang("acc", Add(Var("acc"), Arg(0))),
                     Var("acc")))
        assert run_tree(1, expr, 42) == 42

    def test_var_in_conditional(self):
        # (var result 0
        #   (begin
        #     (if (< x 0)
        #         (set! result (* x -1))
        #         (set! result x))
        #     result))   → abs(x)
        expr = MutVar("result", Const(0),
               Begin(If(Lt(Arg(0), Const(0)),
                        SetBang("result", Mul(Arg(0), Const(-1))),
                        SetBang("result", Arg(0))),
                     Var("result")))
        assert run_tree(1, expr, -42) == 42
        assert run_tree(1, expr,  42) == 42

    def test_begin_side_effects_discarded(self):
        # (begin (* 999 999) 42) → 42 (first expr computed but discarded)
        expr = Begin(Mul(Const(999), Const(999)), Const(42))
        assert run_tree(0, expr) == 42


# ------------------------------------------------------------------
# compile_and_run interface
# ------------------------------------------------------------------

class TestCompileAndRun:

    def test_simple_var(self):
        assert compile_and_run("(var x 42 x)") == 42

    def test_set_bang(self):
        assert compile_and_run("(var x 0 (set! x 42) x)") == 42

    def test_increment(self):
        assert compile_and_run("(var x 41 (set! x (+ x 1)) x)") == 42

    def test_multiple_mutations(self):
        assert compile_and_run(
            "(var x 1 (set! x (* x 2)) (set! x (* x 3)) (set! x (* x 7)) x)"
        ) == 42

    def test_var_with_arg(self):
        assert compile_and_run(
            "(var acc n (set! acc (+ acc 1)) acc)", n=41
        ) == 42

    def test_abs_via_mutable(self):
        assert compile_and_run(
            "(var r 0 (if (< x 0) (set! r (* x -1)) (set! r x)) r)",
            x=-42
        ) == 42
        assert compile_and_run(
            "(var r 0 (if (< x 0) (set! r (* x -1)) (set! r x)) r)",
            x=42
        ) == 42

    def test_two_vars(self):
        assert compile_and_run("(var a 6 (var b 7 (* a b)))") == 42

    def test_mixed_let_and_var(self):
        assert compile_and_run(
            "(let ((scale 6)) (var x 0 (set! x (* scale 7)) x))"
        ) == 42
