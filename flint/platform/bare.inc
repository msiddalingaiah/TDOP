; =============================================================================
; platform/bare.inc — Bare-metal x86-64 platform layer for Flint  (STUB)
;
; Targets x86-64 in 64-bit long mode with a flat identity-mapped address space.
; Expects a Multiboot-compatible bootloader (GRUB etc.).
; I/O via COM1 serial port (0x3F8) at 38400 baud, 8N1.
;
; To complete: add Multiboot header, linker script, memory detection.
; =============================================================================

format binary
use64

COM1_BASE       = 0x3F8

; Arena placed at 2 MB physical — safe above typical kernel load address.
; Adjust ARENA_BASE to suit your memory map.
ARENA_BASE      = 0x00200000

sys.init:
    ; Configure COM1: 38400 baud, 8N1
    mov  dx, COM1_BASE + 1
    xor  al, al
    out  dx, al                 ; disable interrupts

    mov  dx, COM1_BASE + 3
    mov  al, 0x80
    out  dx, al                 ; set DLAB (access baud rate divisor)

    mov  dx, COM1_BASE + 0
    mov  al, 3                  ; divisor low byte  (115200 / 38400 = 3)
    out  dx, al

    mov  dx, COM1_BASE + 1
    xor  al, al
    out  dx, al                 ; divisor high byte

    mov  dx, COM1_BASE + 3
    mov  al, 0x03               ; 8 data bits, 1 stop, no parity; clear DLAB
    out  dx, al

    mov  rax, ARENA_BASE
    ret

sys.emit:
    push rdx
    push rax
    mov  dx, COM1_BASE + 5
.wait_tx:
    in   al, dx
    test al, 0x20               ; TX holding register empty?
    jz   .wait_tx
    pop  rax
    mov  dx, COM1_BASE
    out  dx, al
    pop  rdx
    ret

sys.key:
    push rdx
    mov  dx, COM1_BASE + 5
.wait_rx:
    in   al, dx
    test al, 0x01               ; data ready?
    jz   .wait_rx
    mov  dx, COM1_BASE
    in   al, dx
    pop  rdx
    ret

sys.exit:
    cli
.halt:
    hlt
    jmp  .halt
