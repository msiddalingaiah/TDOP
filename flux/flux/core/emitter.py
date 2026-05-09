from __future__ import annotations
import struct
from abc import ABC, abstractmethod

from flux.core.operands import Operand
from flux.core.target import Target


class Emitter(ABC):
    """Architecture-neutral emitter interface."""

    def __init__(self, target: Target) -> None:
        self.target = target
        self._buf:       bytearray       = bytearray()
        self._label_pos: dict[int, int]  = {}
        self._fixups:    dict[int, list] = {}

    def get_code(self) -> bytes:
        return bytes(self._buf)

    def _emit(self, *bytes_: int) -> None:
        self._buf.extend(bytes_)

    # ------------------------------------------------------------------
    # Label fixup helpers
    # ------------------------------------------------------------------

    def _register_fixup(self, label_id: int) -> None:
        """Append a 4-byte offset field and resolve it, handling both
        forward references (patch when label is placed later) and backward
        references (label already placed — compute offset immediately)."""
        fixup_pos = len(self._buf)

        if label_id in self._label_pos:
            # Backward reference: label already placed, resolve immediately.
            target = self._label_pos[label_id]
            source = fixup_pos + 4          # address of instruction after jump
            offset = target - source        # signed relative offset
            self._buf.extend(struct.pack('<i', offset))
        else:
            # Forward reference: write placeholder and record for later.
            if label_id not in self._fixups:
                self._fixups[label_id] = []
            self._fixups[label_id].append(fixup_pos)
            self._buf.extend(b'\x00\x00\x00\x00')

    def _resolve_label(self, label_id: int) -> None:
        """Record the current position as label_id's address and patch fixups."""
        pos = len(self._buf)
        self._label_pos[label_id] = pos
        for fixup in self._fixups.get(label_id, []):
            source = fixup + 4
            offset = pos - source
            struct.pack_into('<i', self._buf, fixup, offset)

    # ------------------------------------------------------------------
    # Arithmetic
    # ------------------------------------------------------------------

    @abstractmethod
    def mov(self, dst: Operand, src: Operand) -> None: ...

    @abstractmethod
    def add(self, dst: Operand, src: Operand) -> None: ...

    @abstractmethod
    def mul(self, dst: Operand, src: Operand, imm=None) -> None: ...

    @abstractmethod
    def div(self, dst: Operand, lhs: Operand, rhs: Operand) -> None: ...

    @abstractmethod
    def mod(self, dst: Operand, lhs: Operand, rhs: Operand) -> None: ...

    @abstractmethod
    def band(self, dst: Operand, src: Operand) -> None: ...

    @abstractmethod
    def bor(self, dst: Operand, src: Operand) -> None: ...

    @abstractmethod
    def bxor(self, dst: Operand, src: Operand) -> None: ...

    @abstractmethod
    def shl(self, dst: Operand, src: Operand) -> None: ...

    @abstractmethod
    def shr(self, dst: Operand, src: Operand) -> None: ...

    @abstractmethod
    def sub(self, dst: Operand, src: Operand) -> None: ...

    @abstractmethod
    def push(self, src: Operand) -> None: ...

    @abstractmethod
    def pop(self, dst: Operand) -> None: ...

    # ------------------------------------------------------------------
    # Comparison and control flow
    # ------------------------------------------------------------------

    @abstractmethod
    def cmp(self, dst: Operand, src: Operand) -> None: ...

    @abstractmethod
    def jge(self, label_id: int) -> None: ...

    @abstractmethod
    def jle(self, label_id: int) -> None: ...

    @abstractmethod
    def jne(self, label_id: int) -> None: ...

    @abstractmethod
    def jmp(self, label_id: int) -> None: ...

    @abstractmethod
    def place_label(self, label_id: int) -> None: ...

    @abstractmethod
    def ret(self) -> None: ...

    # ------------------------------------------------------------------
    # Stack frame and spill support
    # ------------------------------------------------------------------

    @abstractmethod
    def emit_prologue(self, frame_size: int) -> None: ...

    @abstractmethod
    def emit_epilogue(self) -> None: ...

    @abstractmethod
    def load_spill(self, dst: Operand, slot) -> None: ...

    @abstractmethod
    def store_spill(self, src: Operand, slot) -> None: ...
