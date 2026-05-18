; =============================================================================
; tokenizer.asm - S-expression tokenizer
;
; Public interface:
;   tok_next  rcx=ptr to Token struct → rax=TOK_*
;
; The tokenizer consumes characters from hal_read_char and classifies them
; into the token types defined in defs.inc.  It maintains a one-character
; pushback buffer so that the character that ends an atom (a paren or
; whitespace) is available for the next call.
;
; Atom text is written into the static _tok_atom_buf and is valid until the
; next call to tok_next.  The caller must copy atoms it needs to keep.
;
; Stack discipline reminder:
;   Every procedure here is entered with RSP mod 16 = 8.
;   Each proc opens with push + sub to reach 0 mod 16 before any CALL.
; =============================================================================

ATOM_BUF_SIZE = 256

; ── Static data ──────────────────────────────────────────────────────────────

section '.data' data readable writeable

    _tok_pb_char  db 0              ; pushback character storage
    _tok_pb_valid db 0              ; 1 = _tok_pb_char is valid

    _tok_atom_buf rb ATOM_BUF_SIZE  ; atom accumulation buffer

; ── Internal helpers ─────────────────────────────────────────────────────────

section '.code' code readable executable

; _tok_getc — get the next character, consuming pushback first
; Out: al = character (0 = EOF)
; Clobbers: rax (and whatever hal_read_char clobbers)
_tok_getc:
    push rbx
    sub  rsp, 32                    ; shadow space; RSP now 0 mod 16

    cmp  byte [_tok_pb_valid], 0
    je   .call_hal

    movzx eax, byte [_tok_pb_char]
    mov   byte [_tok_pb_valid], 0
    jmp   .done

.call_hal:
    call hal_read_char              ; al = char; RSP 0 mod 16 before CALL ✓

.done:
    add  rsp, 32
    pop  rbx
    ret

; _tok_ungetc — push one character back into the stream (one slot only)
; In: cl = character
; Clobbers: nothing
_tok_ungetc:
    mov  [_tok_pb_char], cl
    mov  byte [_tok_pb_valid], 1
    ret

; ── Public interface ─────────────────────────────────────────────────────────

; tok_next — read and classify the next token
;
; In:  rcx = pointer to a caller-allocated Token struct (TOK_SIZE bytes)
; Out: rax = token type (TOK_*)
;      *rcx populated:
;        [TOK.type]  always set
;        [TOK.start] pointer into _tok_atom_buf (TOK_ATOM only)
;        [TOK.len]   byte count                 (TOK_ATOM only)
tok_next:
    ; Open frame
    ; Entry:     RSP mod 16 = 8
    ; push rbx:             = 0
    ; push r12:             = 8
    ; push r13:             = 0
    ; sub  32:              = 0   ← all inner CALLs are safe from here
    push rbx
    push r12
    push r13
    sub  rsp, 32

    mov  r12, rcx                   ; r12 = token struct pointer

    ; ── Skip whitespace ───────────────────────────────────────────────────
.skip_ws:
    call _tok_getc                  ; al = char
    cmp  al, ' '
    je   .skip_ws
    cmp  al, 9                      ; HT
    je   .skip_ws
    cmp  al, 13                     ; CR
    je   .skip_ws
    cmp  al, 10                     ; LF
    je   .skip_ws

    ; ── Classify first non-whitespace character ───────────────────────────

    cmp  al, 0                      ; internal EOF sentinel (0 bytes read)
    je   .eof
    cmp  al, 0x1A                   ; Ctrl-Z: console EOF
    je   .eof
    cmp  al, '('
    je   .lparen
    cmp  al, ')'
    je   .rparen

    ; ── Atom: accumulate until a delimiter is seen ────────────────────────
    lea  r13, [_tok_atom_buf]
    xor  rbx, rbx                   ; rbx = atom byte count

.atom_loop:
    ; Store current character (truncate silently if buffer is full)
    cmp  rbx, ATOM_BUF_SIZE - 1
    jge  .atom_next_char
    mov  [r13 + rbx], al
    inc  rbx

.atom_next_char:
    call _tok_getc                  ; al = next char

    ; Delimiter check — end the atom and decide whether to push back
    cmp  al, 0
    je   .atom_end_no_pb            ; real EOF: don't push back 0
    cmp  al, '('
    je   .atom_end_pb
    cmp  al, ')'
    je   .atom_end_pb
    cmp  al, ' '
    je   .atom_end_pb
    cmp  al, 9
    je   .atom_end_pb
    cmp  al, 13
    je   .atom_end_pb
    cmp  al, 10
    je   .atom_end_pb
    cmp  al, 0x1A
    je   .atom_end_pb               ; push Ctrl-Z back → next call → TOK_EOF

    jmp  .atom_loop

.atom_end_pb:
    mov  cl, al
    call _tok_ungetc

.atom_end_no_pb:
    mov  qword [r12 + TOK.type],  TOK_ATOM
    mov  qword [r12 + TOK.start], r13
    mov  qword [r12 + TOK.len],   rbx
    mov  rax, TOK_ATOM
    jmp  .done

    ; ── Single-character tokens ───────────────────────────────────────────
.lparen:
    mov  qword [r12 + TOK.type], TOK_LPAREN
    mov  rax, TOK_LPAREN
    jmp  .done

.rparen:
    mov  qword [r12 + TOK.type], TOK_RPAREN
    mov  rax, TOK_RPAREN
    jmp  .done

.eof:
    mov  qword [r12 + TOK.type], TOK_EOF
    mov  rax, TOK_EOF

    ; ── Close frame ───────────────────────────────────────────────────────
.done:
    add  rsp, 32
    pop  r13
    pop  r12
    pop  rbx
    ret
