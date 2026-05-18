; =============================================================================
; printer.asm - Lisp value pretty-printer
;
; Public:
;   print_cell  rcx=Cell*  → (none)   print one value in Lisp notation
;
; Internal:
;   _print_list  rcx=Cons*  → (none)  print list body (no outer parens)
;   _print_int   rcx=i64    → (none)  print signed decimal integer
; =============================================================================

section '.rdata' data readable

    _str_nil    db 'nil'
    _str_true   db 'true'
    _str_false  db 'false'
    _str_dot    db ' . '    ; dotted-pair separator
    _str_prim   db '#<primitive>'
    _str_lambda db '#<lambda>'

section '.code' code readable executable

; _print_int — write a signed 64-bit integer to stdout in decimal
; In:  rcx = value
; Stack: 3 pushes + sub 64 → 88, (8-88) mod 16 = 0 ✓
;        [rsp+32..55] = 24-byte digit buffer (enough for -9223372036854775808)
_print_int:
    push rbx
    push r12
    push r13
    sub  rsp, 64

    mov  r12, rcx           ; r12 = value
    lea  rbx, [rsp + 32]    ; rbx = digit buffer base

    ; Special-case zero
    test r12, r12
    jnz  .not_zero
    mov  cl,  '0'
    call hal_write_char
    jmp  .int_done

.not_zero:
    ; Handle negative sign
    test r12, r12
    jns  .positive
    mov  cl, '-'
    call hal_write_char
    neg  r12

.positive:
    ; Extract digits in reverse (least significant first)
    xor  r13, r13           ; r13 = digit count
    mov  r8,  10            ; divisor (stays in r8 for the loop)

.extract:
    test r12, r12
    jz   .print_digits
    xor  rdx, rdx           ; rdx:rax / r8
    mov  rax, r12
    div  r8                 ; rax = quotient, rdx = remainder
    mov  r12, rax
    add  dl,  '0'
    mov  [rbx + r13], dl
    inc  r13
    jmp  .extract

.print_digits:
    dec  r13
.print_loop:
    js   .int_done
    movzx ecx, byte [rbx + r13]  ; cl = digit char
    call hal_write_char           ; r13 is preserved (callee-saved)
    dec  r13
    jmp  .print_loop

.int_done:
    add  rsp, 64
    pop  r13
    pop  r12
    pop  rbx
    ret

; _print_list — print list body: "car cdr ..." without surrounding parens
; In:  rcx = Cons*
; Stack: 3 pushes + sub 32 → 56, (8-56) mod 16 = 0 ✓
_print_list:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    mov  r12, rcx           ; r12 = Cons*

    ; Print car
    mov  rcx, [r12 + Cons.car]
    call print_cell

    ; Inspect cdr
    mov  r13, [r12 + Cons.cdr]  ; r13 = cdr Cell*
    mov  rax, [r13 + Cell.tag]

    cmp  rax, TAG_NIL
    je   .list_done         ; proper list end

    cmp  rax, TAG_CONS
    je   .more_cons

    ; Dotted pair: print " . " then cdr directly
    lea  rcx, [_str_dot]
    mov  rdx, 3
    call hal_write_string
    mov  rcx, r13
    call print_cell
    jmp  .list_done

.more_cons:
    ; Continue list: space then recurse into cdr's Cons
    mov  cl, ' '
    call hal_write_char
    mov  rcx, [r13 + Cell.val]  ; Cons* inside the cdr Cell
    call _print_list

.list_done:
    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; print_cell — print one Cell in Lisp notation
; In:  rcx = Cell*
; Stack: 3 pushes + sub 32 → 56, (8-56) mod 16 = 0 ✓
print_cell:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    mov  r12, rcx           ; r12 = Cell*
    mov  rax, [r12 + Cell.tag]

    cmp  rax, TAG_NIL
    je   .nil

    cmp  rax, TAG_BOOL
    je   .bool

    cmp  rax, TAG_INT
    je   .int

    cmp  rax, TAG_SYM
    je   .sym

    cmp  rax, TAG_CONS
    je   .cons

    cmp  rax, TAG_PRIM
    je   .prim

    cmp  rax, TAG_CLOSURE
    je   .closure

    ; Unknown tag — shouldn't happen; print nothing
    jmp  .cell_done

.nil:
    lea  rcx, [_str_nil]
    mov  rdx, 3
    call hal_write_string
    jmp  .cell_done

.bool:
    mov  r13, [r12 + Cell.val]
    test r13, r13
    jz   .false
    lea  rcx, [_str_true]
    mov  rdx, 4
    call hal_write_string
    jmp  .cell_done
.false:
    lea  rcx, [_str_false]
    mov  rdx, 5
    call hal_write_string
    jmp  .cell_done

.int:
    mov  rcx, [r12 + Cell.val]
    call _print_int
    jmp  .cell_done

.sym:
    mov  r13, [r12 + Cell.val]     ; r13 = SymData*
    lea  rcx, [r13 + SymData.chars]
    mov  rdx, [r13 + SymData.len]
    call hal_write_string
    jmp  .cell_done

.cons:
    mov  cl, '('
    call hal_write_char
    mov  rcx, [r12 + Cell.val]     ; Cons*
    call _print_list
    mov  cl, ')'
    call hal_write_char
    jmp  .cell_done

.prim:
    lea  rcx, [_str_prim]
    mov  rdx, 12
    call hal_write_string
    jmp  .cell_done

.closure:
    lea  rcx, [_str_lambda]
    mov  rdx, 9
    call hal_write_string

.cell_done:
    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret
