from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List

from flux.core.operands  import Imm
from flux.core.ir        import VReg, Function
from flux.core.target    import Target
from flux.core.allocator import Allocator


# ------------------------------------------------------------------
# Live intervals
# ------------------------------------------------------------------

@dataclass
class LiveInterval:
    """The range of instructions over which a VReg is live.

    start — instruction index where the VReg is defined (-1 for params,
            which are live before the first instruction).
    end   — instruction index of the VReg's last use.
    """
    vreg:  VReg
    start: int
    end:   int

    def __repr__(self) -> str:
        return f"LiveInterval({self.vreg!r}, [{self.start}, {self.end}])"


def compute_intervals(fn: Function) -> Dict[VReg, LiveInterval]:
    """Compute a live interval for every VReg in *fn*.

    Instructions across all blocks are numbered sequentially from 0.
    Parameters are given start=-1 to mark them as live before the
    first instruction.
    """
    intervals: Dict[VReg, LiveInterval] = {}

    # Parameters: defined before instruction 0.
    for p in fn.params:
        intervals[p] = LiveInterval(p, start=-1, end=-1)

    pos = 0
    for block in fn.blocks:
        for instr in block.instrs:
            # Definition: open a new interval at this position.
            if instr.result is not None and instr.result not in intervals:
                intervals[instr.result] = LiveInterval(instr.result, pos, pos)

            # Uses: extend each operand's interval to cover this position.
            for op in instr.operands:
                if isinstance(op, VReg) and op in intervals:
                    intervals[op].end = pos

            pos += 1

    return intervals


# ------------------------------------------------------------------
# Allocator
# ------------------------------------------------------------------

class LinearScanAllocator(Allocator):
    """Register allocator using the Poletto & Sarkar (1999) linear scan
    algorithm.

    Key improvement over TrivialAllocator: registers are released as
    soon as their holder's live range ends and immediately reused for
    new intervals.  This significantly reduces register pressure for
    functions with many temporaries.

    Raises RuntimeError if a spill is required (not yet supported).
    """

    def _build_allocation(self, fn: Function) -> Dict[VReg, object]:
        if len(fn.params) > len(self.target.arg_registers):
            raise RuntimeError(
                f"Function has {len(fn.params)} parameters but target "
                f"only supports {len(self.target.arg_registers)} argument registers."
            )

        intervals = compute_intervals(fn)
        return self._linear_scan(fn, intervals)

    def _linear_scan(self, fn: Function,
                     intervals: Dict[VReg, LiveInterval]) -> Dict[VReg, object]:
        alloc:    Dict[VReg, object] = {}
        reserved = {self.target.stack_pointer, self.target.frame_pointer}

        # Pre-assign parameters to their calling-convention registers.
        param_regs = set()
        for vreg, reg in zip(fn.params, self.target.arg_registers):
            alloc[vreg] = reg
            param_regs.add(reg)

        # Free pool: allocatable registers not yet spoken for.
        # Stored with the preferred next-choice at the end (pop() is O(1)).
        free: List = [r for r in reversed(self.target.registers)
                      if r not in reserved and r not in param_regs]

        # Active: currently live intervals, kept sorted by end point so
        # expiry scans terminate early.
        active: List[LiveInterval] = sorted(
            [intervals[p] for p in fn.params if p in intervals],
            key=lambda iv: iv.end,
        )

        # Process non-parameter intervals in start order.
        non_param = sorted(
            [iv for vreg, iv in intervals.items() if vreg not in alloc],
            key=lambda iv: iv.start,
        )

        for iv in non_param:
            # Expire intervals whose live range ended before iv starts.
            still_active: List[LiveInterval] = []
            for a in active:             # active is sorted by end
                if a.end < iv.start:
                    free.append(alloc[a.vreg])   # reclaim register
                else:
                    still_active.append(a)
            active = still_active

            if not free:
                raise RuntimeError(
                    f"Register spill required for {iv.vreg!r} — "
                    f"not yet supported by LinearScanAllocator."
                )

            # Assign the next free register and mark this interval active.
            reg = free.pop()
            alloc[iv.vreg] = reg
            active.append(iv)
            active.sort(key=lambda x: x.end)   # keep invariant

        return alloc
