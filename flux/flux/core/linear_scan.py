from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Union

from flux.core.operands  import Imm, SpillSlot
from flux.core.ir        import VReg, Opcode, Instr, Function
from flux.core.target    import Target
from flux.core.emitter   import Emitter
from flux.core.allocator import Allocator


# ------------------------------------------------------------------
# Live intervals
# ------------------------------------------------------------------

@dataclass
class LiveInterval:
    vreg:  VReg
    start: int
    end:   int

    def __repr__(self) -> str:
        return f"LiveInterval({self.vreg!r}, [{self.start}, {self.end}])"


def compute_intervals(fn: Function) -> Dict[VReg, LiveInterval]:
    """Compute a live interval for every VReg in *fn*.

    For loops, back-edges are detected and any variable live at a loop
    header has its interval extended to cover the entire loop body.
    This prevents the register allocator from reusing a register that
    still holds a value needed on the next iteration.
    """
    intervals: Dict[VReg, LiveInterval] = {}

    for p in fn.params:
        intervals[p] = LiveInterval(p, start=-1, end=-1)

    # --- First pass: build initial intervals, record label positions ---
    label_pos: Dict[int, int] = {}   # label_id → instruction position
    pos = 0
    for block in fn.blocks:
        for instr in block.instrs:
            if instr.opcode == Opcode.LABEL:
                label_pos[instr.operands[0].id] = pos

            if instr.result is not None and instr.result not in intervals:
                intervals[instr.result] = LiveInterval(instr.result, pos, pos)

            for op in instr.operands:
                if isinstance(op, VReg) and op in intervals:
                    intervals[op].end = pos

            pos += 1

    # --- Second pass: extend intervals across loop back-edges ---
    # A back-edge is any branch whose target label appears earlier in
    # the flat instruction list.  For each such edge (back_pos → header_pos),
    # any variable that is live at the header (defined before or at it, and
    # used at or after it) must remain live through the entire loop body.
    pos = 0
    for block in fn.blocks:
        for instr in block.instrs:
            if instr.opcode in {Opcode.JMP, Opcode.JGE, Opcode.JLE, Opcode.JNE}:
                target_id  = instr.operands[0].id
                target_pos = label_pos.get(target_id, pos + 1)
                if target_pos < pos:          # back-edge detected
                    for iv in intervals.values():
                        if iv.start <= target_pos <= iv.end:
                            iv.end = max(iv.end, pos)
            pos += 1

    return intervals


# ------------------------------------------------------------------
# Allocator
# ------------------------------------------------------------------

class LinearScanAllocator(Allocator):
    """Linear scan register allocator with stack spilling.

    When the register pool is exhausted, the interval with the furthest
    end point is spilled to a [RBP-relative] stack slot.  Two scratch
    registers (target.scratch_registers) are reserved for reload/store
    and are not available for general allocation.

    Stack frame layout (when spills are present):
        [rbp + 0 ]  ← rbp saved here (via push rbp)
        [rbp - 8 ]  spill slot 0
        [rbp - 16]  spill slot 1
        ...
    Scratch registers (r14, r15) are saved/restored via push/pop in
    the prologue/epilogue.
    """

    def __init__(self, target: Target) -> None:
        super().__init__(target)
        self._frame_size: int = 0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def allocate(self, fn: Function, emitter: Emitter) -> None:
        alloc      = self._build_allocation(fn)
        has_frame  = self._frame_size > 0   # True for spills OR mutable vars

        if has_frame:
            emitter.emit_prologue(self._frame_size)
            # Parameters that were spilled must be stored to their slots
            # immediately — before any instruction can overwrite the arg register.
            for i, param in enumerate(fn.params):
                if isinstance(alloc.get(param), SpillSlot):
                    orig_reg = self.target.arg_registers[i]
                    emitter.store_spill(orig_reg, alloc[param])

        for block in fn.blocks:
            for instr in block.instrs:
                if has_frame:
                    self._lower_spilling(instr, alloc, emitter)
                else:
                    self._lower(instr, alloc, emitter)

    # ------------------------------------------------------------------
    # Allocation
    # ------------------------------------------------------------------

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
        reserved.update(self.target.scratch_registers)

        param_regs: set = set()
        for vreg, reg in zip(fn.params, self.target.arg_registers):
            alloc[vreg] = reg
            param_regs.add(reg)

        free: List = [r for r in reversed(self.target.registers)
                      if r not in reserved and r not in param_regs]

        active: List[LiveInterval] = sorted(
            [intervals[p] for p in fn.params if p in intervals],
            key=lambda iv: iv.end,
        )

        n_spill_slots = 0

        def spill_at_interval(iv: LiveInterval) -> None:
            nonlocal n_spill_slots
            spill = max(active + [iv], key=lambda a: a.end)
            if spill is not iv and spill.end > iv.end:
                reg = alloc[spill.vreg]
                n_spill_slots += 1
                # Spill slots start below the mutable-var area.
                alloc[spill.vreg] = SpillSlot(-(fn.n_vars + n_spill_slots) * 8)
                active.remove(spill)
                alloc[iv.vreg] = reg
                active.append(iv)
                active.sort(key=lambda x: x.end)
            else:
                n_spill_slots += 1
                alloc[iv.vreg] = SpillSlot(-(fn.n_vars + n_spill_slots) * 8)

        non_param = sorted(
            [iv for vreg, iv in intervals.items() if vreg not in alloc],
            key=lambda iv: iv.start,
        )

        for iv in non_param:
            still_active: List[LiveInterval] = []
            for a in active:
                if a.end < iv.start:
                    free.append(alloc[a.vreg])
                else:
                    still_active.append(a)
            active = still_active

            if not free:
                spill_at_interval(iv)
            else:
                reg = free.pop()
                alloc[iv.vreg] = reg
                active.append(iv)
                active.sort(key=lambda x: x.end)

        # Total frame = mutable var area + spill area, 16-byte aligned.
        total_slots = fn.n_vars + n_spill_slots
        raw = total_slots * 8
        self._frame_size = (raw + 15) & ~15 if total_slots > 0 else 0
        return alloc

    # ------------------------------------------------------------------
    # Spill-aware lowering
    # ------------------------------------------------------------------

    def _lower_spilling(self, instr: Instr,
                        alloc: Dict[VReg, object],
                        emitter: Emitter) -> None:
        s1, s2 = self.target.scratch_registers

        # RET: resolve value, move to return register, emit epilogue.
        if instr.opcode == Opcode.RET:
            val_loc = alloc[instr.operands[0]]
            if isinstance(val_loc, SpillSlot):
                emitter.load_spill(s1, val_loc)
                val_reg = s1
            else:
                val_reg = val_loc
            if val_reg != self.target.return_register:
                emitter.mov(self.target.return_register, val_reg)
            emitter.emit_epilogue()
            return

        # Build a temporary alloc with spills resolved to scratch registers.
        # Operand 0 → s1,  Operand 1 → s2,  Result → s1.
        # s1 is shared between lhs and result: safe because x86 two-address
        # ops overwrite lhs with the result (lhs is consumed before write).
        temp    = dict(alloc)
        reloads = []

        for i, op in enumerate(instr.operands):
            if isinstance(op, VReg) and isinstance(alloc.get(op), SpillSlot):
                scratch = s1 if i == 0 else s2
                reloads.append((scratch, alloc[op]))
                temp[op] = scratch

        result_slot = None
        if instr.result is not None and isinstance(alloc.get(instr.result), SpillSlot):
            result_slot    = alloc[instr.result]
            temp[instr.result] = s1

        for scratch, slot in reloads:
            emitter.load_spill(scratch, slot)

        self._lower(instr, temp, emitter)

        if result_slot is not None:
            emitter.store_spill(s1, result_slot)
