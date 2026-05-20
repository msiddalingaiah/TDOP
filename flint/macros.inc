; =============================================================================
; macros.inc — assembler macros for Flint
; =============================================================================
;
; Register contract (all callee-saved under both Win64 and SysV ABI):
;
;   RSP   native call stack  — STC return addresses; do NOT alias this
;   R15   data stack pointer — [R15] = TOS, grows downward
;   R14   HERE               — dictionary write cursor, grows upward
;   R13   LATEST             — most recently defined word's header address
;   R12   return stack ptr   — FORTH >R / R> values, grows downward
;   RBX   scratch            — free for use within a primitive
;
; In STC (subroutine-threaded code) every FORTH word is a callable function.
; Colon definitions are sequences of CALL instructions ending with RET.
; No NEXT macro or instruction pointer register is required.
; =============================================================================

; --- dictionary chain variable (numeric, updated at assembly time) -----------
FLINT_LATEST    = 0         ; null sentinel — no words defined yet

; --- defword label, "name", flags -------------------------------------------
;
; Emits a dictionary header then aligns to CELL for the word's code.
; The word's entry point (CFA in Forth parlance) is `label`.
;
; Header layout in memory:
;   [  link : 8 bytes  |  flags|len : 1 byte  |  name : len bytes  |  pad  ]
;   label:   ← code begins here (aligned to CELL)
;
; Usage:
;   defword PLUS, "+", 0
;       ...code...
;       ret

macro defword _label, _name, _flags {
    local _hdr, _nlen

    ; compute name length at assembly time using a virtual block
    virtual at 0
        db _name
        _nlen = $
    end virtual

    align CELL
    _hdr:
        dq  FLINT_LATEST        ; link → previous header (0 = end of chain)
        db  (_flags) or _nlen   ; flags byte: high bits = flags, low 5 = length
        db  _name               ; name string (not null-terminated)
    FLINT_LATEST = _hdr         ; update chain to this header

    align CELL
    w_#_label:                  ; word entry point (w_ prefix avoids FASM reserved words)
}

; --- data stack helpers ------------------------------------------------------
; These are used in non-primitive helpers (boot.inc, dict.inc) where
; inline macros read more clearly than raw register arithmetic.

macro dpush _reg {
    sub  r15, CELL
    mov  [r15], _reg
}

macro dpop _reg {
    mov  _reg, [r15]
    add  r15, CELL
}

macro dpeek _reg {
    mov  _reg, [r15]
}

; --- runtime code-emission helpers -------------------------------------------
; Used by the colon compiler and control-flow words to emit machine code
; into the dictionary at runtime (R14 = current write position).
;
; flint.compile_call (in dict.inc) emits a rel32 or abs64 CALL.
; flint.compile_lit  (in dict.inc) emits the lit_helper trick.
; Individual control-flow words emit branch sequences directly.
;
; Branch sequences emitted by IF / WHILE / UNTIL use this 16-byte template:
;
;   48 8B 07            mov rax, [r15]          ; read TOS
;   49 83 C7 08         add r15, 8              ; drop TOS
;   48 85 C0            test rax, rax           ; set flags
;   0F 84 xx xx xx xx  jz  rel32               ; conditional branch
;
; The rel32 field starts at offset 12 from the start of the sequence.
; THEN / REPEAT backpatch [patch_addr] with the computed offset.

BRANCH_SEQ_LEN   = 16       ; bytes emitted by IF / WHILE / UNTIL preamble
BRANCH_REL_OFF   = 12       ; byte offset of the rel32 field within the sequence
