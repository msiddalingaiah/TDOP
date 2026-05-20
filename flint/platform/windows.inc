; =============================================================================
; platform/windows.inc -- Win32 platform layer for Flint
;
; Import table is built by hand (raw PE64 idata structures) so that no
; external FASM include files (win64ax.inc etc.) are required.
;
; Calling convention: Microsoft x64
;   Args 1-4 : RCX  RDX  R8  R9
;   Args 5+  : [RSP+32]  [RSP+40]  ...
;   Caller allocates 32 bytes shadow space before any CALL.
;   RSP must be 16-byte aligned at the CALL instruction.
;   Callee-saved: RBX RBP RSI RDI R12-R15  (all Flint regs -- safe)
;
; sys.* functions enforce alignment internally; FORTH callers need not care.
; =============================================================================

format PE64 console
entry  flint.start

; =============================================================================
; .idata section -- PE64 import table (built manually)
;
; Layout:
;   IMAGE_IMPORT_DESCRIPTOR array  (20 bytes each, null-terminated)
;   IAT / INT  (8-byte ULONGLONG entries, null-terminated)
;   DLL name string
;   IMAGE_IMPORT_BY_NAME entries  (WORD hint + BYTE name[])
; =============================================================================

section '.idata' import data readable

; --- Import Directory Table (IMAGE_IMPORT_DESCRIPTOR x 1 + null sentinel) ---
;
;   OriginalFirstThunk : dd  RVA of INT  (we reuse the IAT for both)
;   TimeDateStamp      : dd  0
;   ForwarderChain     : dd  0
;   Name               : dd  RVA of DLL name string
;   FirstThunk         : dd  RVA of IAT  (loader fills these with actual addrs)

  dd RVA kernel32_iat, 0, 0, RVA kernel32_name, RVA kernel32_iat
  dd 0, 0, 0, 0, 0                ; null sentinel (end of directory)

; --- IAT / INT  (8 bytes per entry; bit63=0 -> import-by-name) --------------
align 8
kernel32_iat:
GetStdHandle  dq RVA _h_GetStdHandle
WriteFile     dq RVA _h_WriteFile
ReadFile      dq RVA _h_ReadFile
VirtualAlloc  dq RVA _h_VirtualAlloc
ExitProcess   dq RVA _h_ExitProcess
              dq 0                ; null terminator

; --- DLL name ----------------------------------------------------------------
kernel32_name db 'kernel32.dll', 0

; --- IMAGE_IMPORT_BY_NAME entries  (hint WORD + name BYTE[]) ----------------
_h_GetStdHandle  dw 0
                 db 'GetStdHandle',  0
_h_WriteFile     dw 0
                 db 'WriteFile',     0
_h_ReadFile      dw 0
                 db 'ReadFile',      0
_h_VirtualAlloc  dw 0
                 db 'VirtualAlloc',  0
_h_ExitProcess   dw 0
                 db 'ExitProcess',   0

; =============================================================================
; Win32 constants
; =============================================================================

STD_INPUT_HANDLE        = -10
STD_OUTPUT_HANDLE       = -11
MEM_COMMIT              = 0x00001000
MEM_RESERVE             = 0x00002000
PAGE_EXECUTE_READWRITE  = 0x40

; =============================================================================
; Platform state
; =============================================================================

section '.data' data readable writeable

sys.hStdOut   dq 0
sys.hStdIn    dq 0
sys.nWritten  dd 0
sys.nRead     dd 0
sys.emit.buf  db 0
sys.key.buf   db 0

; =============================================================================
; Platform code
; =============================================================================

section '.text' code readable executable

; -----------------------------------------------------------------------------
; sys.init -- acquire handles, allocate arena
; Returns: RAX = arena base (PAGE_EXECUTE_READWRITE), 0 on failure
; -----------------------------------------------------------------------------
sys.init:
    push rbp
    mov  rbp, rsp
    and  rsp, -16
    sub  rsp, 32

    mov  rcx, STD_OUTPUT_HANDLE
    call [GetStdHandle]
    mov  [sys.hStdOut], rax

    mov  rcx, STD_INPUT_HANDLE
    call [GetStdHandle]
    mov  [sys.hStdIn], rax

    xor  rcx, rcx
    mov  rdx, ARENA_SIZE
    mov  r8,  MEM_COMMIT or MEM_RESERVE
    mov  r9,  PAGE_EXECUTE_READWRITE
    call [VirtualAlloc]

    mov  rsp, rbp
    pop  rbp
    ret

; -----------------------------------------------------------------------------
; sys.emit -- write byte in AL to stdout
; Preserves all registers.
; -----------------------------------------------------------------------------
sys.emit:
    push rbp
    mov  rbp, rsp
    and  rsp, -16
    sub  rsp, 48                 ; 32 shadow + 8 fifth-arg + 8 align pad

    mov  [sys.emit.buf], al

    mov  rcx, [sys.hStdOut]
    lea  rdx, [sys.emit.buf]
    mov  r8d, 1
    lea  r9,  [sys.nWritten]
    mov  qword [rsp+32], 0       ; lpOverlapped = NULL (5th arg)
    call [WriteFile]

    mov  rsp, rbp
    pop  rbp
    ret

; -----------------------------------------------------------------------------
; sys.key -- blocking read of one byte from stdin into AL
; -----------------------------------------------------------------------------
sys.key:
    push rbp
    mov  rbp, rsp
    and  rsp, -16
    sub  rsp, 48

    mov  rcx, [sys.hStdIn]
    lea  rdx, [sys.key.buf]
    mov  r8d, 1
    lea  r9,  [sys.nRead]
    mov  qword [rsp+32], 0
    call [ReadFile]

    mov  al, [sys.key.buf]

    mov  rsp, rbp
    pop  rbp
    ret

; -----------------------------------------------------------------------------
; sys.exit -- terminate process; RCX = exit code; does not return
; -----------------------------------------------------------------------------
sys.exit:
    and  rsp, -16
    sub  rsp, 32
    call [ExitProcess]
