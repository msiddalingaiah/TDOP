; =============================================================================
; flint.asm — Flint FORTH, top-level assembly file
;
; Build (Windows, primary target):
;   fasm flint.asm flint.exe
;   fasm -d TARGET=windows flint.asm flint.exe   (explicit)
;
; Build (Linux, stub):
;   fasm -d TARGET=linux flint.asm flint
;
; Build (bare-metal, stub):
;   fasm -d TARGET=bare flint.asm flint.bin
;
; Requires: FASM 1.73 or later  (https://flatassembler.net)
; =============================================================================

; --- compile-time configuration and macros (no code emitted yet) ------------
include 'config.inc'
include 'macros.inc'

; --- platform layer ----------------------------------------------------------
; This include sets the binary FORMAT directive, the import table (.idata),
; platform-mutable state (.data), and the sys.* function bodies (.text).
; It MUST come before any section that emits code, because FORMAT must be
; the very first effective directive in the assembled output.

include 'platform/detect.inc'

; =============================================================================
; .text section — all primitive words, helpers, and startup code
;
; defword entries are emitted in .text; their headers (link + name) and
; their code all land in this section.  Because FASM re-opens an existing
; section when it sees the same name again, this appends to the .text that
; the platform layer already started.
; =============================================================================

section '.text' code readable executable

    include 'primitives.inc'    ; kernel words (updates FLINT_LATEST)
    include 'dict.inc'          ; find, compile helpers, number output
    include 'boot.inc'          ; entry point, QUIT loop, input

; =============================================================================
; .data section — mutable runtime state
;
; Placed AFTER the primitives include so that FLINT_LATEST has its final value
; by the time the `dq FLINT_LATEST` line is assembled.
; =============================================================================

section '.data' data readable writeable

    ; interpreter state
    flint.state         dq  0           ; 0 = interpret, 1 = compile
    flint.base          dq  10          ; current number base (10 or 16)

    ; stack bottom — saved at startup for .S and DEPTH
    flint.dstack_base   dq  0

    ; arena metadata
    flint.arena_end     dq  0

    ; compiler state — set/read by : ; RECURSE VARIABLE CONSTANT
    current_word_hdr    dq  0           ; address of header being compiled
    current_word_cfa    dq  0           ; address of CFA being compiled

    ; static dictionary tail — initialised from assembly-time FLINT_LATEST
    ; (which captures the address of the very last defword in primitives.inc)
    flint.latest_static dq  FLINT_LATEST

    ; input buffer
    ibuf                rb  IBUF_SIZE
    ibuf_len            dq  0
    ibuf_pos            dq  0

    ; word parse buffer
    wbuf                rb  WBUF_SIZE
    wbuf_len            dq  0

    ; scratch buffer used by flint.print_num / flint.print_unum
    num_buf             rb  24
