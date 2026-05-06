"""
Platform-agnostic helper for executing generated machine code in memory.
Supports Windows (VirtualAlloc) and Linux/macOS (mmap).
"""
from __future__ import annotations
import sys
import ctypes
from typing import Any, Tuple


if sys.platform == "win32":
    import ctypes.wintypes

    _MEM_COMMIT             = 0x1000
    _MEM_RESERVE            = 0x2000
    _MEM_RELEASE            = 0x8000
    _PAGE_EXECUTE_READWRITE = 0x40

    _k32 = ctypes.windll.kernel32
    _k32.VirtualAlloc.restype  = ctypes.c_void_p
    _k32.VirtualFree.argtypes  = [ctypes.c_void_p,
                                   ctypes.c_size_t,
                                   ctypes.wintypes.DWORD]

    def make_callable(code: bytes,
                      restype=ctypes.c_int64,
                      *argtypes) -> Tuple[Any, Any]:
        ptr = _k32.VirtualAlloc(None, len(code),
                                _MEM_COMMIT | _MEM_RESERVE,
                                _PAGE_EXECUTE_READWRITE)
        if not ptr:
            raise MemoryError("VirtualAlloc failed")
        ctypes.memmove(ptr, code, len(code))
        ftype = ctypes.CFUNCTYPE(restype, *argtypes)
        return ftype(ptr), ptr

    def free_code(handle: Any) -> None:
        _k32.VirtualFree(handle, 0, _MEM_RELEASE)

else:
    import mmap as _mmap

    def make_callable(code: bytes,
                      restype=ctypes.c_int64,
                      *argtypes) -> Tuple[Any, Any]:
        mem = _mmap.mmap(-1, len(code),
                         prot  = _mmap.PROT_READ | _mmap.PROT_WRITE | _mmap.PROT_EXEC,
                         flags = _mmap.MAP_PRIVATE | _mmap.MAP_ANONYMOUS)
        mem.write(code)
        addr  = ctypes.addressof(ctypes.c_char.from_buffer(mem))
        ftype = ctypes.CFUNCTYPE(restype, *argtypes)
        return ftype(addr), mem

    def free_code(handle: Any) -> None:
        handle.close()
