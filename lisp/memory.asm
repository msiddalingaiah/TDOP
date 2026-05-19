; =============================================================================
; memory.asm - Typed heap allocation
;
; All procedures follow the HAL calling convention (rcx/rdx/r8/r9 in,
; rax out, rbx/r12-r15 preserved).
;
; Stack alignment rule used throughout:
;   N pushes + sub rsp, M  where  (N*8 + M) mod 16 = 0
;     1 push  →  sub rsp, 8·(2k)     e.g. 32, 48 …
;     2 pushes →  sub rsp, 8·(2k+1)  e.g. 8, 24, 40 …
;     3 pushes →  sub rsp, 8·(2k)    e.g. 32, 48 …
;
; Public:
;   make_int    rcx=value      → rax=Cell*   (TAG_INT)
;   make_sym    rcx=ptr rdx=len→ rax=Cell*   (TAG_SYM)
;   make_cons   rcx=car rdx=cdr→ rax=Cell*   (TAG_CONS)
;   make_atom   rcx=ptr rdx=len→ rax=Cell*   (TAG_INT or TAG_SYM)
;
; Singletons (static addresses — never freed):
;   _cell_nil, _cell_true, _cell_false
; =============================================================================

; ── Singleton values (no allocation needed) ───────────────────────────────────

section '.data' data readable writeable

    _cell_nil:
        dq TAG_NIL,  0

    _cell_true:
        dq TAG_BOOL, 1

    _cell_false:
        dq TAG_BOOL, 0

; ── Internal helpers ─────────────────────────────────────────────────────────

section '.code' code readable executable

; cell_alloc — allocate one uninitialised Cell (CELL_SIZE bytes)
; Out: rax = Cell*  (zeroed by hal_alloc)
; Clobbers: rax, rcx + whatever hal_alloc clobbers
; Stack: 1 push + sub 32 → total 40, 40 mod 16 = 8... wait
; Entry RSP mod 16 = 8; push rbx → 0; sub 32 → 0 ✓
_cell_alloc:
    push rbx
    sub  rsp, 32

    mov  rcx, CELL_SIZE
    call hal_alloc          ; rax = Cell*

    add  rsp, 32
    pop  rbx
    ret

; cons_alloc — allocate one uninitialised Cons (CONS_SIZE bytes)
_cons_alloc:
    push rbx
    sub  rsp, 32

    mov  rcx, CONS_SIZE
    call hal_alloc

    add  rsp, 32
    pop  rbx
    ret

; ── Public procedures ─────────────────────────────────────────────────────────

; make_int — allocate a TAG_INT Cell
; In:  rcx = 64-bit signed integer value
; Out: rax = Cell*
; Stack: 1 push + sub 32 → 40, (8-40) mod 16 = 0 ✓
make_int:
    push rbx
    sub  rsp, 32

    mov  rbx, rcx           ; stash value (rcx needed for _cell_alloc)
    call _cell_alloc        ; rax = Cell*
    mov  qword [rax + Cell.tag], TAG_INT
    mov  [rax + Cell.val],  rbx

    add  rsp, 32
    pop  rbx
    ret

; make_sym — allocate a TAG_SYM Cell, copying the string into a SymData header
; In:  rcx = pointer to source bytes
;      rdx = byte count
; Out: rax = Cell*
; Stack: 3 pushes + sub 32 → 56, (8-56) mod 16 = 0 ✓
make_sym:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    mov  r12, rcx           ; r12 = source ptr
    mov  r13, rdx           ; r13 = length

    ; Allocate SymData: header (8 bytes) + string bytes + null terminator
    lea  rcx, [r13 + SYMDATA_HDR + 1]
    call hal_alloc          ; rax = SymData*
    mov  rbx, rax           ; rbx = SymData*

    mov  [rbx + SymData.len], r13

    ; Copy string bytes
    xor  r9,  r9
.copy:
    cmp  r9,  r13
    jge  .copy_done
    mov  al,  [r12 + r9]
    mov  [rbx + SymData.chars + r9], al
    inc  r9
    jmp  .copy
.copy_done:
    mov  byte [rbx + SymData.chars + r13], 0   ; null terminator

    ; Allocate Cell and point it at the SymData
    call _cell_alloc        ; rax = Cell*
    mov  qword [rax + Cell.tag], TAG_SYM
    mov  [rax + Cell.val],  rbx

    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; make_string — allocate a TAG_STRING Cell (self-evaluating)
; In:  rcx = pointer to string bytes (inner content, no quotes)
;      rdx = byte count
; Out: rax = Cell*
; Stack: 3 pushes + sub 32 → 56, (8-56) mod 16 = 0 ✓
make_string:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    mov  r12, rcx
    mov  r13, rdx

    lea  rcx, [r13 + SYMDATA_HDR + 1]
    call hal_alloc
    mov  rbx, rax

    mov  [rbx + SymData.len], r13

    xor  r9, r9
.copy:
    cmp  r9,  r13
    jge  .copy_done
    mov  al,  [r12 + r9]
    mov  [rbx + SymData.chars + r9], al
    inc  r9
    jmp  .copy
.copy_done:
    mov  byte [rbx + SymData.chars + r13], 0

    call _cell_alloc
    mov  qword [rax + Cell.tag], TAG_STRING
    mov  [rax + Cell.val], rbx

    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; make_vec — convert a cons list of Cell* values into a TAG_VEC Cell
; In:  rcx = cons list Cell* (the elements, already in order)
; Out: rax = TAG_VEC Cell*
;
; Two-pass: count elements, allocate Vec, fill cells.
; Stack: 3 pushes + sub 64 = 88; (8-88) mod 16 = 0 ✓
; [rsp+32] = original cons list (saved for pass 2)
; [rsp+40] = Vec*
; [rsp+48] = count
make_vec:
    push rbx
    push r12
    push r13
    sub  rsp, 64

    mov  r12, rcx               ; r12 = cons list walker
    mov  [rsp+32], rcx          ; save original for pass 2

    ; ── Pass 1: count elements ────────────────────────────────────────────
    xor  r13, r13               ; r13 = count
.count_loop:
    cmp  qword [r12 + Cell.tag], TAG_NIL
    je   .count_done
    mov  rbx, [r12 + Cell.val]
    mov  r12, [rbx + Cons.cdr]
    inc  r13
    jmp  .count_loop
.count_done:
    mov  [rsp+48], r13

    ; ── Allocate Vec: VEC_HDR + count * 8 bytes ───────────────────────────
    mov  rcx, r13
    shl  rcx, 3
    add  rcx, VEC_HDR
    call hal_alloc              ; rax = Vec*
    mov  [rsp+40], rax

    mov  rbx, rax
    mov  r13, [rsp+48]
    mov  [rbx + Vec.count], r13

    ; ── Pass 2: fill cell pointers ────────────────────────────────────────
    mov  r12, [rsp+32]          ; restore original list
    xor  r13, r13               ; r13 = index
.fill_loop:
    cmp  qword [r12 + Cell.tag], TAG_NIL
    je   .fill_done
    mov  rbx, [r12 + Cell.val]  ; Cons*
    mov  r9,  [rbx + Cons.car]  ; element Cell*
    mov  r12, [rbx + Cons.cdr]  ; advance list
    mov  rbx, [rsp+40]          ; Vec*
    mov  [rbx + VEC_HDR + r13*8], r9
    inc  r13
    jmp  .fill_loop
.fill_done:

    ; ── Wrap in TAG_VEC Cell ──────────────────────────────────────────────
    call _cell_alloc
    mov  rbx, [rsp+40]
    mov  qword [rax + Cell.tag], TAG_VEC
    mov  [rax + Cell.val], rbx

    add  rsp, 64
    pop  r13
    pop  r12
    pop  rbx
    ret

; make_keyword — allocate a TAG_KEYWORD Cell (self-evaluating, used as map keys)
; In:  rcx = pointer to source bytes (including leading ':')
;      rdx = byte count (including ':')
; Out: rax = Cell*
; Identical to make_sym but sets TAG_KEYWORD.
; Stack: 3 pushes + sub 32 → 56, (8-56) mod 16 = 0 ✓
make_keyword:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    mov  r12, rcx
    mov  r13, rdx

    lea  rcx, [r13 + SYMDATA_HDR + 1]
    call hal_alloc
    mov  rbx, rax

    mov  [rbx + SymData.len], r13

    xor  r9, r9
.copy:
    cmp  r9,  r13
    jge  .copy_done
    mov  al,  [r12 + r9]
    mov  [rbx + SymData.chars + r9], al
    inc  r9
    jmp  .copy
.copy_done:
    mov  byte [rbx + SymData.chars + r13], 0

    call _cell_alloc
    mov  qword [rax + Cell.tag], TAG_KEYWORD
    mov  [rax + Cell.val], rbx

    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; make_cons — allocate a TAG_CONS Cell wrapping a new Cons pair
; In:  rcx = car (Cell*)
;      rdx = cdr (Cell*)
; Out: rax = Cell*
; Stack: 3 pushes + sub 32 → 56, (8-56) mod 16 = 0 ✓
make_cons:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    mov  r12, rcx           ; r12 = car
    mov  r13, rdx           ; r13 = cdr

    call _cons_alloc        ; rax = Cons*
    mov  rbx, rax
    mov  [rbx + Cons.car], r12
    mov  [rbx + Cons.cdr], r13

    call _cell_alloc        ; rax = Cell*
    mov  qword [rax + Cell.tag], TAG_CONS
    mov  [rax + Cell.val],  rbx

    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; make_atom — parse an atom token into an INT or SYM Cell
; In:  rcx = pointer to atom text
;      rdx = byte count
; Out: rax = Cell*
;
; Tries to interpret the text as a signed decimal integer.
; Accepts: optional leading '-' followed by one or more ASCII digits.
; Anything else becomes a symbol.
;
; Stack: 3 pushes + sub 32 → 56, (8-56) mod 16 = 0 ✓
make_atom:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    mov  r12, rcx           ; r12 = text ptr
    mov  r13, rdx           ; r13 = length

    test r13, r13
    jz   .sym               ; empty → symbol (shouldn't happen)

    ; Determine digit span: skip leading '-'
    xor  rbx, rbx           ; rbx = digit start index
    mov  al,  [r12]
    cmp  al,  '-'
    jne  .check_digits
    cmp  r13, 1
    je   .sym               ; lone '-' is not a number
    mov  rbx, 1

.check_digits:
    ; All chars from rbx to r13-1 must be '0'..'9'
    mov  r8,  rbx
.digit_loop:
    cmp  r8,  r13
    jge  .is_int
    movzx eax, byte [r12 + r8]
    cmp  al,  '0'
    jl   .sym
    cmp  al,  '9'
    jg   .sym
    inc  r8
    jmp  .digit_loop

.is_int:
    ; Parse the magnitude, then negate if '-' was present
    xor  r9,  r9            ; r9 = accumulator
    mov  r8,  rbx           ; r8 = digit index (skips '-' if present)
.parse_loop:
    cmp  r8,  r13
    jge  .parse_done
    movzx eax, byte [r12 + r8]
    sub  eax, '0'
    imul r9,  r9, 10
    add  r9,  rax
    inc  r8
    jmp  .parse_loop
.parse_done:
    ; Negate if first char was '-'
    mov  al,  [r12]
    cmp  al,  '-'
    jne  .pos
    neg  r9
.pos:
    mov  rcx, r9
    call make_int           ; rax = Cell*  (TAG_INT)
    jmp  .done

.sym:
    mov  rcx, r12
    mov  rdx, r13
    call make_sym           ; rax = Cell*  (TAG_SYM)

.done:
    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret
