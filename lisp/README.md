# clisp — A Clojure-like LISP in x64 FASM

A minimal but complete LISP interpreter written in Flat Assembler (FASM) for
Windows x64, producing a self-contained executable with no runtime
dependencies.  The codebase is structured around a HAL abstraction layer so
that a future bootable (BIOS/UEFI) port requires only a new platform file.

---

## Quick start

```
fasm main.asm lisp.exe   # or: make
lisp.exe
```

```clojure
clisp v0.0.1
> (def x 42)
42
> (defn square [n] (* n n))
#<lambda>
> (square x)
1764
> (let [a 3 b 4] (+ (* a a) (* b b)))
25
> (def v [1 2 3 4 5])
[1 2 3 4 5]
> (count v)
5
> (conj v 6)
[1 2 3 4 5 6]
> (defn fib [n] (if (< n 2) n (+ (fib (- n 1)) (fib (- n 2)))))
#<lambda>
> (fib 10)
55
> (display "hello world")
hello world
nil
> (exit)
```

Exit with `(exit)`, `(quit)`, or Ctrl-Z (EOF).

---

## File layout

```
main.asm                   Entry point, REPL loop, include hub
config.inc                 PLATFORM = PLATFORM_WINDOWS
defs.inc                   All constants and struct field offsets
Makefile                   GNU make / nmake build

platform/
    interface.inc          HAL contract (documentation only)
    windows.asm            Win32 implementation of the HAL

tokenizer.asm              Character reader + lexer
memory.asm                 Heap allocation, Cell/Cons/Sym/Vec factories
parser.asm                 Recursive-descent s-expression parser
printer.asm                Cell → text printer
env.asm                    Association-list environment + _global_env
eval.asm                   Evaluator: eval_cell, special forms, apply
primitives.asm             Built-in functions + primitives_init
```

Total source: ~3 500 lines across 12 files.

---

## Build system

FASM compiles everything in a single pass from `main.asm`, which `include`s
every other file in dependency order.  There is no linker step.

```makefile
fasm main.asm lisp.exe
```

The Makefile lists all source files as prerequisites so `make` rebuilds
whenever any file changes.

---

## Platform / HAL

`config.inc` sets `PLATFORM = PLATFORM_WINDOWS`.  The `if PLATFORM = ...`
block in `main.asm` selects the matching implementation file.

### HAL surface (`platform/interface.inc`)

| Procedure         | Arguments                 | Effect                        |
|-------------------|---------------------------|-------------------------------|
| `hal_init`        | —                         | acquire stdout/stdin handles  |
| `hal_write_char`  | `cl` = byte               | write one character           |
| `hal_write_string`| `rcx` = ptr, `rdx` = len  | write N bytes                 |
| `hal_read_char`   | —                         | `rax` = byte (blocks)         |
| `hal_alloc`       | `rcx` = bytes             | `rax` = zeroed heap pointer   |
| `hal_exit`        | `rcx` = code              | terminate (never returns)     |

### Windows implementation (`platform/windows.asm`)

Uses `kernel32` directly via `WriteFile`, `ReadFile`, `GetProcessHeap`,
`HeapAlloc`, `ExitProcess`.  Static handles stored in `.data`:
`_hal_stdout`, `_hal_stdin`, `_hal_heap`.  A 1-byte buffer `_hal_iobuf` /
`_hal_iocount` is used for `hal_read_char`.

---

## Calling convention

All internal procedures follow the Windows x64 ABI:

- **Arguments**: `rcx`, `rdx`, `r8`, `r9`
- **Return value**: `rax`
- **Callee-saved** (every proc that uses them must push/pop): `rbx`, `r12`–`r15`
- **Caller-saved** (may be clobbered freely): `rax`, `rcx`, `rdx`, `r8`–`r11`
- **Shadow space**: 32 bytes below RSP must be reserved before every `call`

### Stack alignment rule

Windows x64 requires RSP to be **16-byte aligned at the point of every
`call` instruction**.  Since `call` itself pushes 8 bytes, RSP is 8-byte
misaligned on entry to every procedure.

Formula — given **N** register pushes and **sub rsp, M**:

```
(N×8 + M) mod 16 = 8   →   RSP mod 16 = 0 before inner calls
```

Standard frames used throughout:

| Pushes | sub rsp | Total delta | Notes                        |
|--------|---------|-------------|------------------------------|
| 1      | 32      | 40          | simple helper                |
| 3      | 32      | 56          | standard multi-call frame    |
| 3      | 48      | 72          | + 16 bytes of local vars     |
| 3      | 64      | 88          | + 32 bytes of local vars     |

Local variables occupy `[rsp+32]` and above (below that is shadow space for
the next callee).

---

## Type system (`defs.inc`)

### Cell — the universal value type (16 bytes)

```
struct Cell {
    tag : qword   ; TAG_* constant
    val : qword   ; integer, or pointer to SymData / Cons / Closure / Vec
}
```

Every value in the interpreter is a `Cell*`.  The heap is an untyped slab
managed by `HeapAlloc`; there is no garbage collector (yet).

### Tags

| Tag           | Value | `Cell.val` interpretation              |
|---------------|-------|----------------------------------------|
| `TAG_NIL`     | 0     | unused (singleton `_cell_nil`)         |
| `TAG_BOOL`    | 1     | 0 = false, 1 = true                   |
| `TAG_INT`     | 2     | signed 64-bit integer                  |
| `TAG_SYM`     | 3     | `SymData*`                             |
| `TAG_CONS`    | 4     | `Cons*`                                |
| `TAG_PRIM`    | 5     | function pointer (64-bit VA)           |
| `TAG_CLOSURE` | 6     | `Closure*`                             |
| `TAG_KEYWORD` | 7     | `SymData*` (`:foo` — self-evaluating)  |
| `TAG_STRING`  | 8     | `SymData*` (inner text, no quotes)     |
| `TAG_VEC`     | 9     | `Vec*` (flat Cell* array)              |

### Supporting structs

```
struct Cons    { car : qword; cdr : qword }               // 16 bytes
struct SymData { len : qword; chars : byte[len+1] }       // 8 + len + 1 bytes
struct Closure { params : qword; body : qword; env : qword } // 24 bytes
struct Vec     { count : qword; cells : Cell*[N] }        // 8 + N*8 bytes
```

`VEC_HDR = 8` — byte offset of the element array within a `Vec`.

### Static singletons (`memory.asm`)

`_cell_nil`, `_cell_true`, `_cell_false` live in `.data` and are returned
by address; they are never heap-allocated.

---

## Tokenizer (`tokenizer.asm`)

### Public

```
tok_next(rcx = Token*) → rax = TOK_* constant
```

Fills the caller-supplied `Token` struct in place.

### Token types

| Constant       | Value | Trigger                          |
|----------------|-------|----------------------------------|
| `TOK_EOF`      | 0     | Ctrl-Z or end of input           |
| `TOK_LPAREN`   | 1     | `(`                              |
| `TOK_RPAREN`   | 2     | `)`                              |
| `TOK_ATOM`     | 3     | symbol or number                 |
| `TOK_STRING`   | 4     | `"..."` — content without quotes |
| `TOK_LBRACKET` | 5     | `[`                              |
| `TOK_RBRACKET` | 6     | `]`                              |

### Internals

- `_tok_getc` → reads one byte via `hal_read_char`; honours a 1-char
  pushback slot (`_tok_pb_char` / `_tok_pb_valid` in `.data`).
- `_tok_ungetc(cl)` → stores the byte in the pushback slot.
- Whitespace (≤ 0x20) is skipped.
- `(`, `)`, `[`, `]` → single-character tokens.
- `"` → string mode: accumulate until closing `"`, yield `TOK_STRING` with
  inner content (quotes stripped).
- Everything else accumulates into an atom until a delimiter (`(`, `)`,
  `[`, `]`, whitespace) is encountered; the delimiter is pushed back.

Atoms are **not** copied; `Token.start` points into an internal static
256-byte buffer `_tok_atom_buf` in `.data`.

---

## Memory / Cell factories (`memory.asm`)

| Function       | Arguments                | Returns           |
|----------------|--------------------------|-------------------|
| `_cell_alloc`  | —                        | zeroed Cell*      |
| `_cons_alloc`  | —                        | zeroed Cons*      |
| `make_int`     | `rcx` = i64              | TAG_INT Cell*     |
| `make_sym`     | `rcx` = ptr, `rdx` = len | TAG_SYM Cell*     |
| `make_keyword` | `rcx` = ptr, `rdx` = len | TAG_KEYWORD Cell* |
| `make_string`  | `rcx` = ptr, `rdx` = len | TAG_STRING Cell*  |
| `make_cons`    | `rcx` = car, `rdx` = cdr | TAG_CONS Cell*    |
| `make_atom`    | `rcx` = ptr, `rdx` = len | TAG_INT or TAG_SYM Cell* |
| `make_vec`     | `rcx` = cons-list Cell*  | TAG_VEC Cell*     |

`make_atom` tries to parse the text as a decimal integer (handles leading
`-`); falls back to `make_sym` if not numeric.

`make_vec` does two passes over the cons list: count elements, then allocate
`Vec` and fill the inline `cells` array.

Symbols, keywords, and strings are **not interned**.  Equality is compared
by string content (`sym_eq`).

---

## Parser (`parser.asm`)

### Public

```
parse_next() → rax = Cell*  (or 0 on EOF)
```

Recursive descent over tokens.  A static `_parse_tok` buffer holds the
current lookahead token.

### Internals

- `_parse_token` — converts one `Token` to a `Cell*`:
  - `TOK_ATOM` → checks first byte for `:` (keyword → `make_keyword`)
    or delegates to `make_atom` (int or symbol).
  - `TOK_STRING` → `make_string`.
  - `TOK_LPAREN` → `_parse_list` (reads until `)`).
  - `TOK_LBRACKET` → `_parse_vector` (reads until `]`, returns TAG_VEC).
- `_parse_list` — reads tokens until `)` or EOF, building a CONS list.
- `_parse_bracket_list` — same but stops at `]`; used internally by
  `_parse_vector`.
- `_parse_vector` — calls `_parse_bracket_list` then `make_vec`.

---

## Printer (`printer.asm`)

### Public

```
print_cell(rcx = Cell*)
```

Tag dispatch:

| Tag           | Output example         |
|---------------|------------------------|
| `TAG_NIL`     | `nil`                  |
| `TAG_BOOL`    | `true` / `false`       |
| `TAG_INT`     | `-42`                  |
| `TAG_SYM`     | `foo`                  |
| `TAG_CONS`    | `(1 2 3)` or `(a . b)` |
| `TAG_PRIM`    | `#<primitive>`         |
| `TAG_CLOSURE` | `#<lambda>`            |
| `TAG_KEYWORD` | `:foo`                 |
| `TAG_STRING`  | `hello` (no quotes)    |
| `TAG_VEC`     | `[1 2 3]`              |

Lists are printed by `_print_list` which walks the CONS chain and emits a
dotted pair ` . ` if the tail is not `TAG_NIL`.

Vectors are printed by `_print_vec(rcx=Vec*)` which iterates the inline
cell array, space-separating elements, wrapped in `[` `]`.

Integers are converted in a 24-byte stack buffer (right-to-left digit fill).

---

## Environment (`env.asm`)

The environment is a **Lisp association list**: a CONS list of `(sym . val)`
pairs, searched linearly.

```
env = ((sym1 . val1) (sym2 . val2) ...)
```

### Global env

```asm
_global_env  dq 0    ; Cell* — alist head, init to _cell_nil at startup
```

Seeded in `main.asm` before `primitives_init`:

```asm
lea  rax, [_cell_nil]
mov  [_global_env], rax
call primitives_init
```

### Procedures

```
sym_eq(rcx=sym1, rdx=sym2)              → rax=1/0
_sym_is(rcx=sym, rdx=cstr)              → rax=1/0
env_lookup(rcx=sym, rdx=env)            → rax=Cell* or 0
env_define(rcx=sym, rdx=val, r8=Cell**) → updates *r8
env_extend(rcx=params, rdx=args, r8=parent) → rax=new env Cell*
```

### Scoping / fallback

`env_lookup` performs **two passes**:

1. Walk the `env` chain passed in.
2. If not found, walk the **current** `_global_env`.

This gives lexical scoping for local variables while ensuring that
definitions added to the global env after a closure was created (e.g.
self-recursive `defn`) are still visible inside that closure.

`env_extend` handles both **TAG_VEC params** (from `fn`/`defn` with `[...]`)
and **cons-list params** (from `lambda` with `(...)`), walking each by index
or car/cdr respectively.

---

## Evaluator (`eval.asm`)

### Public

```
eval_cell(rcx=expr, rdx=env) → rax=Cell*
```

### Dispatch in `eval_cell`

| Expression type                          | Action                              |
|------------------------------------------|-------------------------------------|
| NIL/BOOL/INT/PRIM/CLOSURE/KEYWORD/STRING | self-evaluating, return as-is       |
| SYM                                      | `env_lookup`; error + nil if unbound|
| CONS                                     | `_eval_list`                        |
| VEC                                      | `_eval_vec` (evaluate each element) |

### Special forms (`_eval_list`)

Detected by comparing the list `car` symbol against static strings via
`_sym_is`.

| Form                           | Semantics                                      |
|--------------------------------|------------------------------------------------|
| `(quote x)`                    | return `x` unevaluated                         |
| `(if test then [else])`        | eval test; falsy → else or nil                 |
| `(define sym val)` / `(def …)` | eval val, bind in `_global_env`; return val    |
| `(lambda (p…) body…)`          | allocate `Closure{params, body-list, env}`     |
| `(fn [p…] body…)`              | alias for `lambda`                             |
| `(begin e…)` / `(do e…)`       | eval all; return last                          |
| `(defn name [p…] body…)`       | shorthand for `(def name (fn [p…] body…))`    |
| `(let [x v …] body…)`          | sequential bindings, eval body in extended env |
| `(when test body…)`            | eval body if truthy, else nil                  |
| `(unless test body…)`          | eval body if falsy, else nil                   |

Falsy values: `TAG_NIL` and `TAG_BOOL` with `val=0`.  Everything else
is truthy.

`Closure.body` stores the **list** of body forms, not a single expression.
`_apply` evaluates them in sequence (like `begin`), enabling multi-body
`fn`/`defn`/`lambda`.

### Error reporting

Two error sites in `eval.asm`, both print to stdout and return nil:

- **Unbound symbol** — `eval_cell .sym` when `env_lookup` returns 0:
  prints `\nERROR: unbound symbol 'foo'\n`
- **Not callable** — `_apply` when tag is neither PRIM nor CLOSURE:
  prints `\nERROR: not a function\n`

### Normal call path

```
eval operator → fn Cell*
_eval_args over arg list → evaluated args Cell*
_apply(fn, args, env)
```

`_eval_args` is recursive (head eval + tail recurse).

`_apply` dispatches on tag:

- `TAG_PRIM` → `call [fn.val]` with `rcx=args`
- `TAG_CLOSURE` → `env_extend(params, args, closure.env)`,
  then iterate `closure.body` list like `begin`

### Vector evaluation (`_eval_vec`)

Called from `eval_cell` for TAG_VEC expressions.  Allocates a new `Vec`
of the same size, evaluates each element with `eval_cell`, and stores the
result.  Re-evaluating an already-evaluated vector is safe because value
types self-evaluate.

---

## Primitives (`primitives.asm`)

### Primitive calling convention

```
prim_foo(rcx = args Cell*,  rdx = env Cell*) → rax = Cell*
```

`args` is the already-evaluated argument list.

### Registration

The `defprim` macro allocates a `TAG_SYM` Cell and a `TAG_PRIM` Cell at
runtime and calls `env_define`.  `primitives_init` (called once from
`main.asm`) registers all built-ins.

### Built-in table

| Name      | Arity    | Behaviour                                                |
|-----------|----------|----------------------------------------------------------|
| `+`       | variadic | sum of integers (0 if no args)                           |
| `-`       | variadic | unary negate or left-fold subtract                       |
| `*`       | variadic | product of integers (1 if no args)                       |
| `=`       | 2        | same tag and same val field                              |
| `<`       | 2        | integer less-than                                        |
| `>`       | 2        | integer greater-than                                     |
| `car`     | 1        | head of a CONS                                           |
| `cdr`     | 1        | tail of a CONS                                           |
| `cons`    | 2        | allocate a new CONS pair                                 |
| `list`    | variadic | return evaluated arg list as-is                          |
| `nil?`    | 1        | bool: arg is TAG_NIL                                     |
| `number?` | 1        | bool: arg is TAG_INT                                     |
| `pair?`   | 1        | bool: arg is TAG_CONS                                    |
| `symbol?` | 1        | bool: arg is TAG_SYM                                     |
| `not`     | 1        | bool: arg is falsy                                       |
| `display` | 1        | `print_cell` with no trailing newline                    |
| `newline` | 0        | emit ASCII 10                                            |
| `exit`    | 0        | `hal_exit(0)` — never returns                            |
| `quit`    | 0        | alias for `exit`                                         |
| `count`   | 1        | TAG_VEC → Vec.count; CONS → walk length; NIL → 0        |
| `nth`     | 2        | element at index; nil if out of bounds                   |
| `get`     | 2        | alias for `nth` (future: map lookup)                     |
| `conj`    | 2        | new vector with element appended; nil vec → `[elem]`    |
| `vector`  | variadic | construct vector from evaluated args                     |
| `vec`     | variadic | alias for `vector`                                       |

---

## REPL (`main.asm`)

```
hal_init
_global_env ← _cell_nil
primitives_init
print banner
loop:
    print "> "
    parse_next → Cell* (0 on EOF → exit)
    eval_cell(expr, _global_env) → result
    print_cell(result)
    print newline
```

RSP is adjusted by `sub rsp, 8` on entry to `lisp_start` (the Windows
loader issues a `call`, leaving RSP misaligned by 8 at the entry point).

---

## Known limitations / future work

### Next — Clojure constructs

- `loop` / `recur` — Clojure's explicit tail-call construct; enables
  writing `map`, `filter`, `reduce` in Clojure itself without stack risk
- Hash maps `{:a 1 :b 2}` — needs `{`/`}` tokenizing, `TAG_MAP`,
  `assoc`, `dissoc`, `get`, `keys`, `vals`
- Variadic functions — rest parameter `(fn [x & rest] ...)`
- `apply` — `(apply + [1 2 3])`
- `map`, `filter`, `reduce` as primitives or derivable via `loop`/`recur`
- String primitives — `str`, `subs`, `count` for strings

### Infrastructure

- **Tail-call optimisation (TCO)** — `recur` is the priority path
- **Garbage collector** — mark-and-sweep over the heap Cell pool
- **Bootable target** — replace `platform/windows.asm` with a BIOS or
  UEFI HAL; all other code is platform-agnostic

### Design notes

- Symbols, keywords, and strings are **not interned**.  `=` compares by
  tag and pointer value; `sym_eq` compares by string content.
- `def`/`define`/`defn` always write to `_global_env` regardless of
  the current lexical scope.
- The `env_lookup` two-pass fallback (local chain → `_global_env`) enables
  self-recursion from closures while preserving lexical scoping for
  parameters and `let` bindings.
- `Closure.params` may be TAG_VEC (from `fn`/`defn`) or a cons list (from
  `lambda`).  `env_extend` handles both.
- `[...]` always produces TAG_VEC — `let` binding vectors and `fn`/`defn`
  parameter lists are therefore vectors, which matches Clojure semantics.
- Vector literals evaluate their elements when the vector form is evaluated.
  Re-evaluation of an already-value vector is idempotent.
