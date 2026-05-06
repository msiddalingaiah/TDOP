# Flux

A compiler backend written in Python that parses arithmetic S-expressions,
compiles them through a classic pipeline, and executes the result as native
x86-64 machine code — all in memory, with no external tools required.

```
(+ (* x 3) (- y 1))  →  mov rax, rcx / imul rax, 3 / ...  →  42
```

---

## What it is

Flux is an educational compiler backend that implements each stage of the
compilation pipeline from scratch:

```
S-expression
    │
    ▼
  Parser          flux/core/parser.py
    │
    ▼
  Tree IR         flux/core/tree.py          (Expr, Const, Arg, Add, Sub, Mul)
    │
    ▼
  BURG selector   flux/core/burg.py          bottom-up rewrite, optimal tiling
    │
    ▼
  Linear IR       flux/core/ir.py            (VReg, Opcode, Instr, BasicBlock, Function)
    │
    ▼
  Linear scan     flux/core/linear_scan.py   Poletto & Sarkar (1999)
    │
    ▼
  x86-64 emitter  flux/targets/x86_64/       encodes instructions as raw bytes
    │
    ▼
  execute         flux/core/jit.py           VirtualAlloc / mmap + ctypes
```

The architecture is target-neutral above the emitter layer. A `Target`
descriptor carries the register file and calling convention; the
`Allocator` base class handles instruction lowering so that adding a new
target only requires a new `Emitter` subclass.

---

## Requirements

- Python 3.10 or later (uses `match` / `case`)
- No third-party runtime dependencies

For tests: `pip install pytest`

---

## Quick start

```bash
# Run the REPL
python -m flux

# Run the test suite
python -m pytest tests/ -v
```

---

## The REPL

```
┌─────────────────────────────────────────┐
│  Flux  ·  native code from S-expressions │
└─────────────────────────────────────────┘

flux> (+ 1 2)
3
flux> (def x 6)
x = 6
flux> (def y 7)
y = 7
flux> (* x y)
42
flux> (def result (* _ 2))
result = 84
flux> :ir
function f(%0):
  block entry:
    %1 = mul %0, #2
    ret %1
flux> :vars
  x = 6
  y = 7
  result = 84
  _ = 84
flux> quit
Bye.
```

### Operators

| Syntax | Operation |
|---|---|
| `(+ a b)` | addition |
| `(- a b)` | subtraction |
| `(* a b)` | multiplication |

Operands can be integer literals, bound variable names, or nested expressions.
`_` always holds the result of the last evaluation.

### Commands

| Command | Effect |
|---|---|
| `(def name expr)` | bind a variable to the result of an expression |
| `:ir` | show the linear IR for the last compiled expression |
| `:vars` | list all current bindings |
| `:clear` | clear all bindings |
| `help` | show usage summary |
| `quit` / `exit` | exit |

---

## Programmatic use

```python
from flux.core.compiler import compile_and_run, compile_expr

# Parse, compile, and execute in one call
result = compile_and_run("(+ (* x 3) (- y 1))", x=10, y=13)
# → 42

# Compile only — returns (Function, bytes)
fn, code = compile_expr("(* x 7)", x=6)
print(repr(fn))
# function f(%0):
#   block entry:
#     %1 = mul %0, #7
#     ret %1
```

---

## Project structure

```
flux/
├── flux/
│   ├── __main__.py              entry point  (python -m flux)
│   └── core/
│       ├── tree.py              tree IR  (Expr, Const, Arg, Add, Sub, Mul)
│       ├── ir.py                linear IR  (VReg, Opcode, Instr, BasicBlock, Function)
│       ├── builder.py           FunctionBuilder — fluent IR construction
│       ├── burg.py              BURG instruction selector
│       ├── allocator.py         Allocator base class + shared lowering
│       ├── trivial_allocator.py TrivialAllocator — first-seen order
│       ├── linear_scan.py       LinearScanAllocator + LiveInterval
│       ├── emitter.py           abstract Emitter base class
│       ├── target.py            Target descriptor (registers, calling convention)
│       ├── operands.py          Operand, Reg, Imm, Mem
│       ├── parser.py            S-expression → Expr tree
│       ├── compiler.py          compile_expr / compile_and_run
│       ├── repl.py              FluxRepl
│       └── jit.py               make_callable / free_code (VirtualAlloc / mmap)
│   └── targets/
│       └── x86_64/
│           ├── regs.py          X86_64Reg + all GP registers
│           ├── targets.py       WINDOWS and LINUX Target instances
│           └── emitter.py       X86_64Emitter — instruction encoding
└── tests/
    ├── jit.py                   re-exports flux.core.jit for tests
    ├── test_emitter.py          encoding + execution tests
    ├── test_ir.py               IR data structure tests
    ├── test_trivial_allocator.py
    ├── test_linear_scan.py      interval computation + register reuse
    ├── test_burg.py             labeling costs + rule selection
    ├── test_integration.py      full pipeline: Expr → execute
    └── test_parser.py           parser + compile_and_run
```

---

## Implementation notes

### BURG instruction selection

The selector implements the Aho, Ganapathi & Tjiang bottom-up rewrite
algorithm. Each node in the tree IR is labelled bottom-up with the
minimum cost to derive each non-terminal (`REG` or `IMM`). The optimal
tiling is then read off top-down. This ensures, for example, that a
constant on the right-hand side of `*` always tiles as a 3-operand
`imul` rather than loading the constant into a register first.

### Linear scan register allocation

The allocator follows Poletto & Sarkar (1999). Live intervals are
computed with a single pass over the flat instruction sequence.
Intervals are processed in start-point order; registers are reclaimed
as soon as their holder's interval ends and immediately reused.
Parameters are pinned to the target's argument registers and participate
in expiry so their registers become available to later temporaries.

Spilling is not yet implemented — a `RuntimeError` is raised if the
register pool is exhausted.

### x86-64 encoding

The emitter handles REX prefixes, ModRM bytes, and the distinction
between extended (R8–R15) and non-extended registers. Supported
instructions: `mov`, `add`, `sub`, `imul` (2- and 3-operand), `push`,
`pop`, `ret`. The 3-operand form of `imul` is used when the rhs is an
immediate, avoiding a register load.

### Calling conventions

Two targets are defined: `WINDOWS` (Microsoft x64 ABI — RCX, RDX, R8,
R9 for the first four integer arguments) and `LINUX` (System V AMD64
ABI — RDI, RSI, RDX, RCX, R8, R9). The active target is selected
automatically from `sys.platform` at runtime.

---

## Current status

| Component | Status |
|---|---|
| x86-64 emitter | ✅ mov, add, sub, imul, push, pop, ret |
| Tree IR | ✅ Const, Arg, Add, Sub, Mul |
| BURG selector | ✅ optimal tiling, imm/reg non-terminals |
| Linear IR | ✅ single basic block |
| Trivial allocator | ✅ first-seen order, no spilling |
| Linear scan allocator | ✅ live intervals, register reuse, no spilling |
| S-expression parser | ✅ +, -, *, integer literals, named args |
| REPL | ✅ def, :ir, :vars, :clear |
| Windows support | ✅ VirtualAlloc, Microsoft x64 ABI |
| Linux support | ✅ mmap, System V AMD64 ABI |
| Spilling | ❌ not yet implemented |
| Control flow / conditionals | ❌ not yet implemented |
| SSA construction | ❌ not yet implemented |
| Multiple basic blocks | ❌ not yet implemented |
| ARM64 target | ❌ not yet implemented |

---

## Running the tests

```bash
pip install pytest
python -m pytest tests/ -v
```

115 tests across 7 test modules, covering encoding, execution, interval
computation, register reuse, BURG rule selection, and end-to-end
pipeline correctness.

---

## License

MIT
