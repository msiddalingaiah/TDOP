from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


class Operand:
    """Base class for all instruction operands."""
    pass


@dataclass(frozen=True)
class Reg(Operand):
    """A physical register."""
    name:  str
    index: int

    def __repr__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Imm(Operand):
    """An immediate (constant) integer value."""
    value: int

    def __repr__(self) -> str:
        return f"#{self.value}"


@dataclass(frozen=True)
class Mem(Operand):
    """A memory reference: [base + index*scale + disp]"""
    base:  Reg
    disp:  int           = 0
    index: Optional[Reg] = None
    scale: int           = 1

    def __repr__(self) -> str:
        parts = [repr(self.base)]
        if self.index is not None:
            parts.append(f"{self.index}*{self.scale}")
        if self.disp:
            parts.append(hex(self.disp))
        return f"[{' + '.join(parts)}]"


@dataclass(frozen=True)
class SpillSlot:
    """A stack spill slot at [RBP + offset] where offset is negative."""
    offset: int

    def __repr__(self) -> str:
        return f"[rbp{self.offset:+d}]"
