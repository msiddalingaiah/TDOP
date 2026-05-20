; =============================================================================
; platform/linux.inc — Linux syscall platform layer for Flint  (STUB)
;
; Uses raw syscalls — no libc dependency.
; To complete: test on x86-64 Linux, verify syscall numbers, add mmap flags.
; =============================================================================

format ELF64 executable
entry  flint.start

SYS_READ        = 0
SYS_WRITE       = 1
SYS_MMAP        = 9
SYS_EXIT        = 60

MMAP_PROT_RWX   = 7         ; PROT_READ | PROT_WRITE | PROT_EXEC
MMAP_MAP_FLAGS  = 0x22       ; MAP_PRIVATE | MAP_ANONYMOUS

segment readable writeable
sys.emit.buf    db 0
sys.key.buf     db 0

segment readable executable

sys.init:
    xor  rdi, rdi
    mov  rsi, ARENA_SIZE
    mov  rdx, MMAP_PROT_RWX
    mov  r10, MMAP_MAP_FLAGS
    mov  r8,  -1
    xor  r9,  r9
    mov  rax, SYS_MMAP
    syscall
    ; rax = base address or MAP_FAILED (-1)
    ret

sys.emit:
    mov  [sys.emit.buf], al
    mov  rax, SYS_WRITE
    mov  rdi, 1
    lea  rsi, [sys.emit.buf]
    mov  rdx, 1
    syscall
    ret

sys.key:
    mov  rax, SYS_READ
    xor  rdi, rdi
    lea  rsi, [sys.key.buf]
    mov  rdx, 1
    syscall
    mov  al, [sys.key.buf]
    ret

sys.exit:
    mov  rax, SYS_EXIT
    syscall
