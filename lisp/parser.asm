; =============================================================================
; parser.asm - S-expression parser
;
; Reads tokens from the tokenizer and builds a tree of Cells using the
; memory allocators.
;
; Public:
;   parse_next  (none) → rax=Cell*  or  rax=0 on EOF
;
; Internal:
;   _parse_token  rcx=Token* → rax=Cell*   (dispatch on token type)
;   _parse_list   (none)     → rax=Cell*   (reads until TOK_RPAREN/EOF)
;
; The parser owns a single static token buffer (_parse_tok) used across
; all procedures.  All calls to tok_next use this buffer.
; =============================================================================

section '.data' data readable writeable

    _parse_tok  rq 3        ; Token struct, TOK_SIZE=24 bytes (3 qwords)

section '.code' code readable executable

; _parse_vector — read [ elem ... ] and return a TAG_VEC Cell*
; Elements are parsed recursively via _parse_bracket_list then converted.
; Stack: 1 push + sub 32 = 40; (8-40) mod 16 = 0 ✓
_parse_vector:
    push rbx
    sub  rsp, 32

    call _parse_bracket_list    ; rax = cons list of parsed elements
    mov  rcx, rax
    call make_vec               ; rax = TAG_VEC Cell*

    add  rsp, 32
    pop  rbx
    ret

; _parse_bracket_list — read a vector body after '[' has been consumed
; Returns a plain CONS list (same structure as a paren list).
; Used for let bindings and fn/defn parameter vectors.
; Out: rax = Cell* (CONS chain terminating with _cell_nil)
; Stack: 3 pushes + sub 32 → 56, (8-56) mod 16 = 0 ✓
_parse_bracket_list:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    lea  rcx, [_parse_tok]
    call tok_next           ; rax = TOK_*

    cmp  rax, TOK_RBRACKET
    je   .end_list
    cmp  rax, TOK_EOF
    je   .end_list          ; unclosed bracket — treat EOF as ']'

    lea  rcx, [_parse_tok]
    call _parse_token
    mov  r12, rax           ; r12 = car Cell*

    call _parse_bracket_list
    mov  r13, rax           ; r13 = cdr Cell*

    mov  rcx, r12
    mov  rdx, r13
    call make_cons
    jmp  .done

.end_list:
    lea  rax, [_cell_nil]

.done:
    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; _parse_list — read a list body after '(' has been consumed
; Out: rax = Cell* (CONS chain terminating with _cell_nil)
; Stack: 3 pushes + sub 32 → 56, (8-56) mod 16 = 0 ✓
_parse_list:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    ; Peek at the next token to check for ')'
    lea  rcx, [_parse_tok]
    call tok_next           ; rax = TOK_*

    cmp  rax, TOK_RPAREN
    je   .end_list
    cmp  rax, TOK_EOF
    je   .end_list          ; unclosed list — treat EOF as ')'

    ; Parse the head (car) from whatever token we just read
    lea  rcx, [_parse_tok]
    call _parse_token
    mov  r12, rax           ; r12 = car Cell*

    ; Parse the tail (cdr) — recursive
    call _parse_list
    mov  r13, rax           ; r13 = cdr Cell*

    ; Cons them together
    mov  rcx, r12
    mov  rdx, r13
    call make_cons          ; rax = Cell*  (TAG_CONS)
    jmp  .done

.end_list:
    lea  rax, [_cell_nil]   ; proper list terminator

.done:
    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; _parse_token — turn an already-filled Token struct into a Cell
; In:  rcx = Token* (filled by tok_next)
; Out: rax = Cell*
; Stack: 3 pushes + sub 32 → 56, (8-56) mod 16 = 0 ✓
_parse_token:
    push rbx
    push r12
    push r13
    sub  rsp, 32

    mov  r12, rcx                       ; r12 = Token*
    mov  rbx, [r12 + TOK.type]

    cmp  rbx, TOK_ATOM
    je   .atom

    cmp  rbx, TOK_STRING
    je   .str

    cmp  rbx, TOK_LPAREN
    je   .list

    cmp  rbx, TOK_LBRACKET
    je   .bracket

    ; TOK_RPAREN, TOK_RBRACKET, TOK_EOF, or anything else → nil
    lea  rax, [_cell_nil]
    jmp  .done

.atom:
    mov  rcx, [r12 + TOK.start]
    mov  rdx, [r12 + TOK.len]
    cmp  byte [rcx], ':'
    je   .keyword
    call make_atom
    jmp  .done

.str:
    mov  rcx, [r12 + TOK.start]
    mov  rdx, [r12 + TOK.len]
    call make_string        ; rax = Cell* (TAG_STRING)
    jmp  .done

.keyword:
    call make_keyword       ; rax = Cell* (TAG_KEYWORD)
    jmp  .done

.list:
    call _parse_list        ; rax = Cell*  (reads until matching ')')
    jmp  .done

.bracket:
    call _parse_vector          ; rax = TAG_VEC Cell*

.done:
    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret

; parse_next — read and parse one complete expression
; Returns 0 (NULL) if the very first token is EOF (allows REPL exit).
; Out: rax = Cell*  or  0 on EOF
; Stack: 1 push + sub 32 → 40, (8-40) mod 16 = 0 ✓
parse_next:
    push rbx
    sub  rsp, 32

    lea  rcx, [_parse_tok]
    call tok_next           ; rax = TOK_*

    cmp  rax, TOK_EOF
    jne  .not_eof

    xor  rax, rax           ; return NULL → REPL exits
    jmp  .done

.not_eof:
    lea  rcx, [_parse_tok]
    call _parse_token       ; rax = Cell*

.done:
    add  rsp, 32
    pop  rbx
    ret
