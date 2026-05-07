from __future__ import annotations
from dataclasses import dataclass
from typing import List

from flux.core.operands import Reg


@dataclass
class Target:
    """Describes an ISA and calling convention for the backend."""
    name:              str
    registers:         List[Reg]   # all allocatable physical registers
    caller_saved:      List[Reg]   # caller must save/restore these
    callee_saved:      List[Reg]   # callee must save/restore these
    arg_registers:     List[Reg]   # integer argument passing order
    return_register:   Reg         # where integer return value lives
    stack_pointer:     Reg
    frame_pointer:     Reg
    scratch_registers: List[Reg]   # reserved for spill reload/store (not allocatable)
    word_size:         int = 8     # bytes
