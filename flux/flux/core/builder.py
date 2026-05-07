from __future__ import annotations
from typing import List, Union

from flux.core.operands import Imm
from flux.core.ir import VReg, LabelRef, Opcode, Instr, BasicBlock, Function


class FunctionBuilder:
    """Fluent builder for linear-IR functions."""

    def __init__(self, name: str) -> None:
        self.name          = name
        self._counter      = 0
        self._label_counter= 0
        self._params:  List[VReg]       = []
        self._blocks:  List[BasicBlock] = []
        self._current: BasicBlock       = self._new_block("entry")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fresh(self) -> VReg:
        v = VReg(self._counter)
        self._counter += 1
        return v

    def _new_block(self, label: str) -> BasicBlock:
        block = BasicBlock(label)
        self._blocks.append(block)
        return block

    def _emit(self, instr: Instr) -> None:
        self._current.append(instr)

    # ------------------------------------------------------------------
    # Parameters
    # ------------------------------------------------------------------

    def param(self) -> VReg:
        v = self._fresh()
        self._params.append(v)
        return v

    def params(self, n: int) -> List[VReg]:
        return [self.param() for _ in range(n)]

    # ------------------------------------------------------------------
    # Label allocation
    # ------------------------------------------------------------------

    def new_label(self) -> int:
        """Allocate a fresh label ID."""
        lid = self._label_counter
        self._label_counter += 1
        return lid

    def alloc_vreg(self) -> VReg:
        """Allocate a fresh VReg without emitting an instruction.
        Used to pre-reserve a result slot for if-then-else merges.
        """
        return self._fresh()

    # ------------------------------------------------------------------
    # Arithmetic instructions
    # ------------------------------------------------------------------

    def load_imm(self, value: int) -> VReg:
        result = self._fresh()
        self._emit(Instr(Opcode.LOAD_IMM, result, [Imm(value)]))
        return result

    def move(self, src: VReg) -> VReg:
        result = self._fresh()
        self._emit(Instr(Opcode.MOVE, result, [src]))
        return result

    def move_to(self, dst: VReg, src: VReg) -> None:
        """Emit a move into a pre-existing destination VReg."""
        self._emit(Instr(Opcode.MOVE, dst, [src]))

    def add(self, lhs: VReg, rhs: Union[VReg, Imm]) -> VReg:
        result = self._fresh()
        self._emit(Instr(Opcode.ADD, result, [lhs, rhs]))
        return result

    def sub(self, lhs: VReg, rhs: Union[VReg, Imm]) -> VReg:
        result = self._fresh()
        self._emit(Instr(Opcode.SUB, result, [lhs, rhs]))
        return result

    def mul(self, lhs: VReg, rhs: Union[VReg, Imm]) -> VReg:
        result = self._fresh()
        self._emit(Instr(Opcode.MUL, result, [lhs, rhs]))
        return result

    # ------------------------------------------------------------------
    # Comparison and control flow
    # ------------------------------------------------------------------

    def cmp(self, lhs: VReg, rhs: Union[VReg, Imm]) -> None:
        self._emit(Instr(Opcode.CMP, None, [lhs, rhs]))

    def jge(self, label_id: int) -> None:
        self._emit(Instr(Opcode.JGE, None, [LabelRef(label_id)]))

    def jle(self, label_id: int) -> None:
        self._emit(Instr(Opcode.JLE, None, [LabelRef(label_id)]))

    def jne(self, label_id: int) -> None:
        self._emit(Instr(Opcode.JNE, None, [LabelRef(label_id)]))

    def jmp(self, label_id: int) -> None:
        self._emit(Instr(Opcode.JMP, None, [LabelRef(label_id)]))

    def place_label(self, label_id: int) -> None:
        self._emit(Instr(Opcode.LABEL, None, [LabelRef(label_id)]))

    def ret(self, value: VReg) -> None:
        self._emit(Instr(Opcode.RET, None, [value]))

    # ------------------------------------------------------------------
    # Finalise
    # ------------------------------------------------------------------

    def build(self) -> Function:
        return Function(self.name, self._params, self._blocks)
