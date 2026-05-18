; =============================================================================
; main.asm - Entry point for the Clojure-like LISP interpreter
;
; Assemble with FASM:
;   fasm main.asm lisp.exe
; =============================================================================

format PE64 console
entry lisp_start

include 'win64ax.inc'

include 'config.inc'
include 'defs.inc'
include 'platform/interface.inc'

if PLATFORM = PLATFORM_WINDOWS
    include 'platform/windows.asm'
else
    error 'Unsupported platform'
end if

include 'tokenizer.asm'
include 'memory.asm'
include 'parser.asm'
include 'printer.asm'
include 'env.asm'
include 'eval.asm'
include 'primitives.asm'

; =============================================================================
; Read-only data
; =============================================================================

section '.rdata' data readable

    msg_banner  db 'clisp v0.0.1', 13, 10
    msg_banner_len = $ - msg_banner

    msg_prompt  db '> '
    msg_prompt_len = $ - msg_prompt

; =============================================================================
; Entry point
; =============================================================================

section '.code' code readable executable

lisp_start:
    ; On entry RSP is 8-byte misaligned (Windows loader used CALL).
    ; Subtract 8 to align for the lifetime of this frame.
    sub rsp, 8

    call hal_init

    ; Seed the global env with nil, then populate all built-in primitives.
    lea  rax, [_cell_nil]
    mov  [_global_env], rax
    call primitives_init

    lea  rcx, [msg_banner]
    mov  rdx, msg_banner_len
    call hal_write_string

    ; ── REPL ──────────────────────────────────────────────────────────────
    ; parse_next returns 0 on EOF (Ctrl-Z on Windows); anything else is a Cell*.
    ; Each expression is evaluated in the current global environment.
.repl:
    lea  rcx, [msg_prompt]
    mov  rdx, msg_prompt_len
    call hal_write_string

    call parse_next         ; rax = Cell* or 0
    test rax, rax
    jz   .exit

    mov  rcx, rax
    mov  rdx, [_global_env]
    call eval_cell          ; rax = result Cell*

    mov  rcx, rax
    call print_cell

    mov  cl,  10
    call hal_write_char     ; newline after each result

    jmp  .repl

.exit:
    mov  cl,  10
    call hal_write_char

    xor  rcx, rcx
    call hal_exit
