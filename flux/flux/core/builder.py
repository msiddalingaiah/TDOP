from __future__ import annotations
from typing import List, Union

from flux.core.operands import Imm
from flux.core.ir import VReg, Opcode, Instr, BasicBlock, Function


class FunctionBuilder:
    """Fluent builder for linear-IR functions.

    Usage::

        b = FunctionBuilder("add")
        a, x = b.params(2)
        result = b.add(a, x)
        b.ret(result)
        fn = b.build()
        print(fn)
    """

    def __init__(self, name: str) -> None:
        self.name      = name
        self._counter  = 0
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
        """Declare a single function parameter and return its VReg."""
        v = self._fresh()
        self._params.append(v)
        return v

    def params(self, n: int) -> List[VReg]:
        """Declare *n* parameters and return their VRegs."""
        return [self.param() for _ in range(n)]

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------

    def load_imm(self, value: int) -> VReg:
        """Emit  result = <immediate>."""
        result = self._fresh()
        self._emit(Instr(Opcode.LOAD_IMM, result, [Imm(value)]))
        return result

    def move(self, src: VReg) -> VReg:
        """Emit  result = src  (register copy)."""
        result = self._fresh()
        self._emit(Instr(Opcode.MOVE, result, [src]))
        return result

    def add(self, lhs: VReg, rhs: Union[VReg, Imm]) -> VReg:
        """Emit  result = lhs + rhs."""
        result = self._fresh()
        self._emit(Instr(Opcode.ADD, result, [lhs, rhs]))
        return result

    def mul(self, lhs: VReg, rhs: Union[VReg, Imm]) -> VReg:
        """Emit  result = lhs * rhs."""
        result = self._fresh()
        self._emit(Instr(Opcode.MUL, result, [lhs, rhs]))
        return result

    def sub(self, lhs: VReg, rhs: Union[VReg, Imm]) -> VReg:
        """Emit  result = lhs - rhs."""
        result = self._fresh()
        self._emit(Instr(Opcode.SUB, result, [lhs, rhs]))
        return result

    def ret(self, value: VReg) -> None:
        """Emit  ret value  (terminates the current block)."""
        self._emit(Instr(Opcode.RET, None, [value]))

    # ------------------------------------------------------------------
    # Finalise
    # ------------------------------------------------------------------

    def build(self) -> Function:
        """Return the completed Function."""
        return Function(self.name, self._params, self._blocks)
