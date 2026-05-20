; =============================================================================
; dict.inc — dictionary helpers for Flint
;
; Provides:
;   flint.find          dictionary search
;   flint.create_word   header creation (used by : VARIABLE CONSTANT)
;   flint.compile_call  emit a CALL into the dictionary at R14
;   flint.compile_lit   emit a pushed literal via the lit_helper trick
;   lit_helper          runtime support for compiled literals
;   flint.print_num     signed integer → stdout (uses flint.base)
;   flint.print_unum    unsigned integer → stdout (uses flint.base)
;   flint.print_str     print null-terminated string
; =============================================================================

; -----------------------------------------------------------------------------
; flint.find — search the dictionary for a word by name
;
; in:  RCX = name address (not counted string — raw bytes)
;      RDX = name length
; out: RAX = CFA if found, 0 if not found
;      RBX = flags|len byte if found (garbage if not found)
; -----------------------------------------------------------------------------
flint.find:
    push rsi rdi r8 r9

    mov  r8,  rcx               ; search name
    mov  r9,  rdx               ; search length
    mov  rsi, r13               ; walk from LATEST

.check:
    test rsi, rsi
    jz   .not_found             ; hit end of chain

    movzx rbx, byte [rsi+8]    ; flags|len byte
    test  bl, F_HIDDEN
    jnz   .next                 ; skip hidden (smudged) words

    mov  rax, rbx
    and  rax, F_LENMASK
    cmp  rax, r9
    jne  .next                  ; length mismatch

    ; compare name bytes (case-sensitive)
    lea  rdi, [rsi+9]           ; name in dictionary
    mov  rcx, r9
    push rsi
    mov  rsi, r8                ; name to find
    repe cmpsb
    pop  rsi
    jne  .next                  ; character mismatch

    ; match — compute CFA
    movzx rcx, byte [rsi+8]
    and   rcx, F_LENMASK
    lea   rax, [rsi+9]          ; skip link(8) + flags|len(1)
    add   rax, rcx              ; skip name
    add   rax, CELL-1
    and   rax, -CELL            ; align to CELL → CFA
    jmp   .done

.next:
    mov   rsi, [rsi]            ; follow link pointer
    jmp   .check

.not_found:
    xor   rax, rax

.done:
    pop  r9 r8 rdi rsi
    ret

; -----------------------------------------------------------------------------
; flint.create_word — parse next input token and emit a dictionary header.
;
; After return:
;   R14 points to the new CFA (code starts here)
;   R13 = new header address
;   [current_word_hdr] = new header address
;   [current_word_cfa] = new CFA address
;   The word is marked HIDDEN (smudged) — caller reveals it when ready.
; -----------------------------------------------------------------------------
flint.create_word:
    call flint.parse_word       ; fills wbuf / wbuf_len

    ; save header start
    mov  [current_word_hdr], r14

    ; emit link pointer
    mov  [r14], r13
    add  r14, CELL

    ; emit flags|len with HIDDEN set
    mov  rcx, [wbuf_len]
    or   rcx, F_HIDDEN
    mov  [r14], cl
    inc  r14

    ; emit name bytes
    lea  rsi, [wbuf]
    mov  rcx, [wbuf_len]
.copy:
    test rcx, rcx
    jz   .align
    mov  al, [rsi]
    mov  [r14], al
    inc  r14
    inc  rsi
    dec  rcx
    jmp  .copy

.align:
    add  r14, CELL-1
    and  r14, -CELL             ; align to CELL → CFA position

    ; update LATEST
    mov  rax, [current_word_hdr]
    mov  r13, rax
    mov  [current_word_cfa], r14

    ret

; -----------------------------------------------------------------------------
; flint.compile_call — emit a CALL to the word whose CFA is in RAX.
;
; Prefers rel32 (5 bytes) when the target is within ±2 GB of HERE+5.
; Falls back to absolute MOV RAX, imm64 + CALL RAX (12 bytes).
; RAX is clobbered.
; -----------------------------------------------------------------------------
flint.compile_call:
    push rbx

    ; attempt rel32
    lea  rcx, [rax]             ; target
    lea  rdx, [r14+5]           ; address of next instruction after CALL rel32
    sub  rcx, rdx               ; signed offset

    ; check whether offset fits in int32
    mov  rbx, rcx
    sar  rbx, 31                ; arithmetic sign-extension — 0 or -1 if fits
    cmp  rbx, 0
    je   .rel32
    cmp  rbx, -1
    je   .rel32

.abs64:
    ; emit: 48 B8 <imm64> FF D0 = MOV RAX, imm64; CALL RAX  (12 bytes)
    mov  byte [r14+0],  0x48
    mov  byte [r14+1],  0xB8
    mov  [r14+2], rax
    mov  byte [r14+10], 0xFF
    mov  byte [r14+11], 0xD0
    add  r14, 12
    jmp  .done

.rel32:
    mov  byte [r14], 0xE8       ; CALL rel32  (5 bytes)
    mov  dword [r14+1], ecx
    add  r14, 5

.done:
    pop  rbx
    ret

; -----------------------------------------------------------------------------
; flint.compile_lit — emit code to push a literal at runtime.
;
; Emits: CALL lit_helper (5 bytes) + DQ value (8 bytes) = 13 bytes.
; At runtime lit_helper pops the return address (which points to the DQ),
; reads the value, advances past it, and pushes it onto the data stack.
;
; in:  RAX = literal value to compile
; -----------------------------------------------------------------------------
flint.compile_lit:
    push rcx rdx

    ; CALL lit_helper — always use rel32
    lea  rcx, [lit_helper]
    lea  rdx, [r14+5]
    sub  rcx, rdx
    mov  byte [r14], 0xE8
    mov  dword [r14+1], ecx
    mov  [r14+5], rax           ; the literal value (8 bytes)
    add  r14, 13

    pop  rdx rcx
    ret

; -----------------------------------------------------------------------------
; lit_helper — runtime helper for compiled literals.
;
; Called by compiled words via: CALL lit_helper ; DQ value
; On entry [RSP] = address of the DQ value (the return address from CALL).
; Reads the value, adjusts the return to skip past it, pushes onto data stack.
; -----------------------------------------------------------------------------
lit_helper:
    pop  rax                    ; rax = pointer to embedded literal value
    mov  rcx, [rax]             ; read literal
    add  rax, CELL              ; advance past literal
    push rax                    ; "return" to instruction after the DQ
    sub  r15, CELL
    mov  [r15], rcx             ; push literal onto data stack
    ret

; -----------------------------------------------------------------------------
; flint.print_num — print signed 64-bit integer in RAX to stdout.
; Uses flint.base for the number base.
; -----------------------------------------------------------------------------
flint.print_num:
    test rax, rax
    jns  .positive
    push rax
    mov  al, '-'
    call sys.emit
    pop  rax
    neg  rax
.positive:
    ; fall through to unsigned printer
    jmp  flint.print_unum

; -----------------------------------------------------------------------------
; flint.print_unum — print unsigned 64-bit integer in RAX to stdout.
; -----------------------------------------------------------------------------
flint.print_unum:
    lea  rdi, [num_buf+23]
    mov  byte [rdi], 0          ; null terminator
.digit:
    xor  rdx, rdx
    div  qword [flint.base]     ; rdx = digit, rax = quotient
    cmp  rdx, 10
    jl   .decimal_digit
    add  rdx, 'A' - 10
    jmp  .store
.decimal_digit:
    add  rdx, '0'
.store:
    dec  rdi
    mov  [rdi], dl
    test rax, rax
    jnz  .digit
.emit:
    mov  al, [rdi]
    test al, al
    jz   .done
    call sys.emit
    inc  rdi
    jmp  .emit
.done:
    ret

; -----------------------------------------------------------------------------
; flint.print_str — print null-terminated string at RSI.
; Clobbers RSI, RAX.
; -----------------------------------------------------------------------------
flint.print_str:
.loop:
    mov  al, [rsi]
    test al, al
    jz   .done
    call sys.emit
    inc  rsi
    jmp  .loop
.done:
    ret

; Error string for '
msg_tick_err db "undefined word", 13, 10, 0
