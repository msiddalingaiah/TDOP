; =============================================================================
; primitives.asm — Built-in primitive functions
;
; Each primitive has signature:
;   prim_foo:  rcx = args Cell* (evaluated list),  rdx = env Cell*
;              → rax = result Cell*
;
; Registered at startup by primitives_init, which writes directly to
; _global_env via env_define.
;
; Primitives:
;   Arithmetic (variadic): +  -  *
;   Comparison (binary):   =  <  >
;   List ops:              car  cdr  cons  list
;   Predicates:            nil?  number?  pair?  symbol?  not
;   I/O:                   display  newline
;   Control:               exit  quit  (both call hal_exit(0))
; =============================================================================

section '.rdata' data readable

    ; Primitive name strings (null-terminated for _sym_is; length given to make_sym)
    _pn_add    db '+',       0
    _pn_sub    db '-',       0
    _pn_mul    db '*',       0
    _pn_eq     db '=',       0
    _pn_lt     db '<',       0
    _pn_gt     db '>',       0
    _pn_car    db 'car',     0
    _pn_cdr    db 'cdr',     0
    _pn_cons   db 'cons',    0
    _pn_list   db 'list',    0
    _pn_nilp   db 'nil?',    0
    _pn_nump   db 'number?', 0
    _pn_pairp  db 'pair?',   0
    _pn_symp   db 'symbol?', 0
    _pn_not    db 'not',     0
    _pn_disp   db 'display', 0
    _pn_nl     db 'newline', 0
    _pn_exit   db 'exit',    0
    _pn_quit   db 'quit',    0

section '.code' code readable executable

; ── Helpers ────────────────────────────────────────────────────────────────

; _arg1 — extract the first argument from an args list
; In:  rcx = args Cell*
; Out: rax = first arg Cell*, or _cell_nil if list is empty / wrong type
; No frame — no calls.
_arg1:
    mov  rax, [rcx + Cell.tag]
    cmp  rax, TAG_NIL
    je   .nil
    mov  r8,  [rcx + Cell.val]   ; Cons*
    mov  rax, [r8  + Cons.car]   ; first arg Cell*
    ret
.nil:
    lea  rax, [_cell_nil]
    ret

; ── Arithmetic ─────────────────────────────────────────────────────────────

; (+ n...) — sum of all integer args; returns 0 for no args
; Stack: 3 pushes + sub 32 = 56; (8-56) mod 16 = 0 ✓
prim_add:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    mov  r12, rcx           ; arg list
    xor  r13, r13           ; accumulator

.loop:
    mov  rax, [r12 + Cell.tag]
    cmp  rax, TAG_NIL
    je   .done
    mov  rbx, [r12 + Cell.val]
    mov  r9,  [rbx + Cons.car]
    cmp  qword [r9 + Cell.tag], TAG_INT
    jne  .skip
    add  r13, [r9 + Cell.val]
.skip:
    mov  r12, [rbx + Cons.cdr]
    jmp  .loop

.done:
    mov  rcx, r13
    call make_int

    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; (- n)      — negate n
; (- a b...) — a - b - ...
; Stack: 3 pushes + sub 32 = 56; (8-56) mod 16 = 0 ✓
prim_sub:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    mov  r12, rcx

    ; Empty args → 0
    mov  rax, [r12 + Cell.tag]
    cmp  rax, TAG_NIL
    je   .zero

    ; Get first arg
    mov  rbx, [r12 + Cell.val]
    mov  r9,  [rbx + Cons.car]
    mov  r12, [rbx + Cons.cdr]
    cmp  qword [r9 + Cell.tag], TAG_INT
    jne  .zero
    mov  r13, [r9 + Cell.val]   ; r13 = first value

    ; Unary negation if no more args
    mov  rax, [r12 + Cell.tag]
    cmp  rax, TAG_NIL
    jne  .sub_loop
    neg  r13
    jmp  .emit

.sub_loop:
    mov  rax, [r12 + Cell.tag]
    cmp  rax, TAG_NIL
    je   .emit
    mov  rbx, [r12 + Cell.val]
    mov  r9,  [rbx + Cons.car]
    cmp  qword [r9 + Cell.tag], TAG_INT
    jne  .skip_sub
    sub  r13, [r9 + Cell.val]
.skip_sub:
    mov  r12, [rbx + Cons.cdr]
    jmp  .sub_loop

.zero:
    xor  r13, r13
.emit:
    mov  rcx, r13
    call make_int
    jmp  .done

.done:
    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; (* n...) — product of all integer args; returns 1 for no args
; Stack: 3 pushes + sub 32 = 56; (8-56) mod 16 = 0 ✓
prim_mul:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    mov  r12, rcx
    mov  r13, 1             ; accumulator

.loop:
    mov  rax, [r12 + Cell.tag]
    cmp  rax, TAG_NIL
    je   .done
    mov  rbx, [r12 + Cell.val]
    mov  r9,  [rbx + Cons.car]
    cmp  qword [r9 + Cell.tag], TAG_INT
    jne  .skip
    imul r13, [r9 + Cell.val]
.skip:
    mov  r12, [rbx + Cons.cdr]
    jmp  .loop

.done:
    mov  rcx, r13
    call make_int

    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; ── Comparison ─────────────────────────────────────────────────────────────

; _cmp2 — shared two-arg extraction for =, <, >
; In:  rcx = args Cell*
; Out: r12 = first Cell*, r13 = second Cell*
;      rax = 1 if both present, 0 otherwise
; (Must be called from within a 3-push + sub 32 frame.)
_cmp2:
    mov  rax, [rcx + Cell.tag]
    cmp  rax, TAG_NIL
    je   .bad
    mov  rbx, [rcx + Cell.val]
    mov  r12, [rbx + Cons.car]   ; first
    mov  r9,  [rbx + Cons.cdr]
    mov  rax, [r9  + Cell.tag]
    cmp  rax, TAG_NIL
    je   .bad
    mov  rbx, [r9  + Cell.val]
    mov  r13, [rbx + Cons.car]   ; second
    mov  rax, 1
    ret
.bad:
    xor  rax, rax
    ret

; (= a b) — structural equality (same tag and same value field)
; Stack: 3 pushes + sub 32 = 56; (8-56) mod 16 = 0 ✓
prim_eq:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    call _cmp2
    test rax, rax
    jz   .false

    mov  rax, [r12 + Cell.tag]
    cmp  rax, [r13 + Cell.tag]
    jne  .false
    mov  rax, [r12 + Cell.val]
    cmp  rax, [r13 + Cell.val]
    jne  .false

.true:
    lea  rax, [_cell_true]
    jmp  .done
.false:
    lea  rax, [_cell_false]
.done:
    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; (< a b) — integer less-than
; Stack: 3 pushes + sub 32 = 56; (8-56) mod 16 = 0 ✓
prim_lt:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    call _cmp2
    test rax, rax
    jz   .false
    cmp  qword [r12 + Cell.tag], TAG_INT
    jne  .false
    cmp  qword [r13 + Cell.tag], TAG_INT
    jne  .false
    mov  rax, [r12 + Cell.val]
    cmp  rax, [r13 + Cell.val]
    jl   .true

.false:
    lea  rax, [_cell_false]
    jmp  .done
.true:
    lea  rax, [_cell_true]
.done:
    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; (> a b) — integer greater-than
; Stack: 3 pushes + sub 32 = 56; (8-56) mod 16 = 0 ✓
prim_gt:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    call _cmp2
    test rax, rax
    jz   .false
    cmp  qword [r12 + Cell.tag], TAG_INT
    jne  .false
    cmp  qword [r13 + Cell.tag], TAG_INT
    jne  .false
    mov  rax, [r12 + Cell.val]
    cmp  rax, [r13 + Cell.val]
    jg   .true

.false:
    lea  rax, [_cell_false]
    jmp  .done
.true:
    lea  rax, [_cell_true]
.done:
    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; ── List operations ─────────────────────────────────────────────────────────

; (car pair) — first element
; Stack: 1 push + sub 32 = 40; (8-40) mod 16 = 0 ✓
prim_car:
    push rbx
    sub  rsp, 32

    call _arg1              ; rax = first arg
    cmp  qword [rax + Cell.tag], TAG_CONS
    jne  .nil
    mov  rbx, [rax + Cell.val]
    mov  rax, [rbx + Cons.car]
    jmp  .done
.nil:
    lea  rax, [_cell_nil]
.done:
    add  rsp, 32
    pop  rbx
    ret

; (cdr pair) — rest of list
; Stack: 1 push + sub 32 = 40; (8-40) mod 16 = 0 ✓
prim_cdr:
    push rbx
    sub  rsp, 32

    call _arg1
    cmp  qword [rax + Cell.tag], TAG_CONS
    jne  .nil
    mov  rbx, [rax + Cell.val]
    mov  rax, [rbx + Cons.cdr]
    jmp  .done
.nil:
    lea  rax, [_cell_nil]
.done:
    add  rsp, 32
    pop  rbx
    ret

; (cons a b) — create a pair
; Stack: 3 pushes + sub 32 = 56; (8-56) mod 16 = 0 ✓
prim_cons:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    mov  rax, [rcx + Cell.tag]
    cmp  rax, TAG_NIL
    je   .nil

    mov  rbx, [rcx + Cell.val]
    mov  r12, [rbx + Cons.car]   ; car arg
    mov  r9,  [rbx + Cons.cdr]
    mov  rax, [r9  + Cell.tag]
    cmp  rax, TAG_NIL
    je   .nil
    mov  rbx, [r9  + Cell.val]
    mov  r13, [rbx + Cons.car]   ; cdr arg

    mov  rcx, r12
    mov  rdx, r13
    call make_cons
    jmp  .done

.nil:
    lea  rax, [_cell_nil]
.done:
    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; (list x...) — args are already an evaluated list; return as-is
prim_list:
    mov  rax, rcx
    ret

; ── Predicates ─────────────────────────────────────────────────────────────

; _tag_predicate — check whether the first arg has a given tag
; In:  rcx = args,  r8 = tag to test
; Out: rax = _cell_true / _cell_false
; (Called from within a 1-push + sub 32 frame; no inner calls here.)
_tag_predicate:
    mov  rax, [rcx + Cell.tag]
    cmp  rax, TAG_NIL
    je   .false
    mov  r9,  [rcx + Cell.val]
    mov  rax, [r9  + Cons.car]   ; first arg
    cmp  qword [rax + Cell.tag], r8
    je   .true
.false:
    lea  rax, [_cell_false]
    ret
.true:
    lea  rax, [_cell_true]
    ret

; (nil? x) — Stack: 1 push + sub 32 = 40; (8-40) mod 16 = 0 ✓
prim_nilp:
    push rbx
    sub  rsp, 32
    mov  r8, TAG_NIL
    call _tag_predicate
    add  rsp, 32
    pop  rbx
    ret

; (number? x)
prim_numberp:
    push rbx
    sub  rsp, 32
    mov  r8, TAG_INT
    call _tag_predicate
    add  rsp, 32
    pop  rbx
    ret

; (pair? x)
prim_pairp:
    push rbx
    sub  rsp, 32
    mov  r8, TAG_CONS
    call _tag_predicate
    add  rsp, 32
    pop  rbx
    ret

; (symbol? x)
prim_symbolp:
    push rbx
    sub  rsp, 32
    mov  r8, TAG_SYM
    call _tag_predicate
    add  rsp, 32
    pop  rbx
    ret

; (not x) — true if x is nil or false, else false
; Stack: 1 push + sub 32 = 40; (8-40) mod 16 = 0 ✓
prim_not:
    push rbx
    sub  rsp, 32

    call _arg1              ; rax = first arg (or nil)
    mov  r8, [rax + Cell.tag]
    cmp  r8, TAG_NIL
    je   .true
    cmp  r8, TAG_BOOL
    jne  .false
    cmp  qword [rax + Cell.val], 0
    je   .true

.false:
    lea  rax, [_cell_false]
    jmp  .done
.true:
    lea  rax, [_cell_true]
.done:
    add  rsp, 32
    pop  rbx
    ret

; ── I/O ─────────────────────────────────────────────────────────────────────

; (display x) — print first arg without trailing newline
; Stack: 1 push + sub 32 = 40; (8-40) mod 16 = 0 ✓
prim_display:
    push rbx
    sub  rsp, 32

    call _arg1
    mov  rcx, rax
    call print_cell

    lea  rax, [_cell_nil]

    add  rsp, 32
    pop  rbx
    ret

; (newline) — emit a newline character
; Stack: 1 push + sub 32 = 40; (8-40) mod 16 = 0 ✓
prim_newline:
    push rbx
    sub  rsp, 32

    mov  cl, 10
    call hal_write_char
    lea  rax, [_cell_nil]

    add  rsp, 32
    pop  rbx
    ret

; ── Control ─────────────────────────────────────────────────────────────────

; (exit) / (quit) — terminate with exit code 0
; Stack: 1 push + sub 32 = 40; (8-40) mod 16 = 0 ✓
prim_exit:
    push rbx
    sub  rsp, 32
    xor  rcx, rcx           ; exit code 0
    call hal_exit            ; never returns

; ── Registration ────────────────────────────────────────────────────────────

; defprim name_str, name_len, fn_label
;   Allocates a TAG_SYM + TAG_PRIM Cell pair and calls env_define.
;   Uses r12 as temp (preserved by make_sym / _cell_alloc / env_define).
;   Must be called from within a 3-push + sub 32 frame (maintains alignment).
macro defprim name_str, name_len, fn_label {
    lea  rcx, [name_str]
    mov  rdx, name_len
    call make_sym
    mov  r12, rax               ; r12 = sym Cell*

    call _cell_alloc            ; rax = prim Cell*
    mov  qword [rax + Cell.tag], TAG_PRIM
    lea  r9,  [fn_label]        ; RIP-relative: no base-reloc needed
    mov  [rax + Cell.val], r9

    mov  rcx, r12               ; sym
    mov  rdx, rax               ; prim Cell*
    lea  r8,  [_global_env]
    call env_define
}

; primitives_init — register all built-ins in _global_env
; Called once from main.asm after _global_env has been seeded with _cell_nil.
;
; Stack: 3 pushes + sub 32 = 56; (8-56) mod 16 = 0 ✓
primitives_init:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    defprim _pn_add,  1, prim_add
    defprim _pn_sub,  1, prim_sub
    defprim _pn_mul,  1, prim_mul
    defprim _pn_eq,   1, prim_eq
    defprim _pn_lt,   1, prim_lt
    defprim _pn_gt,   1, prim_gt
    defprim _pn_car,  3, prim_car
    defprim _pn_cdr,  3, prim_cdr
    defprim _pn_cons, 4, prim_cons
    defprim _pn_list, 4, prim_list
    defprim _pn_nilp, 4, prim_nilp
    defprim _pn_nump, 7, prim_numberp
    defprim _pn_pairp,5, prim_pairp
    defprim _pn_symp, 7, prim_symbolp
    defprim _pn_not,  3, prim_not
    defprim _pn_disp, 7, prim_display
    defprim _pn_nl,   7, prim_newline
    defprim _pn_exit, 4, prim_exit
    defprim _pn_quit, 4, prim_exit   ; quit = same as exit

    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret
