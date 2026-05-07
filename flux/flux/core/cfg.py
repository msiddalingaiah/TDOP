"""
Control-flow graph construction and dominator analysis.

Provides the foundation for SSA construction:
  build_cfg()          — split flat IR into proper basic blocks
  reverse_postorder()  — RPO traversal for the dominator algorithm
  compute_dominators() — Cooper, Harvey & Kennedy (2001)
  compute_frontiers()  — standard dominance-frontier algorithm
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from flux.core.ir import Instr, Opcode, Function


# Opcodes that terminate a basic block.
TERM_OPS = frozenset({
    Opcode.JGE, Opcode.JLE, Opcode.JNE,
    Opcode.JMP, Opcode.RET,
})


# ------------------------------------------------------------------
# Data structure
# ------------------------------------------------------------------

@dataclass
class CFGBlock:
    """A proper basic block in the control-flow graph.

    ``term`` is the block's terminating instruction.
    ``term = None`` means the block falls through to ``succs[0]``.
    """
    label:  str
    instrs: List[Instr]          # body instructions (LABEL pseudo-ops stripped)
    term:   Optional[Instr]      # None → fall-through to succs[0]
    succs:  List[str]            # successor block labels
    preds:  List[str]            # predecessor block labels


# ------------------------------------------------------------------
# CFG construction
# ------------------------------------------------------------------

def build_cfg(fn: Function) -> Tuple[str, Dict[str, CFGBlock]]:
    """Split the flat IR of *fn* into a CFG of proper basic blocks.

    Returns ``(entry_label, blocks)`` where *blocks* is an ordered dict
    (insertion order = original instruction order, preserving fall-through).
    """
    flat: List[Instr] = []
    for blk in fn.blocks:
        flat.extend(blk.instrs)

    n = len(flat)
    if n == 0:
        return "entry", {"entry": CFGBlock("entry", [], None, [], [])}

    # ----------------------------------------------------------------
    # Step 1 — find block leaders (first instruction of each block)
    # ----------------------------------------------------------------
    leaders: Set[int] = {0}
    for i, instr in enumerate(flat):
        if instr.opcode == Opcode.LABEL:
            leaders.add(i)                   # LABEL starts a new block
        if instr.opcode in TERM_OPS and i + 1 < n:
            leaders.add(i + 1)              # instruction after terminator

    sorted_leaders = sorted(leaders)

    # ----------------------------------------------------------------
    # Step 2 — assign a label to each leader
    # ----------------------------------------------------------------
    gen_count = 0
    block_label_at: Dict[int, str] = {}
    for k, start in enumerate(sorted_leaders):
        end   = sorted_leaders[k + 1] if k + 1 < len(sorted_leaders) else n
        first = flat[start]
        if start == 0:
            lbl = "entry"
        elif first.opcode == Opcode.LABEL:
            lbl = f"L{first.operands[0].id}"
        else:
            lbl = f"__b{gen_count}"
            gen_count += 1
        block_label_at[start] = lbl

    # ----------------------------------------------------------------
    # Step 3 — build CFGBlock objects
    # ----------------------------------------------------------------
    cfg: Dict[str, CFGBlock] = {}

    for k, start in enumerate(sorted_leaders):
        end = sorted_leaders[k + 1] if k + 1 < len(sorted_leaders) else n
        lbl = block_label_at[start]
        raw = list(flat[start:end])

        # Strip leading LABEL pseudo-op (it's encoded in lbl now).
        if raw and raw[0].opcode == Opcode.LABEL:
            raw = raw[1:]

        # Separate body from terminator.
        if raw and raw[-1].opcode in TERM_OPS:
            term = raw[-1]
            body = raw[:-1]
        else:
            term = None        # fall-through
            body = raw

        # Determine successor labels.
        succs: List[str] = []
        if term is None:
            # Fall-through to next sequential block.
            if k + 1 < len(sorted_leaders):
                succs = [block_label_at[sorted_leaders[k + 1]]]
        elif term.opcode == Opcode.JMP:
            succs = [f"L{term.operands[0].id}"]
        elif term.opcode in {Opcode.JGE, Opcode.JLE, Opcode.JNE}:
            jump_target  = f"L{term.operands[0].id}"
            fall_through = (block_label_at[sorted_leaders[k + 1]]
                            if k + 1 < len(sorted_leaders) else None)
            # Convention: succs[0] = fall-through (then), succs[1] = jump (else).
            succs = [s for s in [fall_through, jump_target] if s is not None]
        elif term.opcode == Opcode.RET:
            succs = []

        cfg[lbl] = CFGBlock(lbl, body, term, succs, [])

    # ----------------------------------------------------------------
    # Step 4 — build predecessor edges
    # ----------------------------------------------------------------
    for lbl, block in cfg.items():
        for succ in block.succs:
            if succ in cfg and lbl not in cfg[succ].preds:
                cfg[succ].preds.append(lbl)

    return "entry", cfg


# ------------------------------------------------------------------
# Reverse post-order traversal
# ------------------------------------------------------------------

def reverse_postorder(blocks: Dict[str, CFGBlock], entry: str) -> List[str]:
    """Return blocks in reverse post-order (required by the dominator algorithm)."""
    visited:   Set[str]  = set()
    postorder: List[str] = []

    def dfs(label: str) -> None:
        visited.add(label)
        for succ in blocks[label].succs:
            if succ in blocks and succ not in visited:
                dfs(succ)
        postorder.append(label)

    dfs(entry)
    return list(reversed(postorder))


# ------------------------------------------------------------------
# Dominator computation — Cooper, Harvey & Kennedy (2001)
# ------------------------------------------------------------------

def compute_dominators(blocks: Dict[str, CFGBlock],
                        entry:  str,
                        rpo:    List[str]) -> Dict[str, str]:
    """Return the immediate dominator of every reachable block.

    Uses the simple iterative algorithm from Cooper et al. (2001):
    "A Simple, Fast Dominance Algorithm."
    """
    rpo_num: Dict[str, int] = {label: i for i, label in enumerate(rpo)}
    idom:    Dict[str, str] = {entry: entry}

    changed = True
    while changed:
        changed = False
        for label in rpo:
            if label == entry:
                continue
            processed_preds = [p for p in blocks[label].preds if p in idom]
            if not processed_preds:
                continue
            new_idom = processed_preds[0]
            for pred in processed_preds[1:]:
                new_idom = _intersect(pred, new_idom, idom, rpo_num)
            if idom.get(label) != new_idom:
                idom[label] = new_idom
                changed = True

    return idom


def _intersect(b1: str, b2: str,
               idom:    Dict[str, str],
               rpo_num: Dict[str, int]) -> str:
    """Find the common dominator of two nodes (finger algorithm)."""
    while b1 != b2:
        while rpo_num[b1] > rpo_num[b2]:
            b1 = idom[b1]
        while rpo_num[b2] > rpo_num[b1]:
            b2 = idom[b2]
    return b1


# ------------------------------------------------------------------
# Dominance frontier
# ------------------------------------------------------------------

def compute_frontiers(blocks: Dict[str, CFGBlock],
                       idom:   Dict[str, str]) -> Dict[str, Set[str]]:
    """Compute the dominance frontier for every block.

    DF(B) = { Y | B dominates a predecessor of Y, but B does not
               strictly dominate Y }.
    """
    df: Dict[str, Set[str]] = {lbl: set() for lbl in blocks}

    for label, block in blocks.items():
        if len(block.preds) >= 2:               # join point
            dom_of_label = idom.get(label, label)
            for pred in block.preds:
                runner = pred
                while runner != dom_of_label:
                    df[runner].add(label)
                    next_runner = idom.get(runner)
                    if next_runner is None or next_runner == runner:
                        break
                    runner = next_runner

    return df
