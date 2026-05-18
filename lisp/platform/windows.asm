; =============================================================================
; platform/windows.asm - Windows x64 HAL implementation
;
; Included by main.asm when PLATFORM = PLATFORM_WINDOWS.
; Requires main.asm to have already included 'win64ax.inc' so that
; the 'library' and 'import' macros are available.
;
; Win32 functions used:
;   kernel32: GetStdHandle, WriteFile, ReadFile,
;             GetProcessHeap, HeapAlloc, ExitProcess
;
; Stack discipline:
;   Every procedure here is called with RSP mod 16 = 8 (standard: the
;   CALL instruction pushed the return address). Each proc does:
;
;       push rbx          ; saves rbx, aligns RSP to 0 mod 16
;       sub  rsp, 32      ; 32-byte shadow space  -> still 0 mod 16
;    [or sub rsp, 48 when a 5th stack argument is needed]
;       ...
;       add  rsp, 32/48
;       pop  rbx
;       ret
; =============================================================================

; ── Import table ─────────────────────────────────────────────────────────────

section '.idata' import data readable writeable

    library kernel32, 'kernel32.dll'

    import kernel32,                        \
        GetStdHandle,   'GetStdHandle',     \
        WriteFile,      'WriteFile',        \
        ReadFile,       'ReadFile',         \
        GetProcessHeap, 'GetProcessHeap',   \
        HeapAlloc,      'HeapAlloc',        \
        ExitProcess,    'ExitProcess'

; ── Platform data ─────────────────────────────────────────────────────────────

section '.data' data readable writeable

    _hal_stdout   dq 0          ; HANDLE for stdout
    _hal_stdin    dq 0          ; HANDLE for stdin
    _hal_heap     dq 0          ; HANDLE for process heap

    _hal_iobuf    db 0          ; single-byte I/O staging buffer
    _hal_iocount  dd 0          ; DWORD: bytes transferred (WriteFile / ReadFile)

; ── HAL procedures ────────────────────────────────────────────────────────────

section '.code' code readable executable

; -----------------------------------------------------------------------------
; hal_init — acquire stdout, stdin, and heap handles
; -----------------------------------------------------------------------------
hal_init:
    push rbx
    sub  rsp, 32

    mov  ecx, -11               ; STD_OUTPUT_HANDLE
    call [GetStdHandle]
    mov  [_hal_stdout], rax

    mov  ecx, -10               ; STD_INPUT_HANDLE
    call [GetStdHandle]
    mov  [_hal_stdin], rax

    call [GetProcessHeap]
    mov  [_hal_heap], rax

    add  rsp, 32
    pop  rbx
    ret

; -----------------------------------------------------------------------------
; hal_write_char — write a single character to stdout
; In: cl = character
; -----------------------------------------------------------------------------
hal_write_char:
    push rbx
    ; sub 48: shadow(32) + arg5 slot(8) + alignment pad(8) = 48, keeps RSP 0 mod 16
    sub  rsp, 48

    mov  [_hal_iobuf], cl

    mov  rcx, [_hal_stdout]     ; hFile
    lea  rdx, [_hal_iobuf]      ; lpBuffer
    mov  r8d, 1                 ; nNumberOfBytesToWrite
    lea  r9,  [_hal_iocount]    ; lpNumberOfBytesWritten
    mov  qword [rsp+32], 0      ; lpOverlapped = NULL  (5th arg)
    call [WriteFile]

    add  rsp, 48
    pop  rbx
    ret

; -----------------------------------------------------------------------------
; hal_write_string — write a byte string to stdout
; In: rcx = pointer to bytes
;     rdx = length in bytes
; -----------------------------------------------------------------------------
hal_write_string:
    push rbx
    sub  rsp, 48

    ; Rearrange arguments for WriteFile(stdout, buf, len, &count, NULL)
    ; Order matters: save rdx first so rcx can be overwritten safely.
    mov  r8,  rdx               ; r8  = length
    mov  rdx, rcx               ; rdx = buffer pointer
    mov  rcx, [_hal_stdout]     ; rcx = handle
    lea  r9,  [_hal_iocount]
    mov  qword [rsp+32], 0
    call [WriteFile]

    add  rsp, 48
    pop  rbx
    ret

; -----------------------------------------------------------------------------
; hal_read_char — read one character from stdin (blocking)
; Out: al = character read
; -----------------------------------------------------------------------------
hal_read_char:
    push rbx
    sub  rsp, 48

    mov  rcx, [_hal_stdin]      ; hFile
    lea  rdx, [_hal_iobuf]      ; lpBuffer
    mov  r8d, 1                 ; nNumberOfBytesToRead
    lea  r9,  [_hal_iocount]    ; lpNumberOfBytesRead
    mov  qword [rsp+32], 0      ; lpOverlapped = NULL
    call [ReadFile]

    movzx eax, byte [_hal_iobuf]

    add  rsp, 48
    pop  rbx
    ret

; -----------------------------------------------------------------------------
; hal_alloc — allocate a zeroed block from the process heap
; In:  rcx = size in bytes
; Out: rax = pointer, or 0 on failure
; -----------------------------------------------------------------------------
hal_alloc:
    push rbx
    sub  rsp, 32

    mov  rbx, rcx               ; stash size (rcx needed for heap handle)
    mov  rcx, [_hal_heap]       ; hHeap
    mov  rdx, 8                 ; dwFlags = HEAP_ZERO_MEMORY
    mov  r8,  rbx               ; dwBytes
    call [HeapAlloc]
    ; rax = pointer or NULL — already the right return value

    add  rsp, 32
    pop  rbx
    ret

; -----------------------------------------------------------------------------
; hal_exit — terminate the process
; In: rcx = exit code  (does not return)
; -----------------------------------------------------------------------------
hal_exit:
    ; ExitProcess never returns; alignment doesn't matter here.
    call [ExitProcess]
