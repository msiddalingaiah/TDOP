# Flux

A compiler backend written in Python that parses arithmetic S-expressions,
compiles them through a classic pipeline, and executes the result as native
x86-64 machine code — all in memory, with no external tools required.

```
(if (< x 0) (* x -1) x)  →  SSA → regalloc → x86-64 bytes → 42
```

**41× faster than CPython** on a tight loop over 100 million iterations.

---

## What it is

Flux is an educational compiler backend that implements each stage of the
compilation pipeline from scratch:

```
S-expression
    │
    ▼
  Parser            flux/core/parser.py
    │
    ▼
  Tree IR           flux/core/tree.py        (Expr, Const, Arg, Add, Sub, Mul,
    │                                         Lt, Gt, Eq, If)
    ▼
  BURG selector     flux/core/burg.py        bottom-up rewrite, optimal tiling
    │
    ▼
  Linear IR         flux/core/ir.py          (VReg, Opcode, Instr, BasicBlock,
    │                                         Function)
    ▼
  SSA construction  flux/core/ssa.py         CFG splitting, dominators,
    │               flux/core/cfg.py         phi insertion, renaming
    ▼
  [optimisations]                            (DCE, const prop, GVN — coming)
    │
    ▼
  SSA destruction   flux/core/ssa.py         phi → parallel copies → flat IR
    │
    ▼
  Linear scan       flux/core/linear_scan.py Poletto & Sarkar (1999)
    │                                        with stack spilling
    ▼
  x86-64 emitter    flux/targets/x86_64/     encodes instructions as raw bytes
    │
    ▼
  execute           flux/core/jit.py         VirtualAlloc / mmap + ctypes
```

The architecture is target-neutral above the emitter layer. A `Target`
descriptor carries the register file, calling convention, and scratch
registers. The `Allocator` base class handles instruction lowering so
adding a new target only requires a new `Emitter` subclass.

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

## Examples

### Fibonacci (iterative)

```lisp
(var a 0
  (var b 1
    (var i 0
      (while (< i n)
        (var tmp (+ a b)
          (set! a b)
          (set! b tmp))
        (set! i (+ i 1)))
      a)))
```

```python
from flux.core.compiler import compile_and_run

compile_and_run("""
    (var a 0 (var b 1 (var i 0
      (while (< i n)
        (var tmp (+ a b) (set! a b) (set! b tmp))
        (set! i (+ i 1)))
      a)))
""", n=10)
# → 55  (fib(10))
```

### Absolute value

```python
compile_and_run("(if (< x 0) (* x -1) x)", x=-42)
# → 42
```

### Sum with let

```python
compile_and_run("(let ((a (* x x)) (b (* y y))) (+ a b))", x=3, y=4)
# → 25
```

### Clamp

```python
compile_and_run("(if (< x 0) 0 (if (> x 100) 100 x))", x=150)
# → 100
```

---

## Performance

Flux compiles to native x86-64 and executes without any interpreter overhead.
Summing the integers from 0 to 99,999,999:

```python
import time
from flux.core.compiler import compile_and_run

expr = """
    (var i 0
      (var sum 0
        (while (< i n)
          (set! sum (+ sum i))
          (set! i (+ i 1)))
        sum))
"""

# Flux: native x86-64
t0 = time.perf_counter()
result = compile_and_run(expr, n=100_000_000)
flux_time = time.perf_counter() - t0

# Python: interpreter
def python_sum(n):
    i = s = 0
    while i < n:
        s += i; i += 1
    return s

t0 = time.perf_counter()
python_sum(100_000_000)
py_time = time.perf_counter() - t0

print(f"Flux:   {flux_time*1000:.0f} ms")
print(f"Python: {py_time*1000:.0f} ms")
print(f"Speedup: {py_time/flux_time:.1f}×")
```

Typical output:
```
Flux:    161 ms
Python: 6593 ms
Speedup: 41.1×
```

Run the benchmark as a test:
```bash
python -m pytest tests/test_loops.py::TestBenchmark -v -s
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
flux> (if (< x y) x y)
6
flux> (def abs (if (< _ 0) (* _ -1) _))
abs = 6
flux> :ir
function f(%0):
  block entry:
    cmp %0, #0
    jge L2
    %1 = mul %0, #-1
    %2 = move %1
    jmp L3
    label L2
    %2 = move %0
    label L3
    ret %2
flux> :vars
  x = 6
  y = 7
  abs = 6
  _ = 6
flux> quit
Bye.
```

### Operators and forms

| Syntax | Operation |
|---|---|
| `(+ a b)` | addition |
| `(- a b)` | subtraction |
| `(* a b)` | multiplication |
| `(< a b)` | less-than comparison |
| `(> a b)` | greater-than comparison |
| `(= a b)` | equality comparison |
| `(if cond then else)` | conditional expression |
| `(let ((x e)) body ...)` | immutable binding |
| `(var x init body ...)` | mutable variable |
| `(set! x expr)` | assign to mutable variable, returns new value |
| `(begin e1 e2)` | sequence two expressions, return second |
| `(while cond body ...)` | loop while condition holds |

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
result = compile_and_run("(if (< x 0) (* x -1) x)", x=-42)
# → 42

# Compile only — returns (Function, bytes)
fn, code = compile_expr("(* x 7)", x=6)
print(repr(fn))
# function f(%0):
#   block entry:
#     %1 = mul %0, #7
#     ret %1

# SSA round-trip (construction + destruction)
from flux.core.ssa import to_ssa, from_ssa
ssa = to_ssa(fn)
print(repr(ssa))   # SSAFunction with phi nodes
out = from_ssa(ssa)  # back to flat IR, ready for allocation
```

---

## Project structure

```
flux/
├── flux/
│   ├── __main__.py              entry point  (python -m flux)
│   ├── core/
│   │   ├── tree.py              tree IR  (Expr, Const, Arg, Add, Sub, Mul,
│   │   │                                  Lt, Gt, Eq, If)
│   │   ├── ir.py                linear IR  (VReg, LabelRef, Opcode, Instr,
│   │   │                                   BasicBlock, Function)
│   │   ├── builder.py           FunctionBuilder — fluent IR construction
│   │   ├── burg.py              BURG instruction selector (rules 1–10)
│   │   ├── cfg.py               CFG construction, RPO, dominators, frontiers
│   │   ├── ssa.py               SSA construction (to_ssa) and destruction (from_ssa)
│   │   ├── allocator.py         Allocator base class + shared instruction lowering
│   │   ├── trivial_allocator.py TrivialAllocator — first-seen order, no spilling
│   │   ├── linear_scan.py       LinearScanAllocator — live intervals + stack spilling
│   │   ├── emitter.py           abstract Emitter base class + label fixup helpers
│   │   ├── target.py            Target descriptor (registers, ABI, scratch regs)
│   │   ├── operands.py          Operand, Reg, Imm, Mem, SpillSlot
│   │   ├── parser.py            S-expression → Expr tree
│   │   ├── compiler.py          compile_expr / compile_and_run
│   │   ├── repl.py              FluxRepl
│   │   └── jit.py               make_callable / free_code (VirtualAlloc / mmap)
│   └── targets/
│       └── x86_64/
│           ├── regs.py          X86_64Reg + all GP registers
│           ├── targets.py       WINDOWS and LINUX Target instances
│           └── emitter.py       X86_64Emitter — full instruction encoding
└── tests/
    ├── jit.py                   platform-agnostic JIT helper (re-exports core.jit)
    ├── test_emitter.py          encoding + execution tests
    ├── test_ir.py               IR data structure tests
    ├── test_trivial_allocator.py
    ├── test_linear_scan.py      interval computation + register reuse
    ├── test_burg.py             labeling costs + rule selection
    ├── test_integration.py      full pipeline: Expr → execute
    ├── test_parser.py           parser + compile_and_run
    ├── test_conditionals.py     comparisons and if-then-else
    ├── test_spill.py            register pressure + stack spilling
    └── test_ssa.py              CFG, dominators, phi insertion, round-trip
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
Comparisons and `if` expressions are handled as rule 10, emitting a
`cmp`, an inverted conditional branch, and a pre-allocated merge VReg.

### SSA construction and destruction

`to_ssa()` transforms the flat IR into SSA form in five steps:

1. **CFG construction** — LABEL and branch instructions are used as block
   boundaries; proper predecessor/successor edges are built.
2. **Dominator computation** — Cooper, Harvey & Kennedy (2001) iterative
   algorithm over the reverse post-order.
3. **Dominance frontiers** — standard frontier algorithm; identifies join
   points where phi nodes are needed.
4. **Phi insertion** — one phi per multiply-defined variable per frontier
   block, using an iterated work-list.
5. **Variable renaming** — DFS over the dominator tree; each definition
   gets a fresh VReg; renaming stacks are maintained and restored.

A post-renaming pruning pass removes phi nodes whose result is never
used (conservative phi insertion places phis at all frontiers regardless
of liveness; pruning makes this safe).

`from_ssa()` (SSA destruction) replaces each phi with parallel copy
instructions inserted into predecessor blocks, sequentialises them to
avoid the lost-copy problem, then flattens the blocks back into the
single-block format the allocator expects.

### Register allocation with spilling

The linear scan allocator follows Poletto & Sarkar (1999). When the
register pool is exhausted, the interval with the furthest end point is
spilled to a `[RBP-relative]` stack slot. Two scratch registers (R14
and R15 on both ABIs) are reserved for spill reload/store and excluded
from the allocatable pool. Spilled parameters are stored to their slots
immediately after the prologue. The stack frame is 16-byte aligned.

### x86-64 encoding

The emitter handles REX prefixes, ModRM bytes, and extended registers
(R8–R15). Supported instructions: `mov`, `add`, `sub`, `imul` (2- and
3-operand), `push`, `pop`, `cmp`, `jge`, `jle`, `jne`, `jmp`, `ret`,
and RBP-relative `load_spill` / `store_spill`. Branch targets use a
fixup system: a 4-byte placeholder is emitted, patched with the correct
relative offset when the target label is placed.

### Calling conventions

Two targets are defined: `WINDOWS` (Microsoft x64 ABI — RCX, RDX, R8,
R9 for the first four integer arguments) and `LINUX` (System V AMD64
ABI — RDI, RSI, RDX, RCX, R8, R9). The active target is selected
automatically from `sys.platform` at runtime.

---

## Current status

| Component | Status |
|---|---|
| x86-64 emitter | ✅ mov, add, sub, imul, push, pop, cmp, jge, jle, jne, jmp, ret, spill/var load/store |
| Tree IR | ✅ Const, Arg, Add, Sub, Mul, Lt, Gt, Eq, If, Let, Var, MutVar, SetBang, Begin, While |
| BURG selector | ✅ optimal tiling, imm/reg non-terminals, all control flow (rules 1–16) |
| Linear IR | ✅ flat instruction list with labels, branches, VRegs, LOAD_VAR, STORE_VAR |
| SSA construction | ✅ CFG splitting, RPO, dominators (Cooper 2001), phi insertion, renaming |
| SSA destruction | ✅ phi → parallel copies, sequentialisation, flat IR reconstruction |
| Trivial allocator | ✅ first-seen order, no spilling |
| Linear scan allocator | ✅ live intervals, register reuse, stack spilling |
| Stack frame | ✅ prologue/epilogue, mutable var slots, spill slots, 16-byte alignment |
| S-expression parser | ✅ +, -, *, <, >, =, if, let, var, set!, begin, integer literals, named args |
| REPL | ✅ def, :ir, :vars, :clear |
| Windows support | ✅ VirtualAlloc, Microsoft x64 ABI |
| Linux support | ✅ mmap, System V AMD64 ABI |
| SSA optimisations | ❌ DCE, constant propagation, GVN — not yet |
| Function definitions | ❌ not yet |
| ARM64 target | ❌ not yet |

---

## Running the tests

```bash
pip install pytest
python -m pytest tests/ -v
```

267 tests across 14 test modules, covering encoding, execution, live
interval computation, register reuse, spilling, mutable variable stack
slots, loop back-edge liveness, BURG rule selection, let and var binding
semantics, SSA construction and destruction, and end-to-end pipeline
correctness. Includes a performance benchmark comparing Flux native code
against CPython.

---

## Documentation

- [BURG instruction selection](docs/burg.md) — rule table, cost model, interpretive vs table-driven, adding new operations
- [SSA construction and destruction](docs/ssa.md) — CFG splitting, dominators, phi insertion, renaming, destruction
- [Register allocation and spilling](docs/allocator.md) — live intervals, linear scan, spill slots, stack frame, calling conventions

---

## License

MIT
