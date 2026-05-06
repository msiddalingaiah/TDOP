from __future__ import annotations
from dataclasses import dataclass

from flux.core.operands import Reg


@dataclass(frozen=True)
class X86_64Reg(Reg):
    """An x86-64 physical register.

    extended=True for R8-R15, which require a REX.B or REX.R bit
    to encode when they appear in the r/m or reg field of ModRM.
    """
    extended: bool = False


# --- General-purpose registers ---
RAX = X86_64Reg("rax",  0)
RCX = X86_64Reg("rcx",  1)
RDX = X86_64Reg("rdx",  2)
RBX = X86_64Reg("rbx",  3)
RSP = X86_64Reg("rsp",  4)
RBP = X86_64Reg("rbp",  5)
RSI = X86_64Reg("rsi",  6)
RDI = X86_64Reg("rdi",  7)
R8  = X86_64Reg("r8",   8,  extended=True)
R9  = X86_64Reg("r9",   9,  extended=True)
R10 = X86_64Reg("r10", 10,  extended=True)
R11 = X86_64Reg("r11", 11,  extended=True)
R12 = X86_64Reg("r12", 12,  extended=True)
R13 = X86_64Reg("r13", 13,  extended=True)
R14 = X86_64Reg("r14", 14,  extended=True)
R15 = X86_64Reg("r15", 15,  extended=True)

ALL = [RAX, RCX, RDX, RBX, RSP, RBP, RSI, RDI,
       R8,  R9,  R10, R11, R12, R13, R14, R15]
