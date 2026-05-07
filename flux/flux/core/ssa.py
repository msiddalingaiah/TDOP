"""
SSA (Static Single Assignment) construction and destruction.

Public API
----------
to_ssa(fn)    — transform a flat-IR Function into SSA form
from_ssa(fn)  — reconstruct a flat Function from SSA form (SSA destruction)

Pipeline
--------
  FunctionBuilder
      ↓
  Function (flat IR, single block)
      ↓  to_ssa()
  SSAFunction
      · CFG with proper basic blocks and predecessor/successor edges
      · PhiNode at each join point for multiply-defined variables
      · Every VReg defined exactly once (SSA invariant)
      ↓  [optional optimisations]
      ↓  from_ssa()
  Function (flat IR, ready for LinearScan)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from flux.core.ir       import VReg, Opcode, Instr, LabelRef, Function, BasicBlock
from flux.core.operands import Imm
from flux.core.cfg      import (CFGBlock, build_cfg, reverse_postorder,
                                 compute_dominators, compute_frontiers)


# ------------------------------------------------------------------
# SSA data structures
# ------------------------------------------------------------------

@dataclass
class PhiNode:
    """A φ-function at a basic block's entry.

    ``result``   — the fresh SSA VReg this phi defines.
    ``original`` — the pre-SSA VReg this phi is tracking (stable through renaming).
    ``incoming`` — maps each predecessor block label to the reaching VReg.
    """
    result:   VReg
    original: VReg
    incoming: Dict[str, VReg] = field(default_factory=dict)

    def __repr__(self) -> str:
        inc = ", ".join(f"{k}: {v!r}" for k, v in self.incoming.items())
        return f"{self.result!r} = φ({inc})"


@dataclass
class SSABlock:
    """A proper basic block in SSA form."""
    label:  str
    phis:   List[PhiNode]
    instrs: List[Instr]
    term:   Optional[Instr]   # None = fall-through to succs[0]
    succs:  List[str]
    preds:  List[str]

    def __repr__(self) -> str:
        phi_lines  = "\n".join(f"  {p!r}"  for p in self.phis)
        body_lines = "\n".join(f"  {i!r}"  for i in self.instrs)
        term_line  = f"  {self.term!r}" if self.term else "  <fall-through>"
        parts = [f"block {self.label}:"]
        if phi_lines:  parts.append(phi_lines)
        if body_lines: parts.append(body_lines)
        parts.append(term_line)
        return "\n".join(parts)


@dataclass
class SSAFunction:
    """A function in SSA form."""
    name:        str
    params:      List[VReg]
    entry:       str
    blocks:      Dict[str, SSABlock]   # label → block (ordered: original split order)
    block_order: List[str]             # block labels in original flat-IR order

    def __repr__(self) -> str:
        body = "\n".join(repr(self.blocks[lbl]) for lbl in self.block_order)
        params = ", ".join(repr(p) for p in self.params)
        return f"ssa function {self.name}({params}):\n{body}"


# ------------------------------------------------------------------
# to_ssa
# ------------------------------------------------------------------

def to_ssa(fn: Function) -> SSAFunction:
    """Transform a flat-IR Function into SSA form.

    Steps
    -----
    1. Split flat IR into proper basic blocks (build_cfg).
    2. Compute dominators and dominance frontiers.
    3. Find all multiply-defined variables and insert phi nodes.
    4. Rename every definition to a unique VReg (variable renaming).
    """
    entry, cfg = build_cfg(fn)
    rpo   = reverse_postorder(cfg, entry)
    idom  = compute_dominators(cfg, entry, rpo)
    df    = compute_frontiers(cfg, idom)

    # Build SSAFunction from the CFG, deep-copying all Instr objects so
    # renaming does not mutate the original Function.
    ssa_blocks: Dict[str, SSABlock] = {}
    block_order: List[str] = []

    for lbl, blk in cfg.items():
        ssa_blocks[lbl] = SSABlock(
            label  = lbl,
            phis   = [],
            instrs = [_copy_instr(i) for i in blk.instrs],
            term   = _copy_instr(blk.term) if blk.term else None,
            succs  = list(blk.succs),
            preds  = list(blk.preds),
        )
        block_order.append(lbl)

    ssa_fn = SSAFunction(fn.name, list(fn.params), entry, ssa_blocks, block_order)

    defs = _find_defs(fn.params, cfg)
    _insert_phis(ssa_fn, df, defs)
    _rename(ssa_fn, idom, fn)
    _prune_unused_phis(ssa_fn)   # remove spurious phis for non-live variables

    return ssa_fn


def _copy_instr(instr: Instr) -> Instr:
    """Shallow-copy an Instr (VReg/LabelRef/Imm operands are immutable)."""
    return Instr(instr.opcode, instr.result, list(instr.operands))


# ----------------------------------------------------------------
# Def-site analysis
# ----------------------------------------------------------------

def _find_defs(params: List[VReg],
               cfg:    Dict[str, CFGBlock]) -> Dict[VReg, Set[str]]:
    """Return, for each VReg, the set of block labels where it is defined."""
    defs: Dict[VReg, Set[str]] = {}

    # Parameters are defined at the entry block.
    for p in params:
        defs.setdefault(p, set()).add("entry")

    for lbl, block in cfg.items():
        for instr in block.instrs:
            if instr.result is not None:
                defs.setdefault(instr.result, set()).add(lbl)
        if block.term and block.term.result is not None:
            defs.setdefault(block.term.result, set()).add(lbl)

    return defs


# ----------------------------------------------------------------
# Phi insertion
# ----------------------------------------------------------------

def _insert_phis(ssa_fn:    SSAFunction,
                 df:        Dict[str, Set[str]],
                 defs:      Dict[VReg, Set[str]]) -> None:
    """Insert φ-node placeholders at dominance frontiers.

    Only variables defined in two or more blocks need phis.
    """
    for var, def_blocks in defs.items():
        if len(def_blocks) < 2:
            continue

        work:    Set[str] = set(def_blocks)
        has_phi: Set[str] = set()

        while work:
            blk_label = work.pop()
            for frontier in df.get(blk_label, set()):
                if frontier not in has_phi:
                    # Deduplicate: one phi per variable per block.
                    if not any(p.original == var
                               for p in ssa_fn.blocks[frontier].phis):
                        ssa_fn.blocks[frontier].phis.append(
                            PhiNode(result=var, original=var)
                        )
                    has_phi.add(frontier)
                    if frontier not in def_blocks:
                        work.add(frontier)


# ----------------------------------------------------------------
# Variable renaming
# ----------------------------------------------------------------

def _rename(ssa_fn: SSAFunction,
            idom:   Dict[str, str],
            fn:     Function) -> None:
    """Rename all variables to make every definition unique (SSA invariant).

    Uses a DFS traversal of the dominator tree, maintaining a renaming
    stack for each original variable.
    """
    # Fresh VReg IDs start above the highest existing ID.
    counter = [_max_vreg_id(fn) + 1]

    stacks: Dict[VReg, List[VReg]] = {}

    def fresh(v: VReg) -> VReg:
        new_v = VReg(counter[0])
        counter[0] += 1
        stacks.setdefault(v, []).append(new_v)
        return new_v

    def current(v: VReg) -> VReg:
        stack = stacks.get(v)
        return stack[-1] if stack else v   # return original if stack empty

    # Parameters are their own "version 0".
    for p in ssa_fn.params:
        stacks[p] = [p]

    # Build dominator-tree children.
    dom_children: Dict[str, List[str]] = {lbl: [] for lbl in ssa_fn.blocks}
    for lbl, dom in idom.items():
        if lbl != dom:
            dom_children[dom].append(lbl)

    def rename(block_label: str) -> None:
        block = ssa_fn.blocks[block_label]
        pushed: Dict[VReg, int] = {}   # original VReg → # of pushes in this block

        # 1. Rename phi results (new definitions at block entry).
        for phi in block.phis:
            phi.result = fresh(phi.original)
            pushed[phi.original] = pushed.get(phi.original, 0) + 1

        # 2. Rename body instructions.
        for instr in block.instrs:
            instr.operands = [
                current(op) if isinstance(op, VReg) else op
                for op in instr.operands
            ]
            if instr.result is not None:
                orig = instr.result
                instr.result = fresh(orig)
                pushed[orig] = pushed.get(orig, 0) + 1

        # 3. Rename terminator uses (VReg operands; LabelRef/Imm unchanged).
        if block.term:
            block.term.operands = [
                current(op) if isinstance(op, VReg) else op
                for op in block.term.operands
            ]

        # 4. Fill in phi operands at successor blocks.
        for succ_label in block.succs:
            if succ_label not in ssa_fn.blocks:
                continue
            for phi in ssa_fn.blocks[succ_label].phis:
                phi.incoming[block_label] = current(phi.original)

        # 5. Recurse on dominator-tree children.
        for child in dom_children.get(block_label, []):
            rename(child)

        # 6. Pop renaming stacks (restore state for sibling subtrees).
        for orig, count in pushed.items():
            for _ in range(count):
                if stacks.get(orig):
                    stacks[orig].pop()

    rename(ssa_fn.entry)


def _collect_used_vregs(ssa_fn: SSAFunction) -> Set[VReg]:
    """Return every VReg that appears as an operand anywhere in *ssa_fn*."""
    used: Set[VReg] = set()
    for block in ssa_fn.blocks.values():
        for phi in block.phis:
            used.update(v for v in phi.incoming.values() if isinstance(v, VReg))
        for instr in block.instrs:
            used.update(op for op in instr.operands if isinstance(op, VReg))
        if block.term:
            used.update(op for op in block.term.operands if isinstance(op, VReg))
    return used


def _prune_unused_phis(ssa_fn: SSAFunction) -> None:
    """Remove phi nodes whose result is never used.

    Phi insertion is conservative (non-pruned SSA): it places phis at
    dominance frontiers even for variables that are not actually live at
    those join points.  After renaming, such phis have a result VReg
    that nothing reads — they are safe to drop.

    Iterates to convergence so that chains of unused phis are fully
    eliminated (relevant when loops are added).
    """
    while True:
        used    = _collect_used_vregs(ssa_fn)
        pruned  = False
        for block in ssa_fn.blocks.values():
            before     = len(block.phis)
            block.phis = [p for p in block.phis if p.result in used]
            if len(block.phis) < before:
                pruned = True
        if not pruned:
            break


def _max_vreg_id(fn: Function) -> int:
    """Return the highest VReg ID appearing anywhere in *fn*."""
    max_id = -1

    def check(v: object) -> None:
        nonlocal max_id
        if isinstance(v, VReg):
            max_id = max(max_id, v.id)

    for p in fn.params:
        check(p)
    for block in fn.blocks:
        for instr in block.instrs:
            check(instr.result)
            for op in instr.operands:
                check(op)

    return max_id


# ------------------------------------------------------------------
# from_ssa  (SSA destruction)
# ------------------------------------------------------------------

def from_ssa(ssa_fn: SSAFunction) -> Function:
    """Reconstruct a flat IR Function from SSA form.

    SSA destruction steps
    ---------------------
    1. For each φ-node, insert parallel copy instructions at the end of
       each predecessor block's body (before the terminator).
    2. Sequentialise the parallel copies to handle potential ordering
       conflicts (the swap problem).
    3. Strip the φ-nodes.
    4. Flatten all blocks back into a single-block Function, preserving
       the original block order so fall-through edges remain correct.
    """
    _insert_phi_copies(ssa_fn)

    flat: List[Instr] = []

    for lbl in ssa_fn.block_order:
        block = ssa_fn.blocks[lbl]

        # Emit a LABEL pseudo-op for every block except the entry.
        if lbl != ssa_fn.entry:
            label_id = _label_id(lbl)
            if label_id is not None:
                flat.append(Instr(Opcode.LABEL, None, [LabelRef(label_id)]))
            # Blocks with generated labels (e.g. "__b0") have no LabelRef
            # because they are reached only by fall-through — no explicit label
            # is needed in the flat output.

        flat.extend(block.instrs)

        if block.term is not None:
            flat.append(block.term)

    return Function(
        ssa_fn.name,
        list(ssa_fn.params),
        [BasicBlock("entry", flat)],
    )


def _label_id(lbl: str) -> Optional[int]:
    """Return the integer ID for a label like 'L5', or None for generated labels."""
    if lbl.startswith("L") and lbl[1:].isdigit():
        return int(lbl[1:])
    return None


# ----------------------------------------------------------------
# Phi copy insertion
# ----------------------------------------------------------------

def _insert_phi_copies(ssa_fn: SSAFunction) -> None:
    """Replace φ-nodes with parallel copies inserted into predecessor blocks."""
    for block in ssa_fn.blocks.values():
        if not block.phis:
            continue

        # Collect the copies each predecessor needs to emit.
        pred_copies: Dict[str, List[Tuple[VReg, VReg]]] = {}
        for phi in block.phis:
            for pred_label, src in phi.incoming.items():
                dst = phi.result
                if dst != src:
                    pred_copies.setdefault(pred_label, []).append((dst, src))

        # Insert sequentialised copies into each predecessor's body.
        for pred_label, copies in pred_copies.items():
            pred_block = ssa_fn.blocks[pred_label]
            for dst, src in _sequentialise(copies):
                pred_block.instrs.append(Instr(Opcode.MOVE, dst, [src]))

        block.phis = []


def _sequentialise(copies: List[Tuple[VReg, VReg]]) -> List[Tuple[VReg, VReg]]:
    """Order parallel copies safely (avoids the lost-copy problem).

    Emits copies in a topological order of the dependency graph, where
    each copy ``dst ← src`` has an edge src → dst.  Handles DAG cases
    correctly.  Cyclic dependencies (from loops) are emitted in order
    with a TODO comment — they do not arise in our current SSA IR.
    """
    copies = [(d, s) for d, s in copies if d != s]
    if not copies:
        return []

    result:    List[Tuple[VReg, VReg]] = []
    remaining: List[Tuple[VReg, VReg]] = list(copies)

    while remaining:
        # Find copies whose source is not written by another pending copy.
        dst_set = {d for d, _ in remaining}
        safe    = [(d, s) for d, s in remaining if s not in dst_set]

        if safe:
            result.extend(safe)
            for copy in safe:
                remaining.remove(copy)
        else:
            # Cycle — emit remaining in order (safe for our current IR,
            # which has no back-edge phi cycles).
            # TODO: break cycles with a temporary when loops are added.
            result.extend(remaining)
            break

    return result
