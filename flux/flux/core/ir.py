from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Union

from flux.core.operands import Imm, MutableVar


# ------------------------------------------------------------------
# Virtual register
# ------------------------------------------------------------------

@dataclass(frozen=True)
class VReg:
    """A virtual register — just an ID.  The allocator maps these to
    physical registers later."""
    id: int

    def __repr__(self) -> str:
        return f"%{self.id}"


# ------------------------------------------------------------------
# Label reference
# ------------------------------------------------------------------

@dataclass(frozen=True)
class LabelRef:
    """A reference to a branch target label, identified by integer ID."""
    id: int

    def __repr__(self) -> str:
        return f"L{self.id}"


# ------------------------------------------------------------------
# Opcodes
# ------------------------------------------------------------------

class Opcode(Enum):
    LOAD_IMM  = auto()   # result = <immediate>
    MOVE      = auto()   # result = src  (vreg copy)
    ADD       = auto()   # result = lhs + rhs
    SUB       = auto()   # result = lhs - rhs
    MUL       = auto()   # result = lhs * rhs
    DIV       = auto()   # result = lhs / rhs  (signed integer division)
    MOD       = auto()   # result = lhs % rhs  (signed remainder)
    BAND      = auto()   # result = lhs & rhs  (bitwise AND)
    BOR       = auto()   # result = lhs | rhs  (bitwise OR)
    BXOR      = auto()   # result = lhs ^ rhs  (bitwise XOR)
    SHL       = auto()   # result = lhs << rhs (left shift)
    SHR       = auto()   # result = lhs >> rhs (arithmetic right shift)
    LOAD_VAR  = auto()   # result = [rbp + var.offset]  (mutable variable read)
    STORE_VAR = auto()   # [rbp + var.offset] = value   (mutable variable write, no result)
    CMP       = auto()   # compare lhs with rhs  (no result, sets flags)
    JGE       = auto()   # jump if ≥  (after cmp)
    JLE       = auto()   # jump if ≤  (after cmp)
    JNE       = auto()   # jump if ≠  (after cmp)
    JMP       = auto()   # unconditional jump
    LABEL     = auto()   # label definition
    RET       = auto()   # return value  (no result)


# ------------------------------------------------------------------
# Instruction
# ------------------------------------------------------------------

# An operand in the linear IR is a virtual register, an immediate,
# a label ref, or a mutable variable slot.
Operand = Union[VReg, Imm, LabelRef, MutableVar]


@dataclass
class Instr:
    """A single linear-IR instruction.

    result  — the VReg written by this instruction, or None for RET.
    operands — inputs: VRegs and/or Imms, depending on opcode.

    Opcode   | result  | operands
    ---------+---------+-------------------
    LOAD_IMM | VReg    | [Imm]
    MOVE     | VReg    | [VReg]
    ADD      | VReg    | [VReg, VReg|Imm]
    SUB      | VReg    | [VReg, VReg|Imm]
    RET      | None    | [VReg]
    """
    opcode:   Opcode
    result:   Optional[VReg]
    operands: List[Operand]

    def __repr__(self) -> str:
        ops = ", ".join(repr(o) for o in self.operands)
        lhs = f"{self.result!r} = " if self.result is not None else ""
        return f"{lhs}{self.opcode.name.lower()} {ops}"


# ------------------------------------------------------------------
# Basic block
# ------------------------------------------------------------------

@dataclass
class BasicBlock:
    """An ordered list of instructions with a single entry and exit."""
    label:  str
    instrs: List[Instr] = field(default_factory=list)

    def append(self, instr: Instr) -> None:
        self.instrs.append(instr)

    def __repr__(self) -> str:
        body = "\n".join(f"    {i!r}" for i in self.instrs)
        return f"  block {self.label}:\n{body}"


# ------------------------------------------------------------------
# Function
# ------------------------------------------------------------------

@dataclass
class Function:
    """A named function: a parameter list and an ordered list of blocks."""
    name:   str
    params: List[VReg]
    blocks: List[BasicBlock]
    n_vars: int = 0   # number of mutable variable stack slots

    def __repr__(self) -> str:
        params = ", ".join(repr(p) for p in self.params)
        blocks = "\n".join(repr(b) for b in self.blocks)
        return f"function {self.name}({params}):\n{blocks}"
