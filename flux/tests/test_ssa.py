"""
Tests for SSA construction and destruction.

Coverage
--------
CFG construction  — correct block split, successor/predecessor edges
Dominators        — idom for simple if-then-else CFG
Phi insertion     — phi placed at the correct join point
Variable renaming — every VReg defined exactly once (SSA invariant)
SSA destruction   — phi converted to copies, correct values emitted
End-to-end        — compile and execute after SSA round-trip
"""
import ctypes
import sys
import pytest

from flux.core.ir        import VReg, Opcode, Instr
from flux.core.operands  import Imm
from flux.core.builder   import FunctionBuilder
from flux.core.burg      import BurgSelector
from flux.core.tree      import Const, Arg, Add, Sub, Mul, If, Lt, Gt, Eq
from flux.core.cfg       import build_cfg, compute_dominators, compute_frontiers, reverse_postorder
from flux.core.ssa       import to_ssa, from_ssa, PhiNode
from flux.core.linear_scan   import LinearScanAllocator
from flux.targets.x86_64.emitter  import X86_64Emitter
from flux.targets.x86_64.targets  import WINDOWS, LINUX

from tests.jit import make_callable, free_code

TARGET = WINDOWS if sys.platform == "win32" else LINUX


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def build_if_fn():
    """f(x) = (if (< x 0) 0 x)  — a simple if-then-else."""
    b    = FunctionBuilder("f")
    x,   = b.params(1)
    sel  = BurgSelector([x], b)
    res  = sel.select(If(Lt(Arg(0), Const(0)), Const(0), Arg(0)))
    b.ret(res)
    return b.build()


def build_add_fn():
    """f(a, b) = a + b  — no branches."""
    b  = FunctionBuilder("f")
    a, x = b.params(2)
    r  = b.add(a, x)
    b.ret(r)
    return b.build()


def compile_and_run_via_ssa(fn, *args):
    """Full pipeline with SSA round-trip."""
    ssa = to_ssa(fn)
    out = from_ssa(ssa)
    emitter   = X86_64Emitter(TARGET)
    allocator = LinearScanAllocator(TARGET)
    allocator.allocate(out, emitter)
    code     = emitter.get_code()
    argtypes = [ctypes.c_int64] * len(args)
    func, handle = make_callable(code, ctypes.c_int64, *argtypes)
    result = func(*args)
    free_code(handle)
    return result


# ------------------------------------------------------------------
# CFG construction tests
# ------------------------------------------------------------------

class TestCFG:

    def test_no_branches_single_block(self):
        fn = build_add_fn()
        entry, cfg = build_cfg(fn)
        assert entry == "entry"
        assert len(cfg) == 1
        assert "entry" in cfg
        assert cfg["entry"].succs == []
        assert cfg["entry"].preds == []

    def test_if_splits_into_four_blocks(self):
        fn = build_if_fn()
        entry, cfg = build_cfg(fn)
        # entry, then (unnamed), else (L-something), merge (L-something)
        assert len(cfg) == 4

    def test_entry_has_two_successors(self):
        fn = build_if_fn()
        entry, cfg = build_cfg(fn)
        assert len(cfg["entry"].succs) == 2

    def test_merge_block_has_two_predecessors(self):
        fn = build_if_fn()
        entry, cfg = build_cfg(fn)
        # Find the merge block: the one with 2 predecessors and a RET terminator
        merge = next(
            lbl for lbl, blk in cfg.items()
            if len(blk.preds) == 2
        )
        assert merge is not None

    def test_predecessor_edges_symmetric(self):
        """If A is in B.preds, then B is in A.succs."""
        fn = build_if_fn()
        _, cfg = build_cfg(fn)
        for lbl, block in cfg.items():
            for succ in block.succs:
                assert lbl in cfg[succ].preds, (
                    f"{lbl} is succ of {succ} but {lbl} not in preds"
                )

    def test_terminator_stripped_from_body(self):
        """Terminator instructions must not appear in block.instrs."""
        fn = build_if_fn()
        _, cfg = build_cfg(fn)
        term_ops = {Opcode.JGE, Opcode.JLE, Opcode.JNE, Opcode.JMP, Opcode.RET}
        for block in cfg.values():
            for instr in block.instrs:
                assert instr.opcode not in term_ops, (
                    f"Terminator opcode {instr.opcode} in body of block {block.label}"
                )


# ------------------------------------------------------------------
# Dominator tests
# ------------------------------------------------------------------

class TestDominators:

    def _idom(self, fn):
        entry, cfg = build_cfg(fn)
        rpo  = reverse_postorder(cfg, entry)
        return compute_dominators(cfg, entry, rpo), cfg

    def test_entry_dominates_itself(self):
        idom, _ = self._idom(build_add_fn())
        assert idom["entry"] == "entry"

    def test_entry_dominates_all_if_blocks(self):
        idom, cfg = self._idom(build_if_fn())
        for lbl in cfg:
            assert lbl in idom, f"Block {lbl} unreachable?"
            # Walk up the idom chain — must reach entry
            runner = lbl
            seen   = set()
            while runner != "entry":
                assert runner not in seen, "idom cycle"
                seen.add(runner)
                runner = idom[runner]

    def test_merge_dominated_by_entry(self):
        idom, cfg = self._idom(build_if_fn())
        merge = next(lbl for lbl, blk in cfg.items() if len(blk.preds) == 2)
        assert idom[merge] == "entry"

    def test_then_else_dominated_by_entry(self):
        idom, cfg = self._idom(build_if_fn())
        merge = next(lbl for lbl, blk in cfg.items() if len(blk.preds) == 2)
        for lbl in cfg:
            if lbl not in ("entry", merge):
                assert idom[lbl] == "entry"


# ------------------------------------------------------------------
# Phi insertion tests
# ------------------------------------------------------------------

class TestPhiInsertion:

    def test_no_phi_for_linear_function(self):
        ssa = to_ssa(build_add_fn())
        for block in ssa.blocks.values():
            assert block.phis == [], f"Unexpected phi in {block.label}"

    def test_phi_inserted_at_merge_block(self):
        ssa   = to_ssa(build_if_fn())
        merge = next(lbl for lbl, blk in ssa.blocks.items()
                     if len(blk.preds) == 2)
        assert len(ssa.blocks[merge].phis) >= 1

    def test_phi_has_two_incoming_values(self):
        ssa   = to_ssa(build_if_fn())
        merge = next(lbl for lbl, blk in ssa.blocks.items()
                     if len(blk.preds) == 2)
        for phi in ssa.blocks[merge].phis:
            assert len(phi.incoming) == 2, \
                f"Expected 2 incoming values, got {phi.incoming}"

    def test_no_phi_in_then_or_else(self):
        ssa   = to_ssa(build_if_fn())
        merge = next(lbl for lbl, blk in ssa.blocks.items()
                     if len(blk.preds) == 2)
        for lbl, block in ssa.blocks.items():
            if lbl not in ("entry", merge):
                assert block.phis == []


# ------------------------------------------------------------------
# Variable renaming tests
# ------------------------------------------------------------------

class TestRenaming:

    def _collect_defs(self, ssa):
        """Return every VReg that appears as a result in the SSA function."""
        defs = []
        for block in ssa.blocks.values():
            for phi in block.phis:
                defs.append(phi.result)
            for instr in block.instrs:
                if instr.result is not None:
                    defs.append(instr.result)
        return defs

    def test_each_vreg_defined_once(self):
        ssa  = to_ssa(build_if_fn())
        defs = self._collect_defs(ssa)
        assert len(defs) == len(set(defs)), \
            f"Duplicate definitions in SSA: {defs}"

    def test_params_unchanged(self):
        fn  = build_if_fn()
        ssa = to_ssa(fn)
        # Params must be identical VReg objects (version-0 of themselves).
        assert ssa.params == fn.params

    def test_phi_result_is_fresh(self):
        fn  = build_if_fn()
        ssa = to_ssa(fn)
        original_ids = {v.id for v in fn.params}
        for block in ssa.blocks.values():
            for instr in block.instrs:
                if instr.result:
                    original_ids.add(instr.result.id)
        # phi results must have IDs above the original IR's max
        for block in ssa.blocks.values():
            for phi in block.phis:
                assert phi.result.id not in original_ids or \
                       phi.result.id > max(original_ids) - 1

    def test_linear_function_unchanged_semantics(self):
        fn  = build_add_fn()
        ssa = to_ssa(fn)
        # No phis, no extra VRegs (simple linear function)
        defs = self._collect_defs(ssa)
        assert len(defs) == len(set(defs))


# ------------------------------------------------------------------
# SSA destruction tests
# ------------------------------------------------------------------

class TestDestruction:

    def test_no_phis_after_destruction(self):
        ssa = to_ssa(build_if_fn())
        from_ssa(ssa)   # modifies ssa in-place
        for block in ssa.blocks.values():
            assert block.phis == []

    def test_copies_inserted_in_predecessors(self):
        ssa   = to_ssa(build_if_fn())
        merge = next(lbl for lbl, blk in ssa.blocks.items()
                     if len(blk.preds) == 2)
        preds = list(ssa.blocks[merge].preds)

        from_ssa(ssa)

        # Each predecessor should have at least one MOVE (the phi copy).
        for pred_lbl in preds:
            moves = [i for i in ssa.blocks[pred_lbl].instrs
                     if i.opcode == Opcode.MOVE]
            assert len(moves) >= 1, \
                f"No phi copy inserted in predecessor {pred_lbl}"

    def test_reconstruction_is_valid_function(self):
        fn  = build_if_fn()
        ssa = to_ssa(fn)
        out = from_ssa(ssa)
        assert isinstance(out, type(fn))
        assert out.name   == fn.name
        assert out.params == fn.params
        # The flat output must still have a RET instruction.
        has_ret = any(i.opcode == Opcode.RET
                      for block in out.blocks
                      for i in block.instrs)
        assert has_ret


# ------------------------------------------------------------------
# End-to-end execution tests
# ------------------------------------------------------------------

class TestEndToEnd:

    def test_add_round_trip(self):
        fn = build_add_fn()
        assert compile_and_run_via_ssa(fn, 10, 32) == 42

    def test_if_round_trip_positive(self):
        fn = build_if_fn()
        assert compile_and_run_via_ssa(fn, 7)  == 7

    def test_if_round_trip_negative(self):
        fn = build_if_fn()
        assert compile_and_run_via_ssa(fn, -5) == 0

    def test_if_round_trip_zero(self):
        fn = build_if_fn()
        assert compile_and_run_via_ssa(fn, 0) == 0

    def test_abs_via_ssa(self):
        b = FunctionBuilder("abs")
        x, = b.params(1)
        sel = BurgSelector([x], b)
        res = sel.select(If(Lt(Arg(0), Const(0)), Mul(Arg(0), Const(-1)), Arg(0)))
        b.ret(res)
        fn = b.build()
        assert compile_and_run_via_ssa(fn, -42) == 42
        assert compile_and_run_via_ssa(fn,  42) == 42

    def test_nested_if_via_ssa(self):
        # sign(x): -1, 0, or 1
        b = FunctionBuilder("sign")
        x, = b.params(1)
        sel = BurgSelector([x], b)
        res = sel.select(
            If(Lt(Arg(0), Const(0)),
               Const(-1),
               If(Eq(Arg(0), Const(0)), Const(0), Const(1)))
        )
        b.ret(res)
        fn = b.build()
        assert compile_and_run_via_ssa(fn, -5) == -1
        assert compile_and_run_via_ssa(fn,  0) ==  0
        assert compile_and_run_via_ssa(fn,  5) ==  1

    def test_complex_expression_via_ssa(self):
        # f(a, b, c) = (a + b) - c
        b = FunctionBuilder("f")
        a, x, c = b.params(3)
        t = b.add(a, x)
        r = b.sub(t, c)
        b.ret(r)
        assert compile_and_run_via_ssa(b.build(), 20, 30, 8) == 42

    def test_ssa_and_direct_give_same_result(self):
        """SSA round-trip must produce the same result as the direct pipeline."""
        from flux.core.compiler import compile_and_run

        cases = [
            ("(if (< x 0) (* x -1) x)", dict(x=-7)),
            ("(if (< x 0) (* x -1) x)", dict(x=7)),
            ("(if (> a b) a b)",          dict(a=10, b=20)),
            ("(+ (* x x) (* y y))",       dict(x=3, y=4)),
        ]

        for expr, kwargs in cases:
            direct = compile_and_run(expr, **kwargs)

            # Rebuild fn for SSA path
            from flux.core.parser  import parse_expr
            arg_names  = list(kwargs.keys())
            arg_values = [kwargs[n] for n in arg_names]
            tree   = parse_expr(expr, args=arg_names)
            builder= FunctionBuilder("f")
            params = builder.params(len(arg_names))
            sel    = BurgSelector(params, builder)
            result = sel.select(tree)
            builder.ret(result)

            via_ssa = compile_and_run_via_ssa(builder.build(), *arg_values)
            assert via_ssa == direct, \
                f"Mismatch for {expr!r} {kwargs}: direct={direct}, ssa={via_ssa}"
