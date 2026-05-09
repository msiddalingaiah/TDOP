from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List

from flux.core.operands  import Imm, SpillSlot
from flux.core.ir        import VReg, Opcode, Instr, Function
from flux.core.target    import Target
from flux.core.emitter   import Emitter
from flux.core.allocator import Allocator
import struct


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
    """Compute live intervals, extending across loop back-edges."""
    intervals: Dict[VReg, LiveInterval] = {}

    for p in fn.params:
        intervals[p] = LiveInterval(p, start=-1, end=-1)

    label_pos: Dict[int, int] = {}
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

    pos = 0
    for block in fn.blocks:
        for instr in block.instrs:
            if instr.opcode in {Opcode.JMP, Opcode.JGE, Opcode.JLE, Opcode.JNE}:
                target_id  = instr.operands[0].id
                target_pos = label_pos.get(target_id, pos + 1)
                if target_pos < pos:
                    for iv in intervals.values():
                        if iv.start <= target_pos <= iv.end:
                            iv.end = max(iv.end, pos)
            pos += 1

    return intervals


# ------------------------------------------------------------------
# Allocator
# ------------------------------------------------------------------

class LinearScanAllocator(Allocator):
    """Linear scan allocator with spilling, callee-save, and stack args.

    Parameters beyond the platform's register count (4 on Windows,
    6 on Linux) are passed on the stack by the caller and loaded into
    registers at callee entry.  There is no hard limit on argument count.

    ABI handling:
    - Callee saves every callee-saved register it uses (prologue/epilogue).
    - Caller saves caller-saved register values live across each call
      site via push/pop (strict iv.start < pos; result captured before pops).
    """

    def __init__(self, target: Target) -> None:
        super().__init__(target)
        self._frame_size:  int  = 0
        self._extra_saves: list = []   # callee-saved regs used by this fn
        self._stack_params: list = []  # [(VReg, stack_index), ...]

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def allocate(self, fn: Function, emitter: Emitter) -> None:
        alloc     = self._build_allocation(fn)
        intervals = compute_intervals(fn)
        has_frame = (self._frame_size > 0 or fn.has_calls
                     or bool(self._extra_saves) or bool(self._stack_params))

        if has_frame:
            emitter.emit_prologue(self._frame_size, self._extra_saves)

            # Spilled register-params: store from arg reg to spill slot.
            n_reg = len(self.target.arg_registers)
            for i, param in enumerate(fn.params[:n_reg]):
                if isinstance(alloc.get(param), SpillSlot):
                    orig_reg = self.target.arg_registers[i]
                    emitter.store_spill(orig_reg, alloc[param])

            # Stack params: load from caller's stack frame.
            # Layout: first stack arg at [rbp + 8*(3+len(extra_saves)+1+0)]
            #                           = [rbp + 8*(4+len(extra_saves))]
            s1 = self.target.scratch_registers[0]
            base_off = 8 * (4 + len(self._extra_saves))
            for vreg, k in self._stack_params:
                offset = base_off + k * 8
                loc    = alloc.get(vreg)
                if isinstance(loc, SpillSlot):
                    emitter.load_spill(s1, SpillSlot(offset))
                    emitter.store_spill(s1, loc)
                elif loc is not None:
                    emitter.load_spill(loc, SpillSlot(offset))

        pos = 0
        for block in fn.blocks:
            for instr in block.instrs:
                if has_frame:
                    self._lower_spilling(instr, alloc, emitter,
                                         intervals=intervals, pos=pos)
                else:
                    self._lower(instr, alloc, emitter)
                pos += 1

    # ------------------------------------------------------------------
    # Allocation
    # ------------------------------------------------------------------

    def _build_allocation(self, fn: Function) -> Dict[VReg, object]:
        intervals = compute_intervals(fn)
        alloc     = self._linear_scan(fn, intervals)

        already_handled  = ({self.target.frame_pointer}
                            | set(self.target.scratch_registers))
        callee_saved_set = set(self.target.callee_saved) - already_handled
        self._extra_saves = sorted(
            {loc for loc in alloc.values()
             if not isinstance(loc, SpillSlot) and loc in callee_saved_set},
            key=lambda r: r.index
        )
        return alloc

    def _linear_scan(self, fn: Function,
                     intervals: Dict[VReg, LiveInterval]) -> Dict[VReg, object]:
        alloc:    Dict[VReg, object] = {}
        reserved = {self.target.stack_pointer, self.target.frame_pointer}
        reserved.update(self.target.scratch_registers)

        n_reg = len(self.target.arg_registers)

        # Pin register params to their arg registers.
        param_regs: set = set()
        for vreg, reg in zip(fn.params[:n_reg], self.target.arg_registers):
            alloc[vreg] = reg
            param_regs.add(reg)

        # Stack params (beyond register count) are NOT pre-assigned —
        # they'll be allocated from the free pool like ordinary VRegs
        # and loaded from the stack at function entry.
        self._stack_params = [(vreg, i)
                              for i, vreg in enumerate(fn.params[n_reg:])]

        base_pool = [r for r in reversed(self.target.registers)
                     if r not in reserved and r not in param_regs]

        if fn.has_calls:
            callee_s = set(self.target.callee_saved) - reserved
            caller_p = [r for r in base_pool if r not in callee_s]
            callee_p = [r for r in base_pool if r in callee_s]
            free: List = caller_p + callee_p
        else:
            free = list(base_pool)

        # Active set: only register params initially (not stack params).
        active: List[LiveInterval] = sorted(
            [intervals[p] for p in fn.params[:n_reg] if p in intervals],
            key=lambda iv: iv.end,
        )

        n_spill_slots = 0

        def spill_at_interval(iv: LiveInterval) -> None:
            nonlocal n_spill_slots
            spill = max(active + [iv], key=lambda a: a.end)
            if spill is not iv and spill.end > iv.end:
                reg = alloc[spill.vreg]
                n_spill_slots += 1
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
            still_active = [a for a in active if a.end >= iv.start]
            freed        = [a for a in active if a.end < iv.start]
            for a in freed:
                free.append(alloc[a.vreg])
            active = still_active

            if not free:
                spill_at_interval(iv)
            else:
                reg = free.pop()
                alloc[iv.vreg] = reg
                active.append(iv)
                active.sort(key=lambda x: x.end)

        total_slots = fn.n_vars + n_spill_slots
        raw = total_slots * 8
        self._frame_size = (raw + 15) & ~15 if total_slots > 0 else 0
        return alloc

    # ------------------------------------------------------------------
    # Spill-aware lowering
    # ------------------------------------------------------------------

    def _lower_spilling(self, instr: Instr,
                        alloc: Dict[VReg, object],
                        emitter: Emitter,
                        intervals: Dict = None,
                        pos: int = 0) -> None:
        s1, s2 = self.target.scratch_registers

        if instr.opcode == Opcode.CALL:
            self._lower_call(instr, alloc, emitter, intervals or {}, pos)
            return

        if instr.opcode == Opcode.RET:
            val_loc = alloc[instr.operands[0]]
            if isinstance(val_loc, SpillSlot):
                emitter.load_spill(s1, val_loc)
                val_reg = s1
            else:
                val_reg = val_loc
            if val_reg != self.target.return_register:
                emitter.mov(self.target.return_register, val_reg)
            emitter.emit_epilogue(self._extra_saves)
            return

        temp    = dict(alloc)
        reloads = []

        for i, op in enumerate(instr.operands):
            if isinstance(op, VReg) and isinstance(alloc.get(op), SpillSlot):
                scratch = s1 if i == 0 else s2
                reloads.append((scratch, alloc[op]))
                temp[op] = scratch

        result_slot = None
        if instr.result is not None and isinstance(alloc.get(instr.result), SpillSlot):
            result_slot        = alloc[instr.result]
            temp[instr.result] = s1

        for scratch, slot in reloads:
            emitter.load_spill(scratch, slot)

        self._lower(instr, temp, emitter)

        if result_slot is not None:
            emitter.store_spill(s1, result_slot)

    # ------------------------------------------------------------------
    # CALL lowering
    # ------------------------------------------------------------------

    def _lower_call(self, instr: Instr,
                    alloc: Dict[VReg, object],
                    emitter: Emitter,
                    intervals: Dict,
                    pos: int) -> None:
        s1, s2           = self.target.scratch_registers
        caller_saved_set = set(self.target.caller_saved)
        ret_reg          = self.target.return_register

        ptr_addr  = instr.operands[0].value
        arg_ops   = instr.operands[1:]
        n_reg     = len(self.target.arg_registers)
        reg_ops   = arg_ops[:n_reg]
        stack_ops = arg_ops[n_reg:]
        N_stack   = len(stack_ops)

        # ── Find caller-saved registers with live values ───────────────
        live_to_save: list = []
        seen_regs:    set  = set()
        for vreg, loc in sorted(alloc.items(), key=lambda x: x[0].id):
            if (not isinstance(loc, SpillSlot)
                    and loc in caller_saved_set
                    and loc != ret_reg
                    and loc not in seen_regs):
                iv = intervals.get(vreg)
                if iv and iv.start < pos and iv.end > pos:
                    live_to_save.append(loc)
                    seen_regs.add(loc)

        # ── Push live caller-saved registers ──────────────────────────
        for r in live_to_save:
            emitter.push(r)

        needs_pad = (len(live_to_save) % 2 == 1)
        if needs_pad:
            emitter._emit(0x48, 0x83, 0xEC, 0x08)   # sub rsp, 8

        # ── Push stack arguments (reverse order) ──────────────────────
        # If N_stack is odd, push a dummy 0 first to maintain alignment.
        stack_dummy = (N_stack % 2 == 1)
        if stack_dummy:
            emitter._emit(0x6A, 0x00)               # push 0 (alignment pad)

        for op in reversed(stack_ops):
            if isinstance(op, VReg):
                loc = alloc.get(op)
                if isinstance(loc, SpillSlot):
                    emitter.load_spill(s1, loc)
                    emitter.push(s1)
                else:
                    emitter.push(loc)

        # ── Parallel-move register arguments ─────────────────────────
        arg_moves: list = []
        for i, op in enumerate(reg_ops):
            if isinstance(op, VReg):
                loc = alloc.get(op)
                if isinstance(loc, SpillSlot):
                    emitter.load_spill(s1, loc)
                    src = s1
                else:
                    src = loc
                dst = self.target.arg_registers[i]
                if src != dst:
                    arg_moves.append((src, dst))

        self._emit_parallel_moves(emitter, arg_moves, s2)

        # ── Indirect call ─────────────────────────────────────────────
        emitter.call_ptr(ptr_addr)

        # ── Clean up stack arguments ──────────────────────────────────
        if N_stack > 0 or stack_dummy:
            n_pushed = N_stack + (1 if stack_dummy else 0)
            cleanup  = n_pushed * 8
            if cleanup <= 127:
                emitter._emit(0x48, 0x83, 0xC4, cleanup)  # add rsp, imm8
            else:
                emitter._emit(0x48, 0x81, 0xC4)
                emitter._buf.extend(struct.pack('<I', cleanup))

        if needs_pad:
            emitter._emit(0x48, 0x83, 0xC4, 0x08)   # add rsp, 8

        # ── Capture return value BEFORE restoring caller-saves ────────
        if instr.result is not None:
            loc = alloc.get(instr.result)
            if isinstance(loc, SpillSlot):
                emitter.store_spill(ret_reg, loc)
            elif loc != ret_reg:
                emitter.mov(loc, ret_reg)

        # ── Restore caller-saved registers ────────────────────────────
        for r in reversed(live_to_save):
            emitter.pop(r)

    # ------------------------------------------------------------------
    # Parallel move sequencer
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_parallel_moves(emitter: Emitter, moves: list, scratch) -> None:
        """Emit parallel register moves without clobbering sources."""
        remaining = list(moves)
        while remaining:
            src_set = {s for s, _ in remaining}
            safe    = [(s, d) for s, d in remaining if d not in src_set]
            if safe:
                for s, d in safe:
                    emitter.mov(d, s)
                for m in safe:
                    remaining.remove(m)
            else:
                s, d = remaining[0]
                emitter.mov(scratch, s)
                remaining = [(scratch if src == s else src, dst)
                             for src, dst in remaining]
