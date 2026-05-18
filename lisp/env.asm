; =============================================================================
; env.asm - Environment (association list) operations
;
; The environment is a Lisp alist: ((sym1 . val1) (sym2 . val2) ...)
; where each element is a CONS Cell whose car is a sym/val pair Cell.
;
; Global env (_global_env) is a qword holding the current alist head Cell*.
; It starts as _cell_nil and grows leftward as bindings are added.
;
; Scoping note:
;   env_lookup searches the given env chain first, then falls back to the
;   current _global_env.  This lets closures see bindings added after they
;   were created (e.g. recursive self-references) while still preserving
;   lexically captured local variables.
;
; Public:
;   sym_eq       rcx=sym1 rdx=sym2         → rax=1/0
;   env_lookup   rcx=sym  rdx=env          → rax=Cell* or 0
;   env_define   rcx=sym  rdx=val  r8=env**→ (updates *r8)
;   env_extend   rcx=params rdx=args r8=parent → rax=new env Cell*
; =============================================================================

section '.data' data readable writeable

    _global_env  dq 0       ; Cell* — the top-level alist (init to _cell_nil)

section '.code' code readable executable

; sym_eq — compare two TAG_SYM Cells by string content
; In:  rcx = sym1 Cell*,  rdx = sym2 Cell*
; Out: rax = 1 if equal, 0 otherwise
; No frame — no inner calls; uses rax/r8/r9/r10 as scratch.
sym_eq:
    mov  rax, [rcx + Cell.val]      ; SymData* for sym1
    mov  r8,  [rdx + Cell.val]      ; SymData* for sym2
    mov  r9,  [rax + SymData.len]
    cmp  r9,  [r8 + SymData.len]
    jne  .no
    xor  r10, r10
.loop:
    cmp  r10, r9
    jge  .yes
    mov  cl,  [rax + SymData.chars + r10]
    cmp  cl,  [r8  + SymData.chars + r10]
    jne  .no
    inc  r10
    jmp  .loop
.yes:
    mov  rax, 1
    ret
.no:
    xor  rax, rax
    ret

; _sym_is — compare a TAG_SYM Cell against a static null-terminated C string
; In:  rcx = sym Cell*,  rdx = null-terminated string
; Out: rax = 1 if equal, 0 otherwise
; No frame — no inner calls; uses rax/r8/r9/r10 as scratch.
_sym_is:
    mov  rax, [rcx + Cell.val]      ; SymData*
    mov  r8,  [rax + SymData.len]   ; symbol length

    xor  r9,  r9                    ; count string length
.count:
    cmp  byte [rdx + r9], 0
    je   .counted
    inc  r9
    jmp  .count
.counted:
    cmp  r8,  r9
    jne  .no

    xor  r10, r10
.cmp:
    cmp  r10, r8
    jge  .yes
    mov  cl,  [rax + SymData.chars + r10]
    cmp  cl,  [rdx + r10]
    jne  .no
    inc  r10
    jmp  .cmp
.yes:
    mov  rax, 1
    ret
.no:
    xor  rax, rax
    ret

; env_lookup — find a symbol's value in an alist, with global-env fallback
; In:  rcx = sym Cell*
;      rdx = env Cell* (alist to search first)
; Out: rax = value Cell*, or 0 if not found
;
; Stack: 3 pushes + sub 48 = 72; (8-72) mod 16 = 0 ✓
; Locals: [rsp+32]=pair Cell* temp   [rsp+40]=Cons* temp
env_lookup:
    push rbx
    push r12
    push r13
    sub  rsp, 48

    mov  r12, rcx           ; r12 = sym
    mov  r13, rdx           ; r13 = current env position

    ; ── Pass 1: search the given env chain ────────────────────────────────
.loop1:
    mov  rax, [r13 + Cell.tag]
    cmp  rax, TAG_NIL
    je   .fallback

    mov  rbx, [r13 + Cell.val]          ; Cons* of env list
    mov  r8,  [rbx + Cons.car]          ; pair Cell*
    mov  [rsp+32], r8
    mov  [rsp+40], rbx

    mov  r9,  [r8  + Cell.val]          ; Cons* of pair
    mov  r10, [r9  + Cons.car]          ; sym in pair

    mov  rcx, r12
    mov  rdx, r10
    call sym_eq
    test rax, rax
    jnz  .found1

    mov  rbx, [rsp+40]
    mov  r13, [rbx + Cons.cdr]          ; advance env
    jmp  .loop1

.found1:
    mov  r8,  [rsp+32]
    mov  r9,  [r8  + Cell.val]
    mov  rax, [r9  + Cons.cdr]          ; the value
    jmp  .done

    ; ── Pass 2: fall back to current _global_env ──────────────────────────
.fallback:
    mov  r13, [_global_env]

.loop2:
    mov  rax, [r13 + Cell.tag]
    cmp  rax, TAG_NIL
    je   .not_found

    mov  rbx, [r13 + Cell.val]
    mov  r8,  [rbx + Cons.car]
    mov  [rsp+32], r8
    mov  [rsp+40], rbx

    mov  r9,  [r8  + Cell.val]
    mov  r10, [r9  + Cons.car]

    mov  rcx, r12
    mov  rdx, r10
    call sym_eq
    test rax, rax
    jnz  .found2

    mov  rbx, [rsp+40]
    mov  r13, [rbx + Cons.cdr]
    jmp  .loop2

.found2:
    mov  r8,  [rsp+32]
    mov  r9,  [r8  + Cell.val]
    mov  rax, [r9  + Cons.cdr]
    jmp  .done

.not_found:
    xor  rax, rax           ; NULL = not found

.done:
    add  rsp, 48
    pop  r13
    pop  r12
    pop  rbx
    ret

; env_define — prepend (sym . val) to the alist pointed at by *r8
; In:  rcx = sym Cell*
;      rdx = val Cell*
;      r8  = Cell** — address of the alist head pointer (will be updated)
; Out: (none)
;
; Stack: 3 pushes + sub 32 = 56; (8-56) mod 16 = 0 ✓
env_define:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    mov  r12, rcx           ; sym
    mov  r13, rdx           ; val
    mov  rbx, r8            ; env**

    ; pair = make_cons(sym, val)
    mov  rcx, r12
    mov  rdx, r13
    call make_cons          ; rax = pair Cell*
    mov  r12, rax

    ; new_env = make_cons(pair, *env_ptr)
    mov  rcx, r12
    mov  rdx, [rbx]         ; current alist head
    call make_cons          ; rax = new alist head

    mov  [rbx], rax         ; update *env_ptr

    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; env_extend — bind params to args in a new alist frame on top of parent
; In:  rcx = params Cell* (list of sym Cells)
;      rdx = args   Cell* (list of val Cells, already evaluated)
;      r8  = parent env Cell*
; Out: rax = new env Cell* (alist with local bindings prepended)
;
; Builds: ((p1.a1) (p2.a2) ... . parent)
; Stops when either list is exhausted.
;
; Stack: 3 pushes + sub 48 = 72; (8-72) mod 16 = 0 ✓
; Local: [rsp+32] = running env Cell* (grows as we prepend)
env_extend:
    push rbx
    push r12
    push r13
    sub  rsp, 48

    mov  r12, rcx           ; r12 = params (walks forward)
    mov  r13, rdx           ; r13 = args   (walks forward)
    mov  [rsp+32], r8       ; running env = parent

.loop:
    mov  rax, [r12 + Cell.tag]
    cmp  rax, TAG_NIL
    je   .done

    mov  rax, [r13 + Cell.tag]
    cmp  rax, TAG_NIL
    je   .done

    ; Advance params and args, capturing current heads
    mov  rbx, [r12 + Cell.val]     ; params Cons*
    mov  r9,  [rbx + Cons.car]     ; param sym Cell*
    mov  r12, [rbx + Cons.cdr]     ; params = params.cdr

    mov  rbx, [r13 + Cell.val]     ; args Cons*
    mov  r10, [rbx + Cons.car]     ; arg val Cell*
    mov  r13, [rbx + Cons.cdr]     ; args = args.cdr

    ; pair = make_cons(param, val)
    mov  rcx, r9
    mov  rdx, r10
    call make_cons          ; rax = pair
    mov  rbx, rax

    ; env = make_cons(pair, env)
    mov  rcx, rbx
    mov  rdx, [rsp+32]
    call make_cons          ; rax = new env head
    mov  [rsp+32], rax

    jmp  .loop

.done:
    mov  rax, [rsp+32]

    add  rsp, 48
    pop  r13
    pop  r12
    pop  rbx
    ret
