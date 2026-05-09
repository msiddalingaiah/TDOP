from __future__ import annotations
from typing import List, Union

from flux.core.operands import Imm, MutableVar
from flux.core.ir import VReg, LabelRef, Opcode, Instr, BasicBlock, Function


class FunctionBuilder:
    """Fluent builder for linear-IR functions."""

    def __init__(self, name: str) -> None:
        self.name           = name
        self._counter       = 0
        self._label_counter = 0
        self._n_vars        = 0
        self._has_calls     = False
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

    def div(self, lhs: VReg, rhs: VReg) -> VReg:
        """Emit  result = lhs // rhs  (signed integer division)."""
        result = self._fresh()
        self._emit(Instr(Opcode.DIV, result, [lhs, rhs]))
        return result

    def mod(self, lhs: VReg, rhs: VReg) -> VReg:
        """Emit  result = lhs % rhs  (signed integer remainder)."""
        result = self._fresh()
        self._emit(Instr(Opcode.MOD, result, [lhs, rhs]))
        return result

    def band(self, lhs: VReg, rhs: Union[VReg, Imm]) -> VReg:
        """Emit  result = lhs & rhs  (bitwise AND)."""
        result = self._fresh()
        self._emit(Instr(Opcode.BAND, result, [lhs, rhs]))
        return result

    def bor(self, lhs: VReg, rhs: Union[VReg, Imm]) -> VReg:
        """Emit  result = lhs | rhs  (bitwise OR)."""
        result = self._fresh()
        self._emit(Instr(Opcode.BOR, result, [lhs, rhs]))
        return result

    def bxor(self, lhs: VReg, rhs: Union[VReg, Imm]) -> VReg:
        """Emit  result = lhs ^ rhs  (bitwise XOR)."""
        result = self._fresh()
        self._emit(Instr(Opcode.BXOR, result, [lhs, rhs]))
        return result

    def shl(self, lhs: VReg, rhs: Union[VReg, Imm]) -> VReg:
        """Emit  result = lhs << rhs  (left shift)."""
        result = self._fresh()
        self._emit(Instr(Opcode.SHL, result, [lhs, rhs]))
        return result

    def shr(self, lhs: VReg, rhs: Union[VReg, Imm]) -> VReg:
        """Emit  result = lhs >> rhs  (arithmetic right shift)."""
        result = self._fresh()
        self._emit(Instr(Opcode.SHR, result, [lhs, rhs]))
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

    def alloc_mutable_var(self) -> MutableVar:
        """Allocate a new mutable variable stack slot.

        Slots are laid out below RBP in allocation order:
            var 0 → [rbp - 8]
            var 1 → [rbp - 16]  etc.
        Spill slots (if any) are placed below the last var slot.
        """
        index  = self._n_vars
        offset = -(index + 1) * 8
        self._n_vars += 1
        return MutableVar(index, offset)

    def load_var(self, var: MutableVar) -> VReg:
        """Emit  result = [rbp + var.offset]  (mutable variable read)."""
        result = self._fresh()
        self._emit(Instr(Opcode.LOAD_VAR, result, [var]))
        return result

    def store_var(self, var: MutableVar, value: VReg) -> None:
        """Emit  [rbp + var.offset] = value  (mutable variable write)."""
        self._emit(Instr(Opcode.STORE_VAR, None, [var, value]))

    def call(self, ptr_holder_addr: int, *args: VReg) -> VReg:
        """Emit an indirect function call through a pointer holder.

        ptr_holder_addr — address of a ctypes.c_uint64 holding the
                          function pointer (stable before compilation).
        args            — VRegs to pass as arguments.
        """
        result = self._fresh()
        self._has_calls = True
        self._emit(Instr(Opcode.CALL, result,
                         [Imm(ptr_holder_addr)] + list(args)))
        return result

    # ------------------------------------------------------------------
    # Finalise
    # ------------------------------------------------------------------

    def build(self) -> Function:
        return Function(self.name, self._params, self._blocks,
                        self._n_vars, self._has_calls)
