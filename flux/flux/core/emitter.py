from __future__ import annotations
from abc import ABC, abstractmethod

from flux.core.operands import Operand
from flux.core.target import Target


_Imm = None   # forward reference; avoid circular import


class Emitter(ABC):
    """Architecture-neutral emitter interface."""

    def __init__(self, target: Target) -> None:
        self.target = target
        self._buf: bytearray = bytearray()

    def get_code(self) -> bytes:
        return bytes(self._buf)

    def _emit(self, *bytes_: int) -> None:
        self._buf.extend(bytes_)

    @abstractmethod
    def mov(self, dst: Operand, src: Operand) -> None: ...

    @abstractmethod
    def add(self, dst: Operand, src: Operand) -> None: ...

    @abstractmethod
    def mul(self, dst: Operand, src: Operand, imm=None) -> None: ...

    @abstractmethod
    def sub(self, dst: Operand, src: Operand) -> None: ...

    @abstractmethod
    def push(self, src: Operand) -> None: ...

    @abstractmethod
    def pop(self, dst: Operand) -> None: ...

    @abstractmethod
    def ret(self) -> None: ...
