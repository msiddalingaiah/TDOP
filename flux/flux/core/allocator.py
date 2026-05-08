from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict

from flux.core.operands import Imm
from flux.core.ir       import VReg, Opcode, Instr, Function
from flux.core.emitter  import Emitter
from flux.core.target   import Target


class Allocator(ABC):
    """Abstract base for register allocators.

    Subclasses implement _build_allocation(); the base class handles
    instruction lowering (VReg → physical Reg) and drives the emitter.
    This keeps the lowering logic in one place regardless of which
    allocation strategy is in use.
    """

    def __init__(self, target: Target) -> None:
        self.target = target

    # ------------------------------------------------------------------
    # Subclass contract
    # ------------------------------------------------------------------

    @abstractmethod
    def _build_allocation(self, fn: Function) -> Dict[VReg, object]:
        """Return a mapping from every VReg in *fn* to a physical Reg."""
        ...

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def allocate(self, fn: Function, emitter: Emitter) -> None:
        """Lower *fn* through *emitter* using this allocator's assignment."""
        alloc = self._build_allocation(fn)
        for block in fn.blocks:
            for instr in block.instrs:
                self._lower(instr, alloc, emitter)

    # ------------------------------------------------------------------
    # Shared instruction lowering
    # ------------------------------------------------------------------

    def _lower(self, instr: Instr,
               alloc: Dict[VReg, object], emitter: Emitter) -> None:

        def reg(v):
            return alloc[v]

        def resolve(op):
            return alloc[op] if isinstance(op, VReg) else op

        match instr.opcode:

            case Opcode.LOAD_IMM:
                emitter.mov(reg(instr.result), instr.operands[0])

            case Opcode.MOVE:
                dst, src = reg(instr.result), reg(instr.operands[0])
                if dst != src:
                    emitter.mov(dst, src)

            case Opcode.ADD:
                dst = reg(instr.result)
                lhs = reg(instr.operands[0])
                rhs = resolve(instr.operands[1])
                if dst != lhs:
                    emitter.mov(dst, lhs)
                emitter.add(dst, rhs)

            case Opcode.LOAD_VAR:
                # Load from a mutable variable's stack slot.
                from flux.core.operands import SpillSlot
                dst = reg(instr.result)
                var = instr.operands[0]    # MutableVar
                emitter.load_spill(dst, SpillSlot(var.offset))

            case Opcode.STORE_VAR:
                # Store to a mutable variable's stack slot.
                from flux.core.operands import SpillSlot
                var = instr.operands[0]    # MutableVar
                src = reg(instr.operands[1])
                emitter.store_spill(src, SpillSlot(var.offset))

            case Opcode.CMP:
                lhs = reg(instr.operands[0])
                rhs = resolve(instr.operands[1])
                emitter.cmp(lhs, rhs)

            case Opcode.JGE:
                emitter.jge(instr.operands[0].id)

            case Opcode.JLE:
                emitter.jle(instr.operands[0].id)

            case Opcode.JNE:
                emitter.jne(instr.operands[0].id)

            case Opcode.JMP:
                emitter.jmp(instr.operands[0].id)

            case Opcode.LABEL:
                emitter.place_label(instr.operands[0].id)

            case Opcode.MUL:
                dst = reg(instr.result)
                lhs = reg(instr.operands[0])
                rhs = resolve(instr.operands[1])
                if isinstance(rhs, Imm):
                    emitter.mul(dst, lhs, rhs)   # 3-operand: dst = lhs * imm
                else:
                    if dst != lhs:
                        emitter.mov(dst, lhs)
                    emitter.mul(dst, rhs)         # 2-operand: dst *= rhs

            case Opcode.SUB:
                dst = reg(instr.result)
                lhs = reg(instr.operands[0])
                rhs = resolve(instr.operands[1])
                if dst != lhs:
                    emitter.mov(dst, lhs)
                emitter.sub(dst, rhs)

            case Opcode.RET:
                val     = reg(instr.operands[0])
                ret_reg = self.target.return_register
                if val != ret_reg:
                    emitter.mov(ret_reg, val)
                emitter.ret()
