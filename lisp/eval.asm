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

    cmp  rax, TAG_SYM
    je   .sym

    cmp  rax, TAG_CONS
    je   .list

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
    lea  rax, [_cell_nil]   ; unbound → nil (silent for now)
    jmp  .done

.list:
    mov  rcx, r12
    mov  rdx, r13
    call _eval_list

.done:
    add  rsp, 32
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

    ; ── (lambda (params...) body) ─────────────────────────────────────────
.sf_lambda:
    mov  rcx, [rsp+40]
    mov  rbx, [rcx + Cell.val]
    mov  r9,  [rbx + Cons.car]  ; params list Cell*
    mov  r10, [rbx + Cons.cdr]  ; (body)
    mov  [rsp+48], r9            ; save params

    mov  rbx, [r10 + Cell.val]
    mov  r10, [rbx + Cons.car]  ; body expr
    mov  [rsp+56], r10           ; save body

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

    ; ── (begin e1 e2 ... eN) → value of eN ───────────────────────────────
.sf_begin:
    mov  r12, [rsp+40]          ; r12 = expr list (reuse, original no longer needed)
    lea  rax, [_cell_nil]       ; default if begin is empty

.begin_loop:
    mov  r9,  [r12 + Cell.tag]
    cmp  r9,  TAG_NIL
    je   .done

    mov  rbx, [r12 + Cell.val]
    mov  r9,  [rbx + Cons.car]  ; current expr
    mov  r12, [rbx + Cons.cdr]  ; remaining (r12 preserved by eval_cell)

    mov  rcx, r9
    mov  rdx, r13
    call eval_cell               ; rax = result (kept as running return)

    jmp  .begin_loop

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

    ; Not callable
    lea  rax, [_cell_nil]
    jmp  .done

.prim:
    mov  rbx, [r12 + Cell.val]  ; function pointer
    mov  rcx, r13               ; args list
    call rbx                    ; call the primitive
    jmp  .done

.closure:
    mov  rbx, [r12 + Cell.val]         ; Closure*
    mov  r9,  [rbx + Closure.params]
    mov  r10, [rbx + Closure.body]
    mov  r11, [rbx + Closure.env]
    mov  [rsp+32], r10                  ; save body (r10 clobbered by env_extend)

    ; Extend the closure's captured env with local bindings
    mov  rcx, r9    ; params
    mov  rdx, r13   ; args
    mov  r8,  r11   ; parent = closure's captured env
    call env_extend  ; rax = extended env

    ; Evaluate body in the extended env
    mov  rcx, [rsp+32]  ; body
    mov  rdx, rax       ; extended env
    call eval_cell

.done:
    add  rsp, 48
    pop  r13
    pop  r12
    pop  rbx
    ret
