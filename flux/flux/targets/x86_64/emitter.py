from __future__ import annotations
import struct

from flux.core.emitter  import Emitter
from flux.core.operands import Operand, Imm, Mem
from flux.targets.x86_64 import regs
from flux.core.target import Target
from flux.targets.x86_64.regs import X86_64Reg


class X86_64Emitter(Emitter):
    """x86-64 instruction encoder.

    Encoding conventions:
      - All integer operations default to 64-bit (REX.W=1).
      - Extended registers (R8-R15) set REX.R when in the reg field
        of ModRM, and REX.B when in the r/m field or the opcode reg field.
      - ModRM mod=0b11 means both operands are registers (no memory).
    """

    # ------------------------------------------------------------------
    # Encoding helpers
    # ------------------------------------------------------------------

    def _rex(self, w: bool = True, r: bool = False,
             x: bool = False, b: bool = False) -> int:
        """Build a REX prefix byte."""
        return 0x40 | (w << 3) | (r << 2) | (x << 1) | b

    def _modrm(self, mod: int, reg: int, rm: int) -> int:
        """Build a ModRM byte."""
        return (mod << 6) | ((reg & 7) << 3) | (rm & 7)

    def _emit_rex_modrm(self, src: X86_64Reg, dst: X86_64Reg) -> None:
        """Emit REX + ModRM for a reg←reg operation (opcode 0x89 style)."""
        self._emit(self._rex(w=True, r=src.extended, b=dst.extended),
                   self._modrm(0b11, src.index, dst.index))

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------

    def mov(self, dst: Operand, src: Operand) -> None:
        if isinstance(dst, X86_64Reg) and isinstance(src, Imm):
            # MOV r64, imm64 — REX.W + (B8+rd) + imm64
            self._emit(self._rex(w=True, b=dst.extended),
                       0xB8 | (dst.index & 7))
            self._buf.extend(struct.pack('<q', src.value))

        elif isinstance(dst, X86_64Reg) and isinstance(src, X86_64Reg):
            # MOV r/m64, r64 — REX.W + 89 /r
            self._emit_rex_modrm(src, dst)
            self._buf.insert(-1, 0x89)   # splice opcode between REX and ModRM

        else:
            raise NotImplementedError(
                f"mov {type(dst).__name__}, {type(src).__name__}")

    def add(self, dst: Operand, src: Operand) -> None:
        if isinstance(dst, X86_64Reg) and isinstance(src, X86_64Reg):
            # ADD r/m64, r64 — REX.W + 01 /r
            rex   = self._rex(w=True, r=src.extended, b=dst.extended)
            modrm = self._modrm(0b11, src.index, dst.index)
            self._emit(rex, 0x01, modrm)

        elif isinstance(dst, X86_64Reg) and isinstance(src, Imm):
            # ADD r/m64, imm32 — REX.W + 81 /0 + imm32
            rex   = self._rex(w=True, b=dst.extended)
            modrm = self._modrm(0b11, 0, dst.index)
            self._emit(rex, 0x81, modrm)
            self._buf.extend(struct.pack('<i', src.value))

        else:
            raise NotImplementedError(
                f"add {type(dst).__name__}, {type(src).__name__}")

    def mul(self, dst: Operand, src: Operand, imm=None) -> None:
        if isinstance(dst, X86_64Reg) and isinstance(src, X86_64Reg):
            if imm is not None:
                # IMUL r64, r/m64, imm32 — dst = src * imm  (3-operand)
                rex   = self._rex(w=True, r=dst.extended, b=src.extended)
                modrm = self._modrm(0b11, dst.index, src.index)
                self._emit(rex, 0x69, modrm)
                self._buf.extend(struct.pack('<i', imm.value))
            else:
                # IMUL r64, r/m64 — dst *= src              (2-operand)
                rex   = self._rex(w=True, r=dst.extended, b=src.extended)
                modrm = self._modrm(0b11, dst.index, src.index)
                self._emit(rex, 0x0F, 0xAF, modrm)
        else:
            raise NotImplementedError(
                f"mul {type(dst).__name__}, {type(src).__name__}")

    def sub(self, dst: Operand, src: Operand) -> None:
        if isinstance(dst, X86_64Reg) and isinstance(src, X86_64Reg):
            # SUB r/m64, r64 — REX.W + 29 /r
            rex   = self._rex(w=True, r=src.extended, b=dst.extended)
            modrm = self._modrm(0b11, src.index, dst.index)
            self._emit(rex, 0x29, modrm)

        elif isinstance(dst, X86_64Reg) and isinstance(src, Imm):
            # SUB r/m64, imm32 — REX.W + 81 /5 + imm32
            rex   = self._rex(w=True, b=dst.extended)
            modrm = self._modrm(0b11, 5, dst.index)
            self._emit(rex, 0x81, modrm)
            self._buf.extend(struct.pack('<i', src.value))

        else:
            raise NotImplementedError(
                f"sub {type(dst).__name__}, {type(src).__name__}")

    def push(self, src: Operand) -> None:
        if isinstance(src, X86_64Reg):
            # PUSH r64 — [REX.B] + (50+rd)
            # REX.W not needed; PUSH is implicitly 64-bit in 64-bit mode.
            if src.extended:
                self._emit(self._rex(w=False, b=True))
            self._emit(0x50 | (src.index & 7))

        else:
            raise NotImplementedError(f"push {type(src).__name__}")

    def pop(self, dst: Operand) -> None:
        if isinstance(dst, X86_64Reg):
            # POP r64 — [REX.B] + (58+rd)
            if dst.extended:
                self._emit(self._rex(w=False, b=True))
            self._emit(0x58 | (dst.index & 7))

        else:
            raise NotImplementedError(f"pop {type(dst).__name__}")

    def cmp(self, dst: Operand, src: Operand) -> None:
        if isinstance(dst, X86_64Reg) and isinstance(src, X86_64Reg):
            # CMP r/m64, r64 — REX.W + 39 /r  (computes dst - src)
            rex   = self._rex(w=True, r=src.extended, b=dst.extended)
            modrm = self._modrm(0b11, src.index, dst.index)
            self._emit(rex, 0x39, modrm)
        elif isinstance(dst, X86_64Reg) and isinstance(src, Imm):
            # CMP r/m64, imm32 — REX.W + 81 /7 + imm32
            rex   = self._rex(w=True, b=dst.extended)
            modrm = self._modrm(0b11, 7, dst.index)
            self._emit(rex, 0x81, modrm)
            self._buf.extend(struct.pack('<i', src.value))
        else:
            raise NotImplementedError(
                f"cmp {type(dst).__name__}, {type(src).__name__}")

    def jge(self, label_id: int) -> None:
        # JGE rel32 — 0F 8D + rel32
        self._emit(0x0F, 0x8D)
        self._register_fixup(label_id)

    def jle(self, label_id: int) -> None:
        # JLE rel32 — 0F 8E + rel32
        self._emit(0x0F, 0x8E)
        self._register_fixup(label_id)

    def jne(self, label_id: int) -> None:
        # JNE rel32 — 0F 85 + rel32
        self._emit(0x0F, 0x85)
        self._register_fixup(label_id)

    def jmp(self, label_id: int) -> None:
        # JMP rel32 — E9 + rel32
        self._emit(0xE9)
        self._register_fixup(label_id)

    def place_label(self, label_id: int) -> None:
        self._resolve_label(label_id)

    def emit_prologue(self, frame_size: int) -> None:
        """Emit function prologue: save registers, set up frame, allocate spills.

        Stack layout after prologue:
            [rbp + 0]   saved rbp
            [rbp - 8]   spill slot 0
            [rbp - 16]  spill slot 1  ...
        Scratch registers (r14, r15) are saved via push before rbp is set.
        """
        # push rbp / push r14 / push r15
        self.push(regs.RBP)
        self.push(regs.R14)
        self.push(regs.R15)
        # mov rbp, rsp — REX.W + 89 /r  (stores rsp into rbp)
        # ModRM: mod=11, reg=RSP(4), rm=RBP(5) = 0xE5
        self._emit(0x48, 0x89, 0xE5)
        # sub rsp, frame_size
        if frame_size > 0:
            if frame_size <= 127:
                self._emit(0x48, 0x83, 0xEC, frame_size)
            else:
                self._emit(0x48, 0x81, 0xEC)
                self._buf.extend(struct.pack('<I', frame_size))

    def emit_epilogue(self) -> None:
        """Emit function epilogue: restore registers, return."""
        # mov rsp, rbp — REX.W + 89 /r  (stores rbp into rsp)
        # ModRM: mod=11, reg=RBP(5), rm=RSP(4) = 0xEC
        self._emit(0x48, 0x89, 0xEC)
        # pop r15 / pop r14 / pop rbp
        self.pop(regs.R15)
        self.pop(regs.R14)
        self.pop(regs.RBP)
        self.ret()

    def load_spill(self, dst: Operand, slot) -> None:
        """Emit  mov dst, [rbp + slot.offset]  (spill reload)."""
        assert isinstance(dst, X86_64Reg)
        # MOV r64, r/m64 (8B /r) with mod=10 (disp32), rm=RBP(5)
        rex   = self._rex(w=True, r=dst.extended, b=False)
        modrm = self._modrm(0b10, dst.index, 5)   # rm=5 → RBP
        self._emit(rex, 0x8B, modrm)
        self._buf.extend(struct.pack('<i', slot.offset))

    def store_spill(self, src: Operand, slot) -> None:
        """Emit  mov [rbp + slot.offset], src  (spill store)."""
        assert isinstance(src, X86_64Reg)
        # MOV r/m64, r64 (89 /r) with mod=10 (disp32), rm=RBP(5)
        rex   = self._rex(w=True, r=src.extended, b=False)
        modrm = self._modrm(0b10, src.index, 5)   # rm=5 → RBP
        self._emit(rex, 0x89, modrm)
        self._buf.extend(struct.pack('<i', slot.offset))

    def ret(self) -> None:
        # RET (near) — C3
        self._emit(0xC3)
