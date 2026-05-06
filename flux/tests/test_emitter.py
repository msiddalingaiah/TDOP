"""
Tests for the x86-64 emitter.

Encoding tests verify raw byte output against known-good sequences.
Execution tests run the generated code in memory to confirm correctness.
"""
import ctypes
import sys
import pytest

from flux.core.operands import Imm
from flux.targets.x86_64.emitter  import X86_64Emitter
from flux.targets.x86_64 import regs
from flux.targets.x86_64.targets  import WINDOWS, LINUX

from tests.jit import make_callable, free_code

# Pick the target that matches the running platform.
TARGET = WINDOWS if sys.platform == "win32" else LINUX


def make_emitter() -> X86_64Emitter:
    return X86_64Emitter(TARGET)


# ------------------------------------------------------------------
# Encoding tests — verify raw bytes without executing
# ------------------------------------------------------------------

class TestEncoding:

    def test_ret(self):
        e = make_emitter()
        e.ret()
        assert e.get_code() == bytes([0xC3])

    def test_mov_rax_imm(self):
        # mov rax, 42  →  REX.W(0x48) + 0xB8 + imm64-LE
        e = make_emitter()
        e.mov(regs.RAX, Imm(42))
        code = e.get_code()
        assert code[0]  == 0x48           # REX.W
        assert code[1]  == 0xB8           # opcode (B8+0 for RAX)
        assert code[2:] == (42).to_bytes(8, "little")

    def test_mov_r8_imm(self):
        # mov r8, 1  →  REX.W+REX.B(0x49) + 0xB8 + imm64-LE
        e = make_emitter()
        e.mov(regs.R8, Imm(1))
        code = e.get_code()
        assert code[0] == 0x49            # REX.W + REX.B
        assert code[1] == 0xB8           # B8+0 (index 8 & 7 == 0)

    def test_mov_reg_reg(self):
        # mov rax, rcx  →  REX.W(0x48) + 0x89 + ModRM
        e = make_emitter()
        e.mov(regs.RAX, regs.RCX)
        code = e.get_code()
        assert code[0] == 0x48            # REX.W
        assert code[1] == 0x89            # MOV r/m64, r64
        # ModRM: mod=11, reg=RCX(1), rm=RAX(0) → 0xC8
        assert code[2] == 0b11_001_000

    def test_add_reg_reg(self):
        # add rax, rcx  →  REX.W + 0x01 + ModRM
        e = make_emitter()
        e.add(regs.RAX, regs.RCX)
        code = e.get_code()
        assert code[0] == 0x48
        assert code[1] == 0x01
        assert code[2] == 0b11_001_000

    def test_push_rax(self):
        # push rax  →  0x50  (no REX needed)
        e = make_emitter()
        e.push(regs.RAX)
        assert e.get_code() == bytes([0x50])

    def test_push_r8(self):
        # push r8  →  REX.B(0x41) + 0x50
        e = make_emitter()
        e.push(regs.R8)
        assert e.get_code() == bytes([0x41, 0x50])

    def test_pop_rbx(self):
        # pop rbx  →  0x5B  (58 + 3)
        e = make_emitter()
        e.pop(regs.RBX)
        assert e.get_code() == bytes([0x5B])


# ------------------------------------------------------------------
# Execution tests — run the generated code in memory
# ------------------------------------------------------------------

class TestExecution:

    def _run(self, code: bytes,
             restype=ctypes.c_int64, *argtypes) -> int:
        func, handle = make_callable(code, restype, *argtypes)
        result = func()
        free_code(handle)
        return result

    def _run_with_args(self, code: bytes, *args,
                       restype=ctypes.c_int64) -> int:
        argtypes = [ctypes.c_int64] * len(args)
        func, handle = make_callable(code, restype, *argtypes)
        result = func(*args)
        free_code(handle)
        return result

    def test_return_immediate(self):
        # mov rax, 42; ret  →  42
        e = make_emitter()
        e.mov(regs.RAX, Imm(42))
        e.ret()
        assert self._run(e.get_code()) == 42

    def test_return_negative(self):
        # mov rax, -7; ret  →  -7
        e = make_emitter()
        e.mov(regs.RAX, Imm(-7))
        e.ret()
        assert self._run(e.get_code()) == -7

    def test_add_two_args(self):
        # f(a, b) = a + b
        # arg0 → first arg reg, arg1 → second arg reg, return in RAX
        arg0, arg1 = TARGET.arg_registers[:2]
        e = make_emitter()
        e.mov(regs.RAX, arg0)
        e.add(regs.RAX, arg1)
        e.ret()
        assert self._run_with_args(e.get_code(), 10, 32) == 42

    def test_sub_two_args(self):
        # f(a, b) = a - b
        arg0, arg1 = TARGET.arg_registers[:2]
        e = make_emitter()
        e.mov(regs.RAX, arg0)
        e.sub(regs.RAX, arg1)
        e.ret()
        assert self._run_with_args(e.get_code(), 50, 8) == 42

    def test_add_immediate(self):
        # f(a) = a + 1
        arg0 = TARGET.arg_registers[0]
        e = make_emitter()
        e.mov(regs.RAX, arg0)
        e.add(regs.RAX, Imm(1))
        e.ret()
        assert self._run_with_args(e.get_code(), 41) == 42
