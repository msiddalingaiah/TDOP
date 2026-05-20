; =============================================================================
; boot.inc -- outer interpreter (QUIT loop), input, number parsing, startup
; =============================================================================

; ============================================================
;  Entry point
; ============================================================

flint.start:
    call sys.init
    test rax, rax
    jz   .init_fail

    ; R15 = data stack ptr (grows downward from top of DSTACK region)
    lea  r15, [rax + DSTACK_SIZE]
    mov  [flint.dstack_base], r15

    ; R12 = FORTH return stack ptr (grows downward from top of RSTACK region)
    lea  r12, [rax + DSTACK_SIZE + RSTACK_SIZE]

    ; R14 = HERE (grows upward from base of dictionary region)
    lea  r14, [rax + DSTACK_SIZE + RSTACK_SIZE]

    ; arena end for UNUSED
    lea  rcx, [rax + ARENA_SIZE]
    mov  [flint.arena_end], rcx

    ; R13 = LATEST (load from data-section pointer; gets a base relocation)
    mov  r13, [flint.latest_static]

    lea  rsi, [banner_str]
    call flint.print_str

    jmp  flint.quit

.init_fail:
    xor  rcx, rcx
    call sys.exit

; ============================================================
;  flint.quit -- outer interpreter loop
; ============================================================

flint.quit:
    mov  qword [flint.state], 0

.refill:
    call flint.refill

.word_loop:
    call flint.parse_word
    cmp  qword [wbuf_len], 0
    jz   .eol

    lea  rcx, [wbuf]
    mov  rdx, [wbuf_len]
    call flint.find             ; rax = CFA or 0,  rbx = flags byte

    test rax, rax
    jz   .not_in_dict

    ; found -- immediate words always execute
    test bl, F_IMMED
    jnz  .execute_word

    cmp  qword [flint.state], 0
    je   .execute_word

    ; compile mode: emit CALL into dictionary
    call flint.compile_call
    jmp  .word_loop

.execute_word:
    call rax
    jmp  .word_loop

.not_in_dict:
    lea  rcx, [wbuf]
    mov  rdx, [wbuf_len]
    call flint.parse_num        ; rax = value, rdx = 1 ok / 0 fail

    test rdx, rdx
    jz   .error

    cmp  qword [flint.state], 0
    je   .push_num

    ; compile mode: emit literal
    call flint.compile_lit
    jmp  .word_loop

.push_num:
    sub  r15, CELL
    mov  [r15], rax
    jmp  .word_loop

    ; --- error: unknown word ---
    ; Use rbx as loop counter -- callee-saved, survives sys.emit calls.
.error:
    lea  rsi, [wbuf]
    mov  rbx, [wbuf_len]
.print_err_char:
    test rbx, rbx
    jz   .print_q
    mov  al, [rsi]
    call sys.emit
    inc  rsi
    dec  rbx                    ; rbx is callee-saved: survives sys.emit
    jmp  .print_err_char
.print_q:
    lea  rsi, [msg_error]
    call flint.print_str
    jmp  .refill                ; discard line, no "ok"

.eol:
    cmp  qword [flint.state], 0
    jne  .refill
    lea  rsi, [msg_ok]
    call flint.print_str
    jmp  .refill

; ============================================================
;  flint.refill -- read one line into ibuf
;
;  Windows console in cooked mode (ENABLE_LINE_INPUT) echoes characters
;  and line-edits before returning from ReadFile.  We must NOT echo
;  ourselves or every character appears twice.
;
;  Uses rbx as the character counter because rbx is callee-saved and
;  will not be clobbered by sys.key (ReadFile) calls.
; ============================================================
flint.refill:
    mov  qword [ibuf_pos], 0
    mov  qword [ibuf_len], 0
    xor  ebx, ebx               ; rbx = char count (callee-saved, safe across sys.key)

.char:
    call sys.key                ; al = next byte
    cmp  al, 10                 ; LF -> end of line
    je   .done
    cmp  al, 13                 ; CR -> skip (part of CRLF)
    je   .char
    ; ignore backspace/DEL -- cooked mode handles line editing for us
    cmp  rbx, IBUF_SIZE-1
    jge  .char
    mov  [ibuf+rbx], al
    inc  rbx
    jmp  .char

.done:
    ; emit CR+LF so output starts on fresh line after the echoed input
    mov  al, 13
    call sys.emit
    mov  al, 10
    call sys.emit
    mov  [ibuf_len], rbx
    ret

; ============================================================
;  flint.parse_word -- extract next whitespace-delimited token from ibuf
; ============================================================
flint.parse_word:
    mov  qword [wbuf_len], 0
    mov  rsi, [ibuf_pos]
    mov  rdx, [ibuf_len]

.skip_ws:
    cmp  rsi, rdx
    jge  .done_empty
    movzx rax, byte [ibuf+rsi]
    inc  rsi
    cmp  al, ' '
    je   .skip_ws
    cmp  al, 9
    je   .skip_ws

    lea  rbx, [wbuf]
    xor  ecx, ecx
    mov  [rbx+rcx], al
    inc  rcx

.collect:
    cmp  rsi, rdx
    jge  .end_token
    movzx rax, byte [ibuf+rsi]
    inc  rsi
    cmp  al, ' '
    je   .end_token
    cmp  al, 9
    je   .end_token
    cmp  rcx, WBUF_SIZE-1
    jge  .end_token
    mov  [rbx+rcx], al
    inc  rcx
    jmp  .collect

.end_token:
    mov  [wbuf_len], rcx

.done_empty:
    mov  [ibuf_pos], rsi
    ret

; ============================================================
;  flint.parse_num -- try to parse wbuf as an integer
;
;  Supports decimal (42, -7) and hex ($FF, 0xFF, -$1A, -0xFF).
;
;  in:  RCX = string address,  RDX = length
;  out: RAX = value  (only valid when RDX = 1)
;       RDX = 1 success, 0 failure
; ============================================================
flint.parse_num:
    test rdx, rdx
    jz   .fail

    xor  rax, rax
    mov  rsi, rcx
    mov  rcx, rdx

    xor  r8d, r8d               ; sign flag
    cmp  byte [rsi], '-'
    jne  .check_base
    mov  r8d, 1
    inc  rsi
    dec  rcx
    jz   .fail

.check_base:
    cmp  byte [rsi], '$'
    jne  .check_0x
    inc  rsi
    dec  rcx
    jz   .fail
    jmp  .hex_digits

.check_0x:
    cmp  rcx, 2
    jl   .base_digits
    cmp  byte [rsi],   '0'
    jne  .base_digits
    cmp  byte [rsi+1], 'x'
    je   .skip2
    cmp  byte [rsi+1], 'X'
    jne  .base_digits
.skip2:
    add  rsi, 2
    sub  rcx, 2
    jz   .fail

.hex_digits:
    test rcx, rcx
    jz   .apply_sign
    movzx rbx, byte [rsi]
    inc  rsi
    dec  rcx
    sub  bl, '0'
    jb   .fail
    cmp  bl, 9
    jle  .hex_have_digit
    sub  bl, 'A'-'0'-10
    jb   .fail
    cmp  bl, 15
    jle  .hex_have_digit
    sub  bl, 'a'-'A'
    jb   .fail
    cmp  bl, 15
    jg   .fail
.hex_have_digit:
    shl  rax, 4
    movzx rbx, bl
    or   rax, rbx
    jmp  .hex_digits

; --- default: parse using flint.base (honours HEX / DECIMAL) ----------------
.base_digits:
    test rcx, rcx
    jz   .apply_sign
    movzx rbx, byte [rsi]
    inc  rsi
    dec  rcx

    ; convert character to digit value in BL
    cmp  bl, '0'
    jb   .fail
    cmp  bl, '9'
    jle  .is_dec_digit
    cmp  bl, 'A'
    jb   .fail
    cmp  bl, 'F'
    jle  .is_upper_hex
    cmp  bl, 'a'
    jb   .fail
    cmp  bl, 'f'
    jg   .fail
    sub  bl, 'a' - 10           ; 'a'->10 .. 'f'->15
    jmp  .check_range
.is_upper_hex:
    sub  bl, 'A' - 10           ; 'A'->10 .. 'F'->15
    jmp  .check_range
.is_dec_digit:
    sub  bl, '0'                ; '0'->0  .. '9'->9
.check_range:
    cmp  rbx, [flint.base]      ; reject digit >= current base
    jge  .fail
    imul rax, qword [flint.base]; accumulate: rax = rax * base + digit
    movzx rbx, bl
    add  rax, rbx
    jmp  .base_digits

.apply_sign:
    test r8d, r8d
    jz   .ok
    neg  rax
.ok:
    mov  rdx, 1
    ret
.fail:
    xor  rdx, rdx
    ret

; ============================================================
;  Constant data
; ============================================================

banner_str  db  "Flint FORTH  (Windows x64)", 13, 10
            db  "type WORDS to list words, BYE to exit", 13, 10
            db  0

msg_ok      db  " ok", 13, 10, 0
msg_error   db  " ?", 13, 10, 0
