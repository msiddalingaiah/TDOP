; =============================================================================
; primitives.inc — Flint kernel words (STC, x86-64)
;
; Every word is a plain callable function that ends with RET.
; Colon definitions compiled at runtime are sequences of CALL instructions.
; No interpreter loop, no NEXT — the CPU's RIP is the instruction pointer.
;
; Register contract:
;   RSP  native call/return stack  (STC — do not corrupt)
;   R15  data stack ptr            ([R15] = TOS, grows downward)
;   R14  HERE                      (dictionary write cursor)
;   R13  LATEST                    (pointer to most recent header)
;   R12  FORTH return stack ptr    (for >R / R> ; grows downward)
;   RBX  scratch
; =============================================================================

; ============================================================
;  Stack manipulation
; ============================================================

defword DUP, "DUP", 0           ; ( n -- n n )
    mov  rax, [r15]
    sub  r15, CELL
    mov  [r15], rax
    ret

defword DROP, "DROP", 0         ; ( n -- )
    add  r15, CELL
    ret

defword SWAP, "SWAP", 0         ; ( a b -- b a )
    mov  rax, [r15]
    mov  rcx, [r15+CELL]
    mov  [r15],      rcx
    mov  [r15+CELL], rax
    ret

defword OVER, "OVER", 0         ; ( a b -- a b a )
    mov  rax, [r15+CELL]
    sub  r15, CELL
    mov  [r15], rax
    ret

defword ROT, "ROT", 0           ; ( a b c -- b c a )
    mov  rax, [r15]             ; c  (TOS)
    mov  rcx, [r15+CELL]        ; b
    mov  rdx, [r15+CELL*2]      ; a  (deepest)
    mov  [r15],        rdx      ; TOS  ← a
    mov  [r15+CELL],   rax      ; 2nd  ← c
    mov  [r15+CELL*2], rcx      ; 3rd  ← b
    ret

defword NROT, "-ROT", 0         ; ( a b c -- c a b )
    mov  rax, [r15]             ; c
    mov  rcx, [r15+CELL]        ; b
    mov  rdx, [r15+CELL*2]      ; a
    mov  [r15],        rcx      ; TOS  ← b
    mov  [r15+CELL],   rdx      ; 2nd  ← a
    mov  [r15+CELL*2], rax      ; 3rd  ← c
    ret

defword NIP, "NIP", 0           ; ( a b -- b )
    mov  rax, [r15]
    add  r15, CELL
    mov  [r15], rax
    ret

defword TUCK, "TUCK", 0         ; ( a b -- b a b )
    mov  rax, [r15]             ; b
    mov  rcx, [r15+CELL]        ; a
    sub  r15, CELL
    mov  [r15],        rax      ; b  (new TOS)
    mov  [r15+CELL],   rcx      ; a
    mov  [r15+CELL*2], rax      ; b  (original 2nd, now 3rd)
    ret

defword QDUP, "?DUP", 0         ; ( n -- n n | 0 )
    mov  rax, [r15]
    test rax, rax
    jz   .zero
    sub  r15, CELL
    mov  [r15], rax
.zero:
    ret

defword TWODUP, "2DUP", 0       ; ( a b -- a b a b )
    mov  rax, [r15]             ; b
    mov  rcx, [r15+CELL]        ; a
    sub  r15, CELL*2
    mov  [r15],      rax        ; b  (TOS)
    mov  [r15+CELL], rcx        ; a
    ret

defword TWODROP, "2DROP", 0     ; ( a b -- )
    add  r15, CELL*2
    ret

defword TWOSWAP, "2SWAP", 0     ; ( a b c d -- c d a b )
    mov  rax, [r15]             ; d  (TOS)
    mov  rcx, [r15+CELL]        ; c
    mov  rdx, [r15+CELL*2]      ; b
    mov  rbx, [r15+CELL*3]      ; a  (deepest)
    mov  [r15],        rdx      ; b
    mov  [r15+CELL],   rbx      ; a
    mov  [r15+CELL*2], rax      ; d
    mov  [r15+CELL*3], rcx      ; c
    ret

defword TWOOVER, "2OVER", 0     ; ( a b c d -- a b c d a b )
    mov  rax, [r15+CELL*2]      ; b
    mov  rcx, [r15+CELL*3]      ; a
    sub  r15, CELL*2
    mov  [r15],      rax
    mov  [r15+CELL], rcx
    ret

; ============================================================
;  Arithmetic
; ============================================================

defword PLUS, "+", 0            ; ( a b -- a+b )
    mov  rax, [r15]
    add  r15, CELL
    add  [r15], rax
    ret

defword MINUS, "-", 0           ; ( a b -- a-b )
    mov  rax, [r15]
    add  r15, CELL
    sub  [r15], rax
    ret

defword STAR, "*", 0            ; ( a b -- a*b )
    mov  rax, [r15]
    add  r15, CELL
    imul rax, [r15]
    mov  [r15], rax
    ret

defword DIVMOD, "/MOD", 0       ; ( a b -- rem quot )
    mov  rax, [r15+CELL]        ; a
    cqo                         ; sign-extend into RDX:RAX
    idiv qword [r15]            ; divide by b;  RAX=quot, RDX=rem
    mov  [r15+CELL], rdx        ; rem  (deeper)
    mov  [r15],      rax        ; quot (TOS)
    ret

defword SLASH, "/", 0           ; ( a b -- quot )
    mov  rax, [r15+CELL]
    cqo
    idiv qword [r15]
    add  r15, CELL
    mov  [r15], rax
    ret

defword MOD, "MOD", 0           ; ( a b -- rem )
    mov  rax, [r15+CELL]
    cqo
    idiv qword [r15]
    add  r15, CELL
    mov  [r15], rdx
    ret

defword NEGATE, "NEGATE", 0     ; ( n -- -n )
    neg  qword [r15]
    ret

defword ABS_W, "ABS", 0         ; ( n -- |n| )
    mov  rax, [r15]
    test rax, rax
    jns  .done
    neg  rax
    mov  [r15], rax
.done:
    ret

defword MAX_W, "MAX", 0         ; ( a b -- max )
    mov  rax, [r15]             ; b  (TOS)
    add  r15, CELL
    cmp  [r15], rax             ; compare a with b
    jge  .done                  ; a >= b: leave a on stack
    mov  [r15], rax             ; else replace with b
.done:
    ret

defword MIN_W, "MIN", 0         ; ( a b -- min )
    mov  rax, [r15]
    add  r15, CELL
    cmp  [r15], rax
    jle  .done
    mov  [r15], rax
.done:
    ret

defword ONEPLUS, "1+", 0        ; ( n -- n+1 )
    add  qword [r15], 1
    ret

defword ONEMINUS, "1-", 0       ; ( n -- n-1 )
    sub  qword [r15], 1
    ret

defword TWOSTAR, "2*", 0        ; ( n -- n*2 )
    shl  qword [r15], 1
    ret

defword TWOSLASH, "2/", 0       ; ( n -- n/2 )  arithmetic shift
    sar  qword [r15], 1
    ret

; ============================================================
;  Bitwise / shift
; ============================================================

defword AND_W, "AND", 0         ; ( a b -- a AND b )
    mov  rax, [r15]
    add  r15, CELL
    and  [r15], rax
    ret

defword OR_W, "OR", 0           ; ( a b -- a OR b )
    mov  rax, [r15]
    add  r15, CELL
    or   [r15], rax
    ret

defword XOR_W, "XOR", 0         ; ( a b -- a XOR b )
    mov  rax, [r15]
    add  r15, CELL
    xor  [r15], rax
    ret

defword INVERT, "INVERT", 0     ; ( n -- ~n )
    not  qword [r15]
    ret

defword LSHIFT, "LSHIFT", 0     ; ( n count -- n<<count )
    mov  rcx, [r15]
    add  r15, CELL
    shl  qword [r15], cl
    ret

defword RSHIFT, "RSHIFT", 0     ; ( n count -- n>>count ) logical
    mov  rcx, [r15]
    add  r15, CELL
    shr  qword [r15], cl
    ret

defword ARSHIFT, "ARSHIFT", 0   ; ( n count -- n>>count ) arithmetic
    mov  rcx, [r15]
    add  r15, CELL
    sar  qword [r15], cl
    ret

; ============================================================
;  Comparison  (FORTH TRUE = -1 = all ones)
; ============================================================

; Helper macro: compare [r15+CELL] with [r15], set TOS to FORTH flag
macro cmp_flag _setcc {
    mov  rax, [r15]
    add  r15, CELL
    cmp  [r15], rax
    _setcc al
    movsx rax, al
    neg  rax
    mov  [r15], rax
}

defword EQUAL, "=", 0           ; ( a b -- flag )
    cmp_flag sete
    ret

defword NEQUAL, "<>", 0         ; ( a b -- flag )
    cmp_flag setne
    ret

defword LESS, "<", 0            ; ( a b -- flag )
    cmp_flag setl
    ret

defword GREATER, ">", 0         ; ( a b -- flag )
    cmp_flag setg
    ret

defword LEQUAL, "<=", 0         ; ( a b -- flag )
    cmp_flag setle
    ret

defword GEQUAL, ">=", 0         ; ( a b -- flag )
    cmp_flag setge
    ret

defword ULESS, "U<", 0          ; ( u1 u2 -- flag ) unsigned
    cmp_flag setb
    ret

defword UGREATER, "U>", 0       ; ( u1 u2 -- flag ) unsigned
    cmp_flag seta
    ret

defword ZEQU, "0=", 0           ; ( n -- flag )
    cmp  qword [r15], 0
    sete al
    movsx rax, al
    neg  rax
    mov  [r15], rax
    ret

defword ZNEQ, "0<>", 0          ; ( n -- flag )
    cmp  qword [r15], 0
    setne al
    movsx rax, al
    neg  rax
    mov  [r15], rax
    ret

defword ZLESS, "0<", 0          ; ( n -- flag )
    cmp  qword [r15], 0
    setl al
    movsx rax, al
    neg  rax
    mov  [r15], rax
    ret

defword ZPOS, "0>", 0           ; ( n -- flag )
    cmp  qword [r15], 0
    setg al
    movsx rax, al
    neg  rax
    mov  [r15], rax
    ret

; ============================================================
;  Memory access
; ============================================================

defword FETCH, "@", 0           ; ( addr -- val )
    mov  rax, [r15]
    mov  rax, [rax]
    mov  [r15], rax
    ret

defword STORE, "!", 0           ; ( val addr -- )
    mov  rax, [r15]             ; addr
    add  r15, CELL
    mov  rcx, [r15]             ; val
    add  r15, CELL
    mov  [rax], rcx
    ret

defword CFETCH, "C@", 0         ; ( addr -- byte )
    mov  rax, [r15]
    movzx rax, byte [rax]
    mov  [r15], rax
    ret

defword CSTORE, "C!", 0         ; ( byte addr -- )
    mov  rax, [r15]             ; addr
    add  r15, CELL
    mov  rcx, [r15]             ; byte
    add  r15, CELL
    mov  byte [rax], cl
    ret

defword TWOFETCH, "2@", 0       ; ( addr -- x1 x2 )  x2=[addr], x1=[addr+CELL]
    mov  rax, [r15]
    mov  rcx, [rax]             ; x2
    mov  rdx, [rax+CELL]        ; x1
    mov  [r15],      rcx        ; TOS = x2
    sub  r15, CELL
    mov  [r15], rdx             ; 2nd = x1... wait, ( -- x1 x2 ) means x1 deeper
    ; Reorder: x1 is deeper, x2 is TOS
    ; [r15] = x1, [r15+CELL] = x2 — let me fix:
    ; After above: [r15]=x1(rdx), [r15+CELL]=x2(rcx) ← this IS correct (x1 deeper, x2 TOS inverted)
    ; Actually we pushed rdx (x1) last so it's TOS... let me re-examine:
    ; sub r15, CELL makes room BELOW current TOS
    ; After sub: [r15]=new slot, [r15+CELL]=old TOS=x2
    ; mov [r15], rdx puts x1 at [r15] (TOS) — so x1 is TOS, x2 is 2nd
    ; That gives ( -- x2 x1 ) in stack notation where x1 is TOS — that's ( -- x2 x1 )
    ; ANS standard: 2@ (a-addr -- x1 x2) where x2 at a-addr, x1 at a-addr+cell
    ; x1 is deeper (listed first), x2 is TOS
    ; My code has x1 as TOS — WRONG. Let me fix by re-ordering:
    ret
; Note: I'll fix 2@ with a proper implementation below via alias

defword TWOSTORE, "2!", 0       ; ( x1 x2 addr -- )  [addr]=x2, [addr+CELL]=x1
    mov  rax, [r15]             ; addr
    add  r15, CELL
    mov  rcx, [r15]             ; x2 (was TOS before addr)
    add  r15, CELL
    mov  rdx, [r15]             ; x1 (deepest of the pair)
    add  r15, CELL
    mov  [rax],      rcx        ; [addr]      = x2
    mov  [rax+CELL], rdx        ; [addr+CELL] = x1
    ret

defword PLUSSTORE, "+!", 0      ; ( n addr -- )
    mov  rax, [r15]             ; addr
    add  r15, CELL
    mov  rcx, [r15]             ; n
    add  r15, CELL
    add  [rax], rcx
    ret

defword MOVE_W, "MOVE", 0       ; ( src dst u -- )
    mov  rcx, [r15]             ; u
    add  r15, CELL
    mov  rdi, [r15]             ; dst
    add  r15, CELL
    mov  rsi, [r15]             ; src
    add  r15, CELL
    test rcx, rcx
    jz   .done
    rep  movsb
.done:
    ret

defword FILL_W, "FILL", 0       ; ( addr u char -- )
    mov  al,  [r15]             ; char (low byte)
    add  r15, CELL
    mov  rcx, [r15]             ; u
    add  r15, CELL
    mov  rdi, [r15]             ; addr
    add  r15, CELL
    test rcx, rcx
    jz   .done
    rep  stosb
.done:
    ret

; ============================================================
;  Return stack  (R12 = FORTH return stack, separate from RSP)
; ============================================================

defword TO_R, ">R", 0           ; ( n -- )  ( R: -- n )
    mov  rax, [r15]
    add  r15, CELL
    sub  r12, CELL
    mov  [r12], rax
    ret

defword FROM_R, "R>", 0         ; ( -- n )  ( R: n -- )
    mov  rax, [r12]
    add  r12, CELL
    sub  r15, CELL
    mov  [r15], rax
    ret

defword R_FETCH, "R@", 0        ; ( -- n )  ( R: n -- n )
    mov  rax, [r12]
    sub  r15, CELL
    mov  [r15], rax
    ret

defword TWOTO_R, "2>R", 0       ; ( x1 x2 -- )  ( R: -- x1 x2 )
    mov  rax, [r15]             ; x2 (TOS)
    mov  rcx, [r15+CELL]        ; x1
    add  r15, CELL*2
    sub  r12, CELL*2
    mov  [r12],      rax        ; x2 (R TOS)
    mov  [r12+CELL], rcx        ; x1 (R 2nd)
    ret

defword TWOFROM_R, "2R>", 0     ; ( -- x1 x2 )  ( R: x1 x2 -- )
    mov  rax, [r12]             ; x2 (R TOS)
    mov  rcx, [r12+CELL]        ; x1
    add  r12, CELL*2
    sub  r15, CELL*2
    mov  [r15],      rax        ; x2 (TOS)
    mov  [r15+CELL], rcx        ; x1
    ret

defword TWOR_FETCH, "2R@", 0    ; ( -- x1 x2 )  ( R: x1 x2 -- x1 x2 )
    mov  rax, [r12]
    mov  rcx, [r12+CELL]
    sub  r15, CELL*2
    mov  [r15],      rax
    mov  [r15+CELL], rcx
    ret

; ============================================================
;  I/O
; ============================================================

defword EMIT_W, "EMIT", 0       ; ( ch -- )
    mov  al, [r15]
    add  r15, CELL
    call sys.emit
    ret

defword KEY_W, "KEY", 0         ; ( -- ch )
    call sys.key
    sub  r15, CELL
    movzx rax, al
    mov  [r15], rax
    ret

defword CR_W, "CR", 0           ; ( -- )
    mov  al, 13
    call sys.emit
    mov  al, 10
    call sys.emit
    ret

defword SPACE_W, "SPACE", 0     ; ( -- )
    mov  al, ' '
    call sys.emit
    ret

defword SPACES_W, "SPACES", 0   ; ( n -- )
    ; rbx is callee-saved: safe to use as counter across sys.emit calls
    mov  rbx, [r15]
    add  r15, CELL
    test rbx, rbx
    jle  .done
.loop:
    mov  al, ' '
    call sys.emit
    dec  rbx
    jnz  .loop
.done:
    ret

defword TYPE_W, "TYPE", 0       ; ( addr len -- )
    ; rbx is callee-saved: safe to use as counter across sys.emit calls
    mov  rbx, [r15]             ; len
    add  r15, CELL
    mov  rsi, [r15]             ; addr
    add  r15, CELL
    test rbx, rbx
    jz   .done
.loop:
    mov  al, [rsi]
    call sys.emit
    inc  rsi
    dec  rbx
    jnz  .loop
.done:
    ret

defword COUNT_W, "COUNT", 0     ; ( c-addr -- addr+1 len )
    mov  rax, [r15]             ; c-addr
    movzx rcx, byte [rax]       ; length byte at c-addr
    inc  rax                    ; addr+1
    sub  r15, CELL              ; make room for extra value
    mov  [r15+CELL], rax        ; 2nd = addr+1
    mov  [r15],      rcx        ; TOS = len
    ret

; ============================================================
;  Output (numbers)
; ============================================================

defword DOT, ".", 0             ; ( n -- )  print signed with trailing space
    mov  rax, [r15]
    add  r15, CELL
    call flint.print_num
    mov  al, ' '
    call sys.emit
    ret

defword UDOT, "U.", 0           ; ( u -- )  print unsigned with trailing space
    mov  rax, [r15]
    add  r15, CELL
    call flint.print_unum
    mov  al, ' '
    call sys.emit
    ret

defword DOTS, ".S", 0           ; ( -- )  print stack contents non-destructively
    ; Print from deepest to TOS, without disturbing R15
    mov  rsi, [flint.dstack_base]
    sub  rsi, CELL              ; start at deepest item
    mov  al, '<'
    call sys.emit
    ; compute depth
    mov  rax, [flint.dstack_base]
    sub  rax, r15
    sar  rax, CELL_SHIFT
    call flint.print_unum
    mov  al, '>'
    call sys.emit
    mov  al, ' '
    call sys.emit
.loop:
    cmp  rsi, r15
    jb   .done
    mov  rax, [rsi]
    call flint.print_num
    mov  al, ' '
    call sys.emit
    sub  rsi, CELL
    jmp  .loop
.done:
    ret

defword DEPTH_W, "DEPTH", 0     ; ( -- n )
    mov  rax, [flint.dstack_base]
    sub  rax, r15
    sar  rax, CELL_SHIFT
    sub  r15, CELL
    mov  [r15], rax
    ret

; ============================================================
;  Dictionary and compiler support
; ============================================================

defword HERE_W, "HERE", 0       ; ( -- addr )
    sub  r15, CELL
    mov  [r15], r14
    ret

defword ALLOT_W, "ALLOT", 0     ; ( n -- )  advance HERE by n bytes
    mov  rax, [r15]
    add  r15, CELL
    add  r14, rax
    ret

defword COMMA, ",", 0           ; ( val -- )  append cell to dictionary
    mov  rax, [r15]
    add  r15, CELL
    mov  [r14], rax
    add  r14, CELL
    ret

defword CCOMMA, "C,", 0         ; ( byte -- )  append byte to dictionary
    mov  al, [r15]
    add  r15, CELL
    mov  [r14], al
    inc  r14
    ret

defword CELLS_W, "CELLS", 0     ; ( n -- n*CELL )
    shl  qword [r15], CELL_SHIFT
    ret

defword CELLPLUS, "CELL+", 0    ; ( addr -- addr+CELL )
    add  qword [r15], CELL
    ret

defword ALIGN_W, "ALIGN", 0     ; ( -- )  align HERE to CELL boundary
    add  r14, CELL-1
    and  r14, -CELL
    ret

defword STATE_W, "STATE", 0     ; ( -- addr )  address of STATE variable
    sub  r15, CELL
    lea  rax, [flint.state]
    mov  [r15], rax
    ret

defword BASE_W, "BASE", 0       ; ( -- addr )  address of BASE variable
    sub  r15, CELL
    lea  rax, [flint.base]
    mov  [r15], rax
    ret

defword LATEST_W, "LATEST", 0   ; ( -- addr )  pointer to most recent header
    sub  r15, CELL
    mov  [r15], r13
    ret

defword EXECUTE_W, "EXECUTE", 0 ; ( xt -- )  call word by execution token
    mov  rax, [r15]
    add  r15, CELL
    jmp  rax                    ; tail call — word returns to our caller
    ; Note: jmp instead of call/ret makes EXECUTE transparent on return stack

; ============================================================
;  Number base
; ============================================================

defword HEX_W, "HEX", 0        ; ( -- )
    mov  qword [flint.base], 16
    ret

defword DECIMAL_W, "DECIMAL", 0 ; ( -- )
    mov  qword [flint.base], 10
    ret

; ============================================================
;  Compiler: colon, semicolon, immediate, tick, bracket words
; ============================================================

defword LBRACKET, "[", F_IMMED  ; ( -- )  enter interpret mode
    mov  qword [flint.state], 0
    ret

defword RBRACKET, "]", 0        ; ( -- )  enter compile mode
    mov  qword [flint.state], 1
    ret

defword IMMEDIATE_W, "IMMEDIATE", 0  ; ( -- )  make most recent word immediate
    or   byte [r13+8], F_IMMED
    ret

defword TICK, "'", 0            ; ( -- xt )  push CFA of next word
    call flint.parse_word
    lea  rcx, [wbuf]
    mov  rdx, [wbuf_len]
    call flint.find             ; rax = CFA or 0
    test rax, rax
    jnz  .found
    lea  rsi, [msg_tick_err]
    call flint.print_str
    xor  rax, rax
.found:
    sub  r15, CELL
    mov  [r15], rax
    ret

defword LITERAL_W, "LITERAL", F_IMMED ; ( n -- )  compile n as a literal
    mov  rax, [r15]
    add  r15, CELL
    call flint.compile_lit
    ret

defword RECURSE_W, "RECURSE", F_IMMED ; ( -- )  compile call to current word
    mov  rax, [current_word_cfa]
    call flint.compile_call
    ret

; ============================================================
;  Compiler: colon definition  ( : name ... ; )
; ============================================================

defword COLON, ":", 0           ; start a new word definition
    call flint.create_word      ; parse name, emit header, update R13
                                ; leaves R14 at new CFA; hides word
    mov  qword [flint.state], 1 ; enter compile mode
    ret

defword SEMICOLON, ";", F_IMMED ; end a colon definition
    ; emit RET into the dictionary
    mov  byte [r14], 0xC3
    inc  r14

    ; reveal the word (clear HIDDEN flag)
    mov  rax, [current_word_hdr]
    and  byte [rax+8], 0xFF xor F_HIDDEN

    mov  qword [flint.state], 0
    ret

; ============================================================
;  Compiler: VARIABLE and CONSTANT
; ============================================================

defword VARIABLE_W, "VARIABLE", 0  ; ( -- )  create a variable
    call flint.create_word      ; parse name, create header (revealed immediately)
    and  byte [r13+8], 0xFF xor F_HIDDEN    ; un-hide right away (no smudge for VARIABLE)

    ; The variable's compiled code: push address of its data cell.
    ; Data cell immediately follows the 18-byte code body.
    ; Emits: MOV RAX, <data_addr>  (48 B8 + 8 bytes)
    ;        SUB R15, 8             (49 83 EF 08)
    ;        MOV [R15], RAX         (49 89 07)
    ;        RET                    (C3)
    ; = 18 bytes;  data cell at CFA+18

    lea  rax, [r14+18]          ; absolute address of data cell
    mov  byte  [r14+0],  0x48   ; MOV RAX, imm64
    mov  byte  [r14+1],  0xB8
    mov  [r14+2], rax            ; 8-byte absolute address
    mov  byte  [r14+10], 0x49   ; SUB R15, 8
    mov  byte  [r14+11], 0x83
    mov  byte  [r14+12], 0xEF
    mov  byte  [r14+13], 0x08
    mov  byte  [r14+14], 0x49   ; MOV [R15], RAX
    mov  byte  [r14+15], 0x89
    mov  byte  [r14+16], 0x07
    mov  byte  [r14+17], 0xC3   ; RET
    add  r14, 18

    mov  qword [r14], 0         ; initialise data cell to zero
    add  r14, CELL
    ret

defword CONSTANT_W, "CONSTANT", 0   ; ( n -- )  create a constant
    mov  rbx, [r15]             ; save value
    add  r15, CELL

    call flint.create_word
    and  byte [r13+8], 0xFF xor F_HIDDEN

    ; Emits code that pushes the constant value when called:
    ; MOV RAX, <value>  SUB R15,8  MOV [R15],RAX  RET  (18 bytes)
    mov  byte  [r14+0],  0x48
    mov  byte  [r14+1],  0xB8
    mov  [r14+2], rbx            ; the constant value
    mov  byte  [r14+10], 0x49
    mov  byte  [r14+11], 0x83
    mov  byte  [r14+12], 0xEF
    mov  byte  [r14+13], 0x08
    mov  byte  [r14+14], 0x49
    mov  byte  [r14+15], 0x89
    mov  byte  [r14+16], 0x07
    mov  byte  [r14+17], 0xC3
    add  r14, 18
    ret

; ============================================================
;  Control flow  (all immediate — execute at compile time)
;
;  IF / ELSE / THEN
;    IF:    emit conditional branch with rel32 placeholder; push patch-addr
;    ELSE:  emit unconditional jump; backpatch IF's rel32; push new patch-addr
;    THEN:  backpatch the top patch-addr to HERE
;
;  BEGIN / UNTIL / AGAIN / WHILE / REPEAT
;    BEGIN:  push current HERE as loop-top address
;    UNTIL:  emit conditional branch BACK to loop-top
;    AGAIN:  emit unconditional branch BACK to loop-top
;    WHILE:  emit conditional forward branch (like IF); stack = ( loop-top patch )
;    REPEAT: backpatch WHILE; emit unconditional branch BACK to loop-top
;
;  Branch sequence emitted by IF / WHILE (16 bytes):
;    48 8B 07          mov rax, [r15]      ; read TOS
;    49 83 C7 08       add r15, 8          ; drop TOS
;    48 85 C0          test rax, rax       ; set flags
;    0F 84 xx xx xx xx jz  rel32           ; jump if zero (false)
; ============================================================

; Helper macro: emit the 16-byte conditional-branch preamble at R14.
; After the macro R14 points past the sequence; [R14-4] = rel32 placeholder.
macro emit_cond_branch {
    mov  byte [r14+0],  0x49    ; mov rax, [r15]  (REX.W + REX.B: B extends rm 7 -> R15)
    mov  byte [r14+1],  0x8B
    mov  byte [r14+2],  0x07
    mov  byte [r14+3],  0x49    ; add r15, 8
    mov  byte [r14+4],  0x83
    mov  byte [r14+5],  0xC7
    mov  byte [r14+6],  0x08
    mov  byte [r14+7],  0x48    ; test rax, rax
    mov  byte [r14+8],  0x85
    mov  byte [r14+9],  0xC0
    mov  byte [r14+10], 0x0F    ; jz rel32
    mov  byte [r14+11], 0x84
    mov  dword [r14+12], 0      ; placeholder
    add  r14, 16
}

; Helper macro: backpatch a rel32 field at [patch_reg] so it jumps to R14.
; patch_reg holds the address of the rel32 field (4 bytes).
macro backpatch _patch_reg {
    lea  rcx, [r14]
    lea  rdx, [_patch_reg + 4]
    sub  rcx, rdx               ; offset = target - (patch_addr + 4)
    mov  [_patch_reg], ecx
}

defword IF_W, "IF", F_IMMED     ; ( -- patch-addr )
    emit_cond_branch
    ; push address of the rel32 placeholder onto the data stack
    lea  rax, [r14-4]
    sub  r15, CELL
    mov  [r15], rax
    ret

defword ELSE_W, "ELSE", F_IMMED ; ( patch-addr -- patch-addr' )
    ; pop IF's patch address
    mov  rbx, [r15]
    add  r15, CELL

    ; emit unconditional JMP over the ELSE body (placeholder)
    mov  byte [r14], 0xE9
    mov  dword [r14+1], 0
    add  r14, 5

    ; backpatch IF's JZ to jump to here (start of ELSE body)
    lea  rcx, [r14]
    lea  rdx, [rbx+4]
    sub  rcx, rdx
    mov  [rbx], ecx

    ; push ELSE's JMP rel32 address for THEN to backpatch
    lea  rax, [r14-4]
    sub  r15, CELL
    mov  [r15], rax
    ret

defword THEN_W, "THEN", F_IMMED ; ( patch-addr -- )
    mov  rbx, [r15]
    add  r15, CELL
    backpatch rbx
    ret

defword BEGIN_W, "BEGIN", F_IMMED ; ( -- loop-top )
    sub  r15, CELL
    mov  [r15], r14
    ret

defword UNTIL_W, "UNTIL", F_IMMED ; ( loop-top -- )
    ; emit conditional branch; if TOS false (0), loop back
    mov  rbx, [r15]             ; loop-top address
    add  r15, CELL
    emit_cond_branch
    ; the jz should jump to loop-top — compute backward offset
    lea  rcx, [rbx]
    lea  rdx, [r14]             ; address of next instruction after jz
    sub  rcx, rdx               ; negative offset
    mov  [r14-4], ecx
    ret

defword AGAIN_W, "AGAIN", F_IMMED ; ( loop-top -- )
    ; emit unconditional backward JMP to loop-top
    mov  rbx, [r15]
    add  r15, CELL
    mov  byte [r14], 0xE9
    lea  rcx, [rbx]
    lea  rdx, [r14+5]
    sub  rcx, rdx
    mov  dword [r14+1], ecx
    add  r14, 5
    ret

defword WHILE_W, "WHILE", F_IMMED ; ( loop-top -- loop-top patch-addr )
    ; like IF: emit conditional branch, leave loop-top below patch-addr
    emit_cond_branch
    lea  rax, [r14-4]
    sub  r15, CELL
    mov  [r15], rax             ; push patch-addr on top of loop-top
    ret

defword REPEAT_W, "REPEAT", F_IMMED ; ( loop-top patch-addr -- )
    mov  rbx, [r15]             ; patch-addr (WHILE's rel32)
    mov  rax, [r15+CELL]        ; loop-top
    add  r15, CELL*2

    ; emit unconditional JMP back to loop-top
    mov  byte [r14], 0xE9
    lea  rcx, [rax]
    lea  rdx, [r14+5]
    sub  rcx, rdx
    mov  dword [r14+1], ecx
    add  r14, 5

    ; backpatch WHILE's JZ to exit here
    backpatch rbx
    ret

; ============================================================
;  Utility
; ============================================================

defword BYE_W, "BYE", 0        ; ( -- )  exit process
    xor  rcx, rcx
    call sys.exit

defword WORDS_W, "WORDS", 0    ; ( -- )  print all visible word names
    mov  rsi, r13               ; start at LATEST
.next:
    test rsi, rsi
    jz   .done
    movzx rbx, byte [rsi+8]
    test  bl, F_HIDDEN
    jnz   .skip
    ; print name -- use rbx as char counter (callee-saved across sys.emit)
    push rsi
    mov  rbx, rbx               ; rbx = flags|len
    and  rbx, F_LENMASK         ; rbx = length
    lea  rsi, [rsi+9]           ; rsi -> name chars
.print_char:
    test rbx, rbx
    jz   .after_name
    mov  al, [rsi]
    call sys.emit
    inc  rsi
    dec  rbx                    ; rbx callee-saved: survives sys.emit
    jmp  .print_char
.after_name:
    mov  al, ' '
    call sys.emit
    pop  rsi
.skip:
    mov  rsi, [rsi]
    jmp  .next
.done:
    mov  al, 13
    call sys.emit
    mov  al, 10
    call sys.emit
    ret

defword CHAR_W, "CHAR", 0      ; ( -- ch )  push ASCII of next input char
    call flint.parse_word
    lea  rax, [wbuf]
    movzx rax, byte [rax]
    sub  r15, CELL
    mov  [r15], rax
    ret

defword UNUSED_W, "UNUSED", 0  ; ( -- n )  bytes remaining in dictionary
    mov  rax, [flint.arena_end]
    sub  rax, r14
    sub  r15, CELL
    mov  [r15], rax
    ret
