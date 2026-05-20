# Flint FORTH

A minimal, fast FORTH interpreter and compiler written in
[FASM](https://flatassembler.net) x86-64 assembly. Windows is the primary
target; Linux and bare-metal stubs are included for future completion.

---

## Quick start

```
fasm flint.asm flint.exe
flint.exe
```

Requires **FASM 1.73 or later** (flat assembler, free — https://flatassembler.net).

---

## Examples

Each line below is typed at the Flint prompt. Expected output follows the
`→` marker. Flint prints ` ok` after every successfully interpreted line.

### Stack and arithmetic

```forth
1 2 + .
→ 3 ok

10 3 /MOD . .
→ 3 1 ok
```

`/MOD` leaves quotient then remainder; `.` prints TOS, so quotient prints
first then remainder.

```forth
5 DUP * .
→ 25 ok

1 2 3 .S
→ <3> 1 2 3  ok
```

`.S` prints the entire stack non-destructively, prefixed by `<depth>`.

### Defining words

```forth
: SQUARE  DUP * ;
5 SQUARE .
→ 25 ok

: CUBE  DUP DUP * * ;
3 CUBE .
→ 27 ok

: MAX2  2DUP < IF SWAP THEN DROP ;
7 3 MAX2 .
→ 7 ok
```

### Conditionals

```forth
: SIGN  DUP 0< IF DROP -1 ELSE 0> IF 1 ELSE 0 THEN THEN ;
-5 SIGN .
→ -1 ok
0 SIGN .
→ 0 ok
7 SIGN .
→ 1 ok
```

### Counted loops

```forth
: COUNTDOWN  BEGIN DUP . 1- DUP 0= UNTIL DROP ;
5 COUNTDOWN
→ 5 4 3 2 1  ok
```

```forth
: STARS  0 BEGIN OVER OVER > WHILE 42 EMIT 1+ REPEAT 2DROP CR ;
7 STARS
→ *******
 ok
```

42 is ASCII `*`.

### Variables and constants

```forth
VARIABLE COUNTER
0 COUNTER !
COUNTER @ .
→ 0 ok

5 COUNTER !
COUNTER @ .
→ 5 ok

1 COUNTER +!
COUNTER @ .
→ 6 ok

42 CONSTANT ANSWER
ANSWER .
→ 42 ok
```

### Number bases

```forth
HEX
FF .
→ FF ok

1A2B .
→ 1A2B ok

DECIMAL
255 .
→ 255 ok
```

In `HEX` mode both input and output use base 16. The `$` and `0x` prefixes
force hex regardless of the current base: `$FF` and `0xFF` both parse as 255
even in decimal mode.

### Negative numbers

```forth
-42 .
→ -42 ok

-1 INVERT .
→ 0 ok

HEX
-1 .
→ FFFFFFFFFFFFFFFF ok
DECIMAL
```

### Character output

```forth
: GREET  72 EMIT 101 EMIT 108 EMIT 108 EMIT 111 EMIT CR ;
GREET
→ Hello
 ok
```

### Dictionary introspection

```forth
WORDS
```

Lists every visible word newest-first. Defined words appear at the top.

```forth
UNUSED .
```

Prints remaining bytes in the dictionary region (starts at 1 MB).

### Exiting

```forth
BYE
```

Calls `ExitProcess(0)` and terminates cleanly.

---

## Architecture

### Threading model — Subroutine Threaded Code (STC)

Flint uses **subroutine-threaded code**. Every FORTH word is an ordinary
x86-64 function that ends with `RET`. Colon definitions are sequences of
`CALL` instructions. No separate interpreter pointer register is needed:
the CPU's own `RIP` and return-address stack serve that role directly.

Benefits over classic DTC (direct-threaded code):
- Existing CPU branch-prediction hardware works natively.
- Short words can be inlined by the compiler without any special case.
- No `NEXT` macro; generated code is standard machine code.
- Easy to disassemble and debug with any x86 disassembler.

### Register contract

All registers in the contract are **callee-saved** under both the
Microsoft x64 ABI (Windows) and the System V AMD64 ABI (Linux), so
Win32 API calls inside `sys.*` functions cannot disturb them.

| Register | Role |
|----------|------|
| `RSP` | Native call / return stack (STC return addresses) |
| `R15` | Data stack pointer — `[R15]` = TOS, grows downward |
| `R14` | `HERE` — dictionary write cursor, grows upward |
| `R13` | `LATEST` — pointer to the most recent word header |
| `R12` | FORTH return stack pointer — `>R` / `R>` values |
| `RBX` | Scratch — free within a primitive |

### Memory layout

At startup, `sys.init` allocates a single contiguous arena and partitions
it as follows:

```
base
  ├─ [0 .. DSTACK_SIZE)                    data stack   (64 KB)
  │    R15 starts at base+DSTACK_SIZE (empty stack), grows downward
  ├─ [DSTACK_SIZE .. DSTACK_SIZE+RSTACK_SIZE)  return stack (64 KB)
  │    R12 starts at top, grows downward
  └─ [DSTACK_SIZE+RSTACK_SIZE .. ARENA_SIZE)   dictionary   (1 MB)
       R14 starts here, grows upward
```

On Windows the arena is allocated with `PAGE_EXECUTE_READWRITE` so that
FORTH words compiled into it at runtime can be executed directly.

### Dictionary header format

```
offset  size   field
  0       8    link        — pointer to previous header (0 = end of chain)
  8       1    flags|len   — high bits: flags; low 5 bits: name length (max 31)
  9      len   name        — name bytes (not null-terminated)
  9+len   —    padding     — zeroes to next CELL (8-byte) boundary
  *       —    code        — machine code starts here (the CFA)
```

Flag bits:

| Bit | Constant | Meaning |
|-----|----------|---------|
| 7 | `F_IMMED` (0x80) | Immediate — executed even in compile mode |
| 5 | `F_HIDDEN` (0x20) | Hidden during compilation (smudge bit) |
| 4:0 | `F_LENMASK` (0x1F) | Name length |

### Platform abstraction

All syscalls and OS interactions live in `platform/`:

| File | Target | Mechanism |
|------|--------|-----------|
| `windows.inc` | Windows x64 | Win32 API via kernel32.dll imports |
| `linux.inc` | Linux x86-64 | Raw `syscall` instruction (stub) |
| `bare.inc` | Bare x86-64 | COM1 UART port I/O (stub) |

**Windows note:** Windows deliberately has no stable public syscall ABI —
syscall numbers change between OS versions. All Windows code must go through
DLL imports. Flint's platform layer fully encapsulates this: `sys.emit`,
`sys.key`, `sys.init`, and `sys.exit` are the only platform-specific symbols
referenced by the rest of the codebase.

Each `sys.*` function on Windows enforces 16-byte RSP alignment and
allocates the required 32-byte shadow space (48 bytes for calls with five
or more arguments) before any Win32 call, so callers need not worry about
alignment.

### The outer interpreter (QUIT loop)

`flint.quit` in `boot.inc` implements the standard FORTH outer loop:

1. `flint.refill` — read one line into `ibuf` with character echo and
   backspace handling.
2. `flint.parse_word` — extract the next whitespace-delimited token.
3. `flint.find` — walk the dictionary chain from `LATEST` backward,
   comparing length then name bytes (case-sensitive).
4. If found and in interpret mode (or `IMMEDIATE`): execute via `CALL rax`.
5. If found and in compile mode: emit a `CALL` into the dictionary.
6. If not found: `flint.parse_num` tries decimal (`42`, `-7`) and hex
   (`$FF`, `0xFF`, `-$1A`). On success the value is pushed (interpret) or
   compiled as a literal (compile). On failure, print `?` and refill.
7. At end of line, print ` ok` and loop.

### Colon compiler

`:` calls `flint.create_word` which:
- parses the word name,
- emits a dictionary header (link + flags/len + name, aligned to 8 bytes),
- marks the word `HIDDEN` (smudge bit),
- sets `STATE = 1` (compile mode).

In compile mode, each found word causes `flint.compile_call` to emit a
`CALL` instruction:

- **rel32** (5 bytes): used when the target is within ±2 GB of HERE.
- **abs64** (12 bytes): `MOV RAX, imm64; CALL RAX` — fallback for targets
  outside the 2 GB window (unlikely in a 1 MB dictionary, but handled).

`;` emits a `RET` byte (0xC3), clears the `HIDDEN` flag, and sets
`STATE = 0`.

### Literal compilation

Numbers encountered in compile mode are compiled using the **lit_helper
trick**:

```
CALL lit_helper     ; 5 bytes — relative call
DQ   value          ; 8 bytes — the literal value embedded in the code
```

`lit_helper` pops the return address (which points directly at the `DQ`),
reads the 8-byte value, advances the return address past the `DQ`, pushes
that return address back, and pushes the value onto the data stack. This
keeps the code stream linear with no separate constant pool.

### Control flow

`IF`, `ELSE`, `THEN`, `BEGIN`, `WHILE`, `REPEAT`, `UNTIL`, and `AGAIN`
are **immediate** words that emit actual x86 branch instructions directly
into the dictionary at compile time.

`IF` and `WHILE` emit a 16-byte preamble that pops TOS and conditionally
jumps:

```
48 8B 07            mov rax, [r15]      ; read TOS
49 83 C7 08         add r15, 8          ; drop TOS
48 85 C0            test rax, rax
0F 84 xx xx xx xx  jz  rel32           ; branch if false (0)
```

`THEN`/`REPEAT` backpatch the `rel32` field to the current `HERE`.
`AGAIN`/`REPEAT` emit a `JMP rel32` backward to the `BEGIN` address (left
on the data stack by `BEGIN`). FORTH TRUE = −1, so `TEST rax, rax; JZ` is
correct for any non-zero true value.

### VARIABLE and CONSTANT

Both words call `flint.create_word` to create the header and then emit
18 bytes of inline machine code directly:

```asm
; VARIABLE: push address of data cell
48 B8 <data_addr>   MOV RAX, imm64   ; absolute address of data cell
49 83 EF 08         SUB R15, 8
49 89 07            MOV [R15], RAX
C3                  RET

; CONSTANT: push the constant value
48 B8 <value>       MOV RAX, imm64   ; the constant value
49 83 EF 08         SUB R15, 8
49 89 07            MOV [R15], RAX
C3                  RET
```

For `VARIABLE`, the data cell (initialised to 0) immediately follows the
18-byte code block. Its address is computed as `CFA + 18` at definition
time, so it is baked in as an absolute address and requires no indirection
at runtime.

### >R and R@

The FORTH return stack (`>R`, `R>`, `R@`) uses register `R12` as a
dedicated stack pointer, completely separate from `RSP`. This avoids the
classic STC complication where return addresses and user-pushed values would
be interleaved on the native stack.

---

## Source file layout

```
flint/
├── flint.asm          Top-level: includes everything in the right order
├── config.inc         Compile-time constants (CELL, flags, arena sizes)
├── macros.inc         defword macro, stack helpers, register contract docs
├── platform/
│   ├── detect.inc     TARGET selection (windows / linux / bare)
│   ├── windows.inc    Win32 API layer  ← primary, fully implemented
│   ├── linux.inc      Linux syscall layer  (stub)
│   └── bare.inc       Bare-metal COM1 layer (stub)
├── primitives.inc     ~60 kernel words in assembly
├── dict.inc           flint.find, compile helpers, number printers
└── boot.inc           flint.start, flint.quit, refill, parse_word, parse_num
```

### Assembly order matters

`flint.asm` includes files in a specific order chosen to satisfy two FASM
constraints:

1. `format PE64` must be the first effective directive → platform include
   comes first.
2. `dq FLINT_LATEST` (the final dictionary tail pointer stored in `.data`)
   must be assembled *after* all `defword` calls that update the
   `FLINT_LATEST` numeric variable → the `.data` section definition in
   `flint.asm` comes after `include 'primitives.inc'`.

---

## Word reference

### Stack
`DUP  DROP  SWAP  OVER  ROT  -ROT  NIP  TUCK  ?DUP`
`2DUP  2DROP  2SWAP  2OVER`

### Arithmetic
`+  -  *  /MOD  /  MOD  NEGATE  ABS  MAX  MIN  1+  1-  2*  2/`

### Bitwise / shift
`AND  OR  XOR  INVERT  LSHIFT  RSHIFT  ARSHIFT`

### Comparison  (TRUE = −1)
`=  <>  <  >  <=  >=  U<  U>  0=  0<>  0<  0>`

### Memory
`@  !  C@  C!  2@  2!  +!  MOVE  FILL`

### Return stack
`>R  R>  R@  2>R  2R>  2R@`

### I/O
`EMIT  KEY  CR  SPACE  SPACES  TYPE  COUNT`

### Output
`. (dot)  U.  .S  DEPTH`

### Dictionary / compiler
`HERE  ALLOT  ,  C,  CELLS  CELL+  ALIGN  STATE  BASE  LATEST`
`: (colon)  ; (semicolon)  IMMEDIATE  '  [  ]  LITERAL  RECURSE`
`VARIABLE  CONSTANT  EXECUTE`

### Control flow  (compile-time)
`IF  ELSE  THEN  BEGIN  UNTIL  AGAIN  WHILE  REPEAT`

### Utility
`EMIT  KEY  WORDS  CHAR  HEX  DECIMAL  UNUSED  BYE`

---

## Design notes and trade-offs

**No TOS caching.** A common STC optimisation caches the top-of-stack value
in a dedicated register (e.g. `RBX`) to avoid a memory round-trip on every
push and pop. Flint deliberately omits this: TOS caching complicates every
primitive (each must decide whether to load from cache or memory) and makes
the calling convention harder to reason about. It is the most impactful
single optimisation available once correctness is established.

**No guard pages.** A production interpreter would place an
`MEM_RESERVE`-only page just below each stack to catch overflows with an
access violation. Flint allocates a plain contiguous region. Stack overflows
silently corrupt adjacent memory. Guard-page support is straightforward to
add with `VirtualAlloc` + `VirtualProtect`.

**Case-sensitive.** Word names are matched exactly as stored. By convention
all built-in words are uppercase. User words are whatever case they are
defined in.

**Words are TRUE = −1.** `0=`, `<`, `=`, etc. push −1 for true and 0 for
false, following the ANS/ISO FORTH standard. `AND`, `OR`, `XOR`, `INVERT`
operate bitwise and compose correctly with boolean results.

**No `DOES>` or `CREATE`.** The definitional words `CREATE` and `DOES>`
that allow arbitrary run-time behaviour in defined words are not yet
implemented. `VARIABLE` and `CONSTANT` cover the most common cases.

**No `."`.** String literal output in compiled words (`." hello"`) is not
yet implemented. It requires embedding a counted string in the code stream
and a helper similar to `lit_helper`.

---

## Extending Flint

The clearest extension points:

- **New primitives:** add a `defword` entry in `primitives.inc`. The macro
  handles the header; just write the body ending in `ret`.
- **DOES>:** implement `CREATE` (like `VARIABLE` but without the push-addr
  body) then `DOES>` which patches the header's code pointer to a
  user-supplied runtime action. See Forth 2012 specification §6.1.1250.
- **String literals:** add `lit_str_helper` analogous to `lit_helper` that
  reads a counted string from the code stream and pushes addr/len.
- **Linux completion:** `platform/linux.inc` has all the right function
  stubs; fill in the ELF64 entry sequence and `sys.init` memory setup.
- **Optimisation:** add TOS caching in `RBX`. Every primitive that reads
  TOS loads from `RBX` instead of `[R15]`; every primitive that writes TOS
  stores to `RBX`. Pushes also store the old `RBX` to `[R15-CELL]`. Measure
  first — the CPU's L1 cache makes the raw benefit smaller than it looks on
  paper.
