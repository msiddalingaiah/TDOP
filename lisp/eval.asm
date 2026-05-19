; =============================================================================
; eval.asm - Core evaluator
;
; Public:
;   eval_cell   rcx=expr rdx=env → rax=Cell*
;
; Internal:
;   _eval_list  rcx=list rdx=env → rax=Cell*  (special forms + calls)
;   _eval_args  rcx=list rdx=env → rax=Cell*  (evaluate each element)
;   _apply      rcx=fn   rdx=args r8=env → rax=Cell*
;
; Special forms: quote · if · define · lambda · begin
;
; Self-evaluating: TAG_NIL, TAG_BOOL, TAG_INT, TAG_PRIM, TAG_CLOSURE
; Symbol: looked up in env (with global fallback)
; List: dispatched by car
; =============================================================================

section '.rdata' data readable

    _sf_quote   db 'quote',  0
    _sf_if      db 'if',     0
    _sf_define  db 'define', 0
    _sf_lambda  db 'lambda', 0
    _sf_begin   db 'begin',  0
    _sf_fn      db 'fn',     0   ; alias for lambda
    _sf_do      db 'do',     0   ; alias for begin
    _sf_def     db 'def',    0   ; alias for define
    _sf_defn    db 'defn',   0   ; (defn name [params] body...)
    _sf_let     db 'let',    0   ; (let [x v ...] body...)
    _sf_when    db 'when',   0   ; (when test body...)
    _sf_unless  db 'unless', 0   ; (unless test body...)

    ; Error messages — leading 10 = newline before the message
    _err_unbound_pre    db 10, "ERROR: unbound symbol '"
    _err_unbound_pre_len = $ - _err_unbound_pre
    _err_notfn          db 10, 'ERROR: not a function', 10
    _err_notfn_len      = $ - _err_notfn

section '.code' code readable executable

; eval_cell — evaluate one expression in the given environment
; In:  rcx = expr Cell*
;      rdx = env  Cell*
; Out: rax = result Cell*
;
; Stack: 3 pushes + sub 32 = 56; (8-56) mod 16 = 0 ✓
eval_cell:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    mov  r12, rcx           ; expr
    mov  r13, rdx           ; env

    mov  rax, [r12 + Cell.tag]

    ; Self-evaluating types
    cmp  rax, TAG_NIL
    je   .self
    cmp  rax, TAG_BOOL
    je   .self
    cmp  rax, TAG_INT
    je   .self
    cmp  rax, TAG_PRIM
    je   .self
    cmp  rax, TAG_CLOSURE
    je   .self
    cmp  rax, TAG_KEYWORD
    je   .self
    cmp  rax, TAG_STRING
    je   .self

    cmp  rax, TAG_SYM
    je   .sym

    cmp  rax, TAG_CONS
    je   .list

    cmp  rax, TAG_VEC
    je   .vec

    ; Unknown — return nil
    lea  rax, [_cell_nil]
    jmp  .done

.self:
    mov  rax, r12
    jmp  .done

.sym:
    mov  rcx, r12
    mov  rdx, r13
    call env_lookup         ; rax = Cell* or 0
    test rax, rax
    jnz  .done

    ; Unbound symbol — print error and return nil
    lea  rcx, [_err_unbound_pre]
    mov  rdx, _err_unbound_pre_len
    call hal_write_string

    mov  rax, [r12 + Cell.val]      ; SymData*
    lea  rcx, [rax + SymData.chars]
    mov  rdx, [rax + SymData.len]
    call hal_write_string

    mov  cl, 39                     ; closing '
    call hal_write_char
    mov  cl, 10                     ; newline
    call hal_write_char

    lea  rax, [_cell_nil]
    jmp  .done

.list:
    mov  rcx, r12
    mov  rdx, r13
    call _eval_list
    jmp  .done

.vec:
    mov  rcx, r12
    mov  rdx, r13
    call _eval_vec

.done:
    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; _eval_vec — evaluate each element of a vector literal
; In:  rcx = TAG_VEC Cell*,  rdx = env Cell*
; Out: rax = new TAG_VEC Cell* with every element evaluated
;
; Stack: 3 pushes + sub 64 = 88; (8-88) mod 16 = 0 ✓
; [rsp+32] = original Vec*
; [rsp+40] = new Vec*
; [rsp+48] = element count
; [rsp+56] = current index i
_eval_vec:
    push rbx
    push r12
    push r13
    sub  rsp, 64

    mov  r12, rcx                       ; r12 = original TAG_VEC Cell*
    mov  r13, rdx                       ; r13 = env

    mov  rbx, [r12 + Cell.val]          ; old Vec*
    mov  [rsp+32], rbx
    mov  r9,  [rbx + Vec.count]
    mov  [rsp+48], r9

    ; Allocate new Vec of the same size
    mov  rcx, r9
    shl  rcx, 3
    add  rcx, VEC_HDR
    call hal_alloc                      ; rax = new Vec*
    mov  [rsp+40], rax
    mov  rbx, rax
    mov  r9,  [rsp+48]
    mov  [rbx + Vec.count], r9

    ; Evaluate each element
    xor  r9, r9
    mov  [rsp+56], r9                   ; i = 0

.eval_loop:
    mov  r9,  [rsp+56]
    cmp  r9,  [rsp+48]
    jge  .eval_done

    mov  rbx, [rsp+32]                  ; old Vec*
    mov  rcx, [rbx + VEC_HDR + r9*8]   ; element expr
    mov  rdx, r13
    call eval_cell                      ; rax = evaluated element

    mov  r9,  [rsp+56]
    mov  rbx, [rsp+40]                  ; new Vec*
    mov  [rbx + VEC_HDR + r9*8], rax

    inc  r9
    mov  [rsp+56], r9
    jmp  .eval_loop

.eval_done:
    ; Wrap in TAG_VEC Cell
    call _cell_alloc
    mov  rbx, [rsp+40]
    mov  qword [rax + Cell.tag], TAG_VEC
    mov  [rax + Cell.val], rbx

    add  rsp, 64
    pop  r13
    pop  r12
    pop  rbx
    ret

; _eval_list — evaluate a list form (special form or function call)
; In:  rcx = CONS Cell*  (the list)
;      rdx = env Cell*
; Out: rax = result Cell*
;
; Stack: 3 pushes + sub 64 = 88; (8-88) mod 16 = 0 ✓
; Locals:
;   [rsp+32] = car Cell* (operator, then evaluated fn)
;   [rsp+40] = cdr Cell* (arg list, unevaluated then evaluated)
;   [rsp+48] = temp save A
;   [rsp+56] = temp save B
_eval_list:
    push rbx
    push r12
    push r13
    sub  rsp, 64

    mov  r12, rcx
    mov  r13, rdx

    ; Extract car and cdr, save to stack
    mov  rbx, [r12 + Cell.val]
    mov  rax, [rbx + Cons.car]  ; car = operator
    mov  r9,  [rbx + Cons.cdr]  ; cdr = arg list
    mov  [rsp+32], rax
    mov  [rsp+40], r9

    ; Only check special forms if car is a symbol
    mov  rax, [rax + Cell.tag]
    cmp  rax, TAG_SYM
    jne  .normal_call

    mov  rcx, [rsp+32]
    lea  rdx, [_sf_quote]
    call _sym_is
    test rax, rax
    jnz  .sf_quote

    mov  rcx, [rsp+32]
    lea  rdx, [_sf_if]
    call _sym_is
    test rax, rax
    jnz  .sf_if

    mov  rcx, [rsp+32]
    lea  rdx, [_sf_define]
    call _sym_is
    test rax, rax
    jnz  .sf_define

    mov  rcx, [rsp+32]
    lea  rdx, [_sf_lambda]
    call _sym_is
    test rax, rax
    jnz  .sf_lambda

    mov  rcx, [rsp+32]
    lea  rdx, [_sf_begin]
    call _sym_is
    test rax, rax
    jnz  .sf_begin

    mov  rcx, [rsp+32]
    lea  rdx, [_sf_fn]
    call _sym_is
    test rax, rax
    jnz  .sf_lambda         ; fn = lambda

    mov  rcx, [rsp+32]
    lea  rdx, [_sf_do]
    call _sym_is
    test rax, rax
    jnz  .sf_begin          ; do = begin

    mov  rcx, [rsp+32]
    lea  rdx, [_sf_def]
    call _sym_is
    test rax, rax
    jnz  .sf_define         ; def = define

    mov  rcx, [rsp+32]
    lea  rdx, [_sf_defn]
    call _sym_is
    test rax, rax
    jnz  .sf_defn

    mov  rcx, [rsp+32]
    lea  rdx, [_sf_let]
    call _sym_is
    test rax, rax
    jnz  .sf_let

    mov  rcx, [rsp+32]
    lea  rdx, [_sf_when]
    call _sym_is
    test rax, rax
    jnz  .sf_when

    mov  rcx, [rsp+32]
    lea  rdx, [_sf_unless]
    call _sym_is
    test rax, rax
    jnz  .sf_unless

    ; ── Normal function call ───────────────────────────────────────────────
.normal_call:
    mov  rcx, [rsp+32]      ; operator expr
    mov  rdx, r13
    call eval_cell
    mov  [rsp+32], rax      ; evaluated fn

    mov  rcx, [rsp+40]      ; arg list
    mov  rdx, r13
    call _eval_args
    mov  [rsp+40], rax      ; evaluated args

    mov  rcx, [rsp+32]
    mov  rdx, [rsp+40]
    mov  r8,  r13
    call _apply
    jmp  .done

    ; ── (quote x) → x unevaluated ─────────────────────────────────────────
.sf_quote:
    mov  rcx, [rsp+40]          ; cdr = (x)
    mov  rbx, [rcx + Cell.val]
    mov  rax, [rbx + Cons.car]  ; x
    jmp  .done

    ; ── (if test then [else]) ─────────────────────────────────────────────
.sf_if:
    mov  rcx, [rsp+40]
    mov  rbx, [rcx + Cell.val]
    mov  r9,  [rbx + Cons.car]  ; test expr
    mov  r10, [rbx + Cons.cdr]  ; (then [else])
    mov  [rsp+48], r10           ; save (then [else]) across call

    mov  rcx, r9
    mov  rdx, r13
    call eval_cell               ; rax = test result
    mov  rbx, rax

    ; Falsy: nil, or bool false
    mov  rax, [rbx + Cell.tag]
    cmp  rax, TAG_NIL
    je   .if_false
    cmp  rax, TAG_BOOL
    jne  .if_true
    cmp  qword [rbx + Cell.val], 0
    je   .if_false

.if_true:
    mov  r10, [rsp+48]
    mov  rbx, [r10 + Cell.val]
    mov  rcx, [rbx + Cons.car]  ; then expr
    mov  rdx, r13
    call eval_cell
    jmp  .done

.if_false:
    mov  r10, [rsp+48]
    mov  rbx, [r10 + Cell.val]
    mov  r10, [rbx + Cons.cdr]  ; ([else]) or nil

    mov  rax, [r10 + Cell.tag]
    cmp  rax, TAG_NIL
    je   .if_no_else

    mov  rbx, [r10 + Cell.val]
    mov  rcx, [rbx + Cons.car]  ; else expr
    mov  rdx, r13
    call eval_cell
    jmp  .done

.if_no_else:
    lea  rax, [_cell_nil]
    jmp  .done

    ; ── (define sym val-expr) ─────────────────────────────────────────────
    ; Always writes to the global environment.
.sf_define:
    mov  rcx, [rsp+40]
    mov  rbx, [rcx + Cell.val]
    mov  r9,  [rbx + Cons.car]  ; sym Cell*
    mov  r10, [rbx + Cons.cdr]  ; (val-expr)
    mov  [rsp+48], r9            ; save sym across call

    mov  rbx, [r10 + Cell.val]
    mov  rcx, [rbx + Cons.car]  ; val-expr
    mov  rdx, r13
    call eval_cell
    mov  rbx, rax               ; rbx = evaluated value

    mov  rcx, [rsp+48]          ; sym
    mov  rdx, rbx               ; value
    lea  r8,  [_global_env]
    call env_define

    mov  rax, rbx               ; return the bound value
    jmp  .done

    ; ── (lambda (params...) body...) — also handles fn ────────────────────
    ; Closure.body now stores the body FORM LIST, not a single expr.
    ; _apply iterates it like (begin ...).
.sf_lambda:
    mov  rcx, [rsp+40]
    mov  rbx, [rcx + Cell.val]
    mov  r9,  [rbx + Cons.car]  ; params list Cell*
    mov  r10, [rbx + Cons.cdr]  ; body list (all remaining forms)
    mov  [rsp+48], r9            ; save params
    mov  [rsp+56], r10           ; save body LIST

    ; Allocate Closure struct and fill it
    mov  rcx, CLOSURE_SIZE
    call hal_alloc
    mov  rbx, rax

    mov  r9,  [rsp+48]
    mov  r10, [rsp+56]
    mov  [rbx + Closure.params], r9
    mov  [rbx + Closure.body],   r10
    mov  [rbx + Closure.env],    r13  ; capture current env

    ; Wrap in a TAG_CLOSURE Cell
    call _cell_alloc
    mov  qword [rax + Cell.tag], TAG_CLOSURE
    mov  [rax + Cell.val],  rbx
    jmp  .done

    ; ── (begin e1 e2 ... eN) → value of eN — also handles do ─────────────
.sf_begin:
    mov  r12, [rsp+40]          ; r12 = expr list
    lea  rax, [_cell_nil]

.begin_loop:
    mov  r9,  [r12 + Cell.tag]
    cmp  r9,  TAG_NIL
    je   .done

    mov  rbx, [r12 + Cell.val]
    mov  r9,  [rbx + Cons.car]
    mov  r12, [rbx + Cons.cdr]

    mov  rcx, r9
    mov  rdx, r13
    call eval_cell

    jmp  .begin_loop

    ; ── (defn name [params] body...) ──────────────────────────────────────
    ; Desugars to: (define name (fn [params] body...))
    ; Inline: extracts name/params/body, builds Closure, env_defines it.
    ;
    ; Slot reuse (by this point car/cdr in [rsp+32/40] are expendable):
    ;   r12        = name Cell*    (repurposed; callee-saved ✓)
    ;   [rsp+32]   = params Cell*
    ;   [rsp+40]   = body list Cell*
    ;   [rsp+48]   = Closure*
    ;   [rsp+56]   = closure Cell*
.sf_defn:
    mov  rcx, [rsp+40]           ; args = (name [params] body...)
    mov  rbx, [rcx + Cell.val]
    mov  r12, [rbx + Cons.car]   ; r12 = name Cell*
    mov  r9,  [rbx + Cons.cdr]   ; ([params] body...)

    mov  rbx, [r9 + Cell.val]
    mov  rax, [rbx + Cons.car]   ; params Cell* (bracket list = cons list)
    mov  [rsp+32], rax
    mov  rax, [rbx + Cons.cdr]   ; body list
    mov  [rsp+40], rax

    ; Allocate and fill Closure
    mov  rcx, CLOSURE_SIZE
    call hal_alloc
    mov  [rsp+48], rax

    mov  rbx, rax
    mov  r9,  [rsp+32]
    mov  r10, [rsp+40]
    mov  [rbx + Closure.params], r9
    mov  [rbx + Closure.body],   r10
    mov  [rbx + Closure.env],    r13

    ; Wrap in TAG_CLOSURE Cell
    call _cell_alloc
    mov  rbx, [rsp+48]
    mov  qword [rax + Cell.tag], TAG_CLOSURE
    mov  [rax + Cell.val], rbx
    mov  [rsp+56], rax            ; closure Cell*

    ; Define name → closure in global env
    mov  rcx, r12
    mov  rdx, [rsp+56]
    lea  r8,  [_global_env]
    call env_define

    mov  rax, [rsp+56]
    jmp  .done

    ; ── (let [x v x2 v2 ...] body...) ────────────────────────────────────
    ; Bindings are now TAG_VEC (since [...] produces vectors).
    ; Sequential binding: each val is eval'd in the env extended so far.
    ;
    ; Slot reuse:
    ;   r12        = Vec* of bindings (repurposed; callee-saved ✓)
    ;   [rsp+32]   = index i (walks binding pairs)
    ;   [rsp+40]   = body list
    ;   [rsp+48]   = running env
    ;   [rsp+56]   = current sym Cell* temp
.sf_let:
    mov  rcx, [rsp+40]            ; args = (bindings-vec body...)
    mov  rbx, [rcx + Cell.val]
    mov  r9,  [rbx + Cons.car]    ; bindings Cell* (TAG_VEC)
    mov  rax, [rbx + Cons.cdr]    ; body list
    mov  [rsp+40], rax
    mov  [rsp+48], r13            ; running env = initial env

    mov  r12, [r9 + Cell.val]     ; r12 = Vec* of bindings

    xor  rax, rax
    mov  [rsp+32], rax            ; i = 0

.let_bind:
    mov  r9,  [rsp+32]            ; i
    cmp  r9,  [r12 + Vec.count]
    jge  .let_body                ; i >= count: all bindings done

    ; sym = Vec.cells[i]
    mov  rax, [r12 + VEC_HDR + r9*8]
    mov  [rsp+56], rax            ; save sym

    ; check i+1 exists
    inc  r9
    cmp  r9,  [r12 + Vec.count]
    jge  .let_body                ; odd count: stop

    ; val-expr = Vec.cells[i+1]
    mov  rcx, [r12 + VEC_HDR + r9*8]
    inc  r9
    mov  [rsp+32], r9             ; advance i by 2

    ; eval val-expr in current running env (r12 survives: callee-saved ✓)
    mov  rdx, [rsp+48]
    call eval_cell                ; rax = val

    ; extend env: cons(cons(sym, val), running-env)
    mov  rcx, [rsp+56]
    mov  rdx, rax
    call make_cons                ; pair
    mov  rcx, rax
    mov  rdx, [rsp+48]
    call make_cons                ; new env head
    mov  [rsp+48], rax

    jmp  .let_bind

.let_body:
    ; eval body forms in sequence in the final env, return last
    mov  r12, [rsp+40]
    lea  rax, [_cell_nil]

.let_body_loop:
    mov  r9, [r12 + Cell.tag]
    cmp  r9, TAG_NIL
    je   .done

    mov  rbx, [r12 + Cell.val]
    mov  r9,  [rbx + Cons.car]
    mov  r12, [rbx + Cons.cdr]

    mov  rcx, r9
    mov  rdx, [rsp+48]
    call eval_cell

    jmp  .let_body_loop

    ; ── (when test body...) — eval body if test is truthy, else nil ───────
.sf_when:
    mov  rcx, [rsp+40]
    mov  rbx, [rcx + Cell.val]
    mov  r9,  [rbx + Cons.car]   ; test expr
    mov  r10, [rbx + Cons.cdr]   ; body list
    mov  [rsp+48], r10

    mov  rcx, r9
    mov  rdx, r13
    call eval_cell

    mov  r9, [rax + Cell.tag]
    cmp  r9, TAG_NIL
    je   .when_false
    cmp  r9, TAG_BOOL
    jne  .when_true
    cmp  qword [rax + Cell.val], 0
    je   .when_false

.when_true:
    mov  r12, [rsp+48]
    lea  rax, [_cell_nil]
.when_loop:
    mov  r9, [r12 + Cell.tag]
    cmp  r9, TAG_NIL
    je   .done
    mov  rbx, [r12 + Cell.val]
    mov  r9,  [rbx + Cons.car]
    mov  r12, [rbx + Cons.cdr]
    mov  rcx, r9
    mov  rdx, r13
    call eval_cell
    jmp  .when_loop

.when_false:
    lea  rax, [_cell_nil]
    jmp  .done

    ; ── (unless test body...) — eval body if test is falsy, else nil ──────
.sf_unless:
    mov  rcx, [rsp+40]
    mov  rbx, [rcx + Cell.val]
    mov  r9,  [rbx + Cons.car]
    mov  r10, [rbx + Cons.cdr]
    mov  [rsp+48], r10

    mov  rcx, r9
    mov  rdx, r13
    call eval_cell

    mov  r9, [rax + Cell.tag]
    cmp  r9, TAG_NIL
    je   .unless_run
    cmp  r9, TAG_BOOL
    jne  .unless_skip
    cmp  qword [rax + Cell.val], 0
    jne  .unless_skip

.unless_run:
    mov  r12, [rsp+48]
    lea  rax, [_cell_nil]
.unless_loop:
    mov  r9, [r12 + Cell.tag]
    cmp  r9, TAG_NIL
    je   .done
    mov  rbx, [r12 + Cell.val]
    mov  r9,  [rbx + Cons.car]
    mov  r12, [rbx + Cons.cdr]
    mov  rcx, r9
    mov  rdx, r13
    call eval_cell
    jmp  .unless_loop

.unless_skip:
    lea  rax, [_cell_nil]

.done:
    add  rsp, 64
    pop  r13
    pop  r12
    pop  rbx
    ret

; _eval_args — evaluate a list of expressions left-to-right
; In:  rcx = arg-list Cell*
;      rdx = env Cell*
; Out: rax = new list Cell* with each element evaluated
;
; Stack: 3 pushes + sub 32 = 56; (8-56) mod 16 = 0 ✓
_eval_args:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    mov  r12, rcx
    mov  r13, rdx

    mov  rax, [r12 + Cell.tag]
    cmp  rax, TAG_NIL
    je   .nil_base             ; base case: empty list

    ; Evaluate head
    mov  rbx, [r12 + Cell.val]
    mov  r9,  [rbx + Cons.car]
    mov  r12, [rbx + Cons.cdr] ; advance (r12 preserved across calls)

    mov  rcx, r9
    mov  rdx, r13
    call eval_cell
    mov  rbx, rax              ; rbx = evaluated head

    ; Recursively evaluate tail
    mov  rcx, r12
    mov  rdx, r13
    call _eval_args
    mov  r12, rax              ; r12 = evaluated tail

    ; Cons head onto tail
    mov  rcx, rbx
    mov  rdx, r12
    call make_cons
    jmp  .done

.nil_base:
    lea  rax, [_cell_nil]

.done:
    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; _apply — call a function with evaluated arguments
; In:  rcx = fn   Cell* (TAG_PRIM or TAG_CLOSURE)
;      rdx = args Cell* (already evaluated list)
;      r8  = env  Cell* (current env, used for closure base)
; Out: rax = result Cell*
;
; Stack: 3 pushes + sub 48 = 72; (8-72) mod 16 = 0 ✓
; Local: [rsp+32] = body Cell* save slot
_apply:
    push rbx
    push r12
    push r13
    sub  rsp, 48

    mov  r12, rcx           ; fn
    mov  r13, rdx           ; args

    mov  rax, [r12 + Cell.tag]

    cmp  rax, TAG_PRIM
    je   .prim

    cmp  rax, TAG_CLOSURE
    je   .closure

    ; Not callable — print error and return nil
    lea  rcx, [_err_notfn]
    mov  rdx, _err_notfn_len
    call hal_write_string
    lea  rax, [_cell_nil]
    jmp  .done

.prim:
    mov  rbx, [r12 + Cell.val]  ; function pointer
    mov  rcx, r13               ; args list
    call rbx                    ; call the primitive
    jmp  .done

.closure:
    mov  rbx, [r12 + Cell.val]          ; Closure*
    mov  r9,  [rbx + Closure.params]
    mov  r10, [rbx + Closure.body]      ; body LIST
    mov  r11, [rbx + Closure.env]
    mov  [rsp+32], r10                   ; save body list

    ; Extend the closure's captured env with local bindings
    mov  rcx, r9    ; params
    mov  rdx, r13   ; args
    mov  r8,  r11   ; parent = closure's captured env
    call env_extend
    mov  [rsp+40], rax                   ; save extended env

    ; Evaluate body forms in sequence, return last (like begin)
    mov  r12, [rsp+32]                   ; r12 = body list walker
    lea  rax,  [_cell_nil]               ; default if body is empty

.body_loop:
    mov  r9, [r12 + Cell.tag]
    cmp  r9, TAG_NIL
    je   .done

    mov  rbx, [r12 + Cell.val]
    mov  r9,  [rbx + Cons.car]           ; current body expr
    mov  r12, [rbx + Cons.cdr]           ; rest of body (r12 callee-saved ✓)

    mov  rcx, r9
    mov  rdx, [rsp+40]                   ; extended env
    call eval_cell                        ; rax = result

    jmp  .body_loop

.done:
    add  rsp, 48
    pop  r13
    pop  r12
    pop  rbx
    ret
