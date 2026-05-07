# BURG Instruction Selection

Flux uses a BURG (Bottom-Up Rewrite Generator) instruction selector to
tile the tree IR into linear IR instructions.  The implementation is
interpretive (IBURG style) — the dynamic programming runs directly on
each tree at compile time rather than being pre-compiled into a
table-driven automaton.

---

## Overview

Instruction selection is the problem of mapping an expression tree to a
sequence of target instructions.  A tree node like `Add(Arg(0), Const(1))`
could be compiled in more than one way:

```
; Option A — load constant into a register, then add
mov  rcx, 1
add  rax, rcx        ; 2 instructions

; Option B — use an immediate operand directly
add  rax, 1          ; 1 instruction
```

BURG chooses Option B automatically by assigning costs to each possible
mapping and finding the minimum-cost tiling of the whole tree.

---

## Non-terminals

Non-terminals represent what a subtree's value can be used as.  Flux
currently has two:

| Non-terminal | Meaning |
|---|---|
| `REG` | the value resides in a virtual register |
| `IMM` | the value can be used directly as an immediate operand |

Not every node can derive both non-terminals.  `Arg`, for example, can
only derive `REG` (an argument is in a register, not an immediate).

---

## Rule table

Each rule maps a tree pattern to a non-terminal, with a base cost.
The total cost of applying a rule is the base cost plus the costs of
deriving the required non-terminals from the children.

| ID | Pattern | NT | Cost | Action |
|---|---|---|---|---|
| 1 | `Const` | `imm` | **0** | return `Imm(value)` — no instruction emitted |
| 2 | `Const` | `reg` | 1 | emit `load_imm value` → result VReg |
| 3 | `Arg` | `reg` | **0** | return the parameter VReg — already in a register |
| 4 | `Add(reg, reg)` | `reg` | 1 | emit `add lhs, rhs` |
| 5 | `Add(reg, imm)` | `reg` | 1 | emit `add lhs, imm` |
| 6 | `Sub(reg, reg)` | `reg` | 1 | emit `sub lhs, rhs` |
| 7 | `Sub(reg, imm)` | `reg` | 1 | emit `sub lhs, imm` |
| 8 | `Mul(reg, reg)` | `reg` | 1 | emit `imul dst, lhs, rhs` |
| 9 | `Mul(reg, imm)` | `reg` | 1 | emit `imul dst, lhs, imm` (3-operand form) |
| 10 | `If(cond, reg, reg)` | `reg` | 1 | emit cmp + conditional branch + merge |

Rules 1 and 3 have cost 0 because they produce their result for free —
no instruction is emitted.  Every other rule costs 1.

---

## The two phases

### Phase 1 — labeling (bottom-up)

Starting at the leaves and working up toward the root, each node is
assigned a `State` — a mapping from each non-terminal to the cheapest
rule that can derive it at that node, plus the accumulated cost.

For `Const(1)`:
```
IMM → cost 0, rule 1   (use as immediate — free)
REG → cost 1, rule 2   (load into register)
```

For `Arg(0)`:
```
REG → cost 0, rule 3   (already in a register)
IMM → unreachable
```

For `Add(Arg(0), Const(1))`, the labeler tries both Add rules:
```
rule 4  Add(reg, reg): cost = 1 + Arg[REG](0) + Const[REG](1) = 2
rule 5  Add(reg, imm): cost = 1 + Arg[REG](0) + Const[IMM](0) = 1
```
Rule 5 wins.  The node's state records `REG → cost 1, rule 5`.

The labeling result for every node is cached, so shared subtrees are
only labelled once.

### Phase 2 — reduction (top-down)

Starting at the root with a requested non-terminal (always `REG`), the
reducer looks up the winning rule in the node's cached state, executes
its action to emit IR instructions, and recursively reduces the children
with the non-terminals that rule requires.

For `Add(Arg(0), Const(1))` using rule 5:
1. Reduce `Arg(0)` as `REG` → returns `%0` (param VReg, no instruction emitted)
2. Reduce `Const(1)` as `IMM` → returns `Imm(1)` (no instruction emitted)
3. Emit `builder.add(%0, Imm(1))` → returns `%1`

The net result: a single `add` instruction with an immediate operand,
which is exactly what Option B above achieves.

---

## Why this is optimal

The dynamic programming accumulates costs bottom-up across the entire
tree.  A rule's recorded cost includes the cost of the cheapest way to
derive each of its children's non-terminals.  This means the winning
rule at every node accounts for what's available from its subtree —
local decisions are globally consistent.

A naive recursive tiler that just picks "what looks cheapest here"
without looking at children could, for example, choose `Add(reg, reg)`
for `Add(Arg(0), Const(1))` if it didn't know the right child could
be an immediate.  BURG's bottom-up pass ensures that information is
always available when a rule is chosen.

---

## The `If` special case (rule 10)

`If` doesn't map cleanly to a single instruction.  Rule 10 is a macro
rule: its reduction directly drives `FunctionBuilder` to emit:

1. The comparison (`cmp lhs, rhs`) — using `REG` or `IMM` for the rhs,
   whichever is cheaper
2. An inverted conditional branch to the else label
3. The then branch, writing its result to a pre-allocated result VReg
4. An unconditional jump to the merge label
5. The else branch label and code, also writing to the result VReg
6. The merge label

The pre-allocated result VReg is written in both branches, so after SSA
construction it becomes the subject of a phi node at the merge block.

---

## Instruction costs in Flux

Flux uses a deliberately simple cost model: every rule that emits an
instruction costs 1; every rule that produces a result for free costs 0.
The only meaningful distinction the costs encode is:

- A constant used as an **immediate** is free (rule 1, cost 0)
- A constant loaded into a **register** costs one instruction (rule 2, cost 1)

This single distinction drives the key practical optimisation: constant
operands on the right-hand side of arithmetic are folded into the
instruction's immediate field rather than loaded separately.

### What real cost models look like

In a production compiler, costs would reflect actual hardware
characteristics:

**Instruction latency** — on modern x86, `imul` has a higher latency
than `add`.  Giving multiply a cost of 3 and add a cost of 1 would let
BURG prefer a shift-and-add sequence (`x * 4` → `x << 2`) when one
exists.

**Code size** — a 3-operand `imul r, r, imm8` is 4 bytes; a general
`imul r, r/m64` is 3 bytes.  A size-optimising compiler might assign
different costs to reflect this.

**Immediate constraints** — x86 sign-extends 32-bit immediates to 64
bits.  A constant that doesn't fit in 32 bits can't be used as an
immediate at all.  The rule could conditionally set its cost to infinity
when the value is out of range, forcing the constant to be loaded into
a register instead.

**Target variation** — a rule cheap on x86 may be expensive on ARM.
Separate cost tables per target allow the same grammar to drive
architecture-specific choices.

### Strength reduction via costs

One classic application is **strength reduction**: replacing expensive
operations with cheaper equivalents.

```
(* x 2)  →  (+ x x)   ; replace multiply-by-2 with add
(* x 4)  →  (x << 2)  ; replace multiply-by-power-of-2 with shift
```

If `imul` had cost 3 and `add` had cost 1, BURG would automatically
prefer `Add(Arg(0), Arg(0))` over `Mul(Arg(0), Const(2))` when
compiling `(* x 2)`, because the add tiling would have a lower total
cost.  Flux doesn't currently implement shifts or cost differentiation,
but the mechanism is already in place — it's just a matter of adding
the rules and adjusting the costs.

---

## Interpretive vs table-driven BURG

Flux's implementation is **interpretive** (IBURG): the dynamic
programming runs at compiler-compile time in Python, driven by `match`
statements and explicit cost comparisons.

A **table-driven** BURG tool would pre-compute a finite automaton from
the grammar spec.  At compile time, each node is labelled by a simple
array lookup — `table[node_kind][left_state][right_state]` — with no
branching or arithmetic.

The tiling decisions are **identical** between the two approaches.
Optimality is a property of the algorithm, not the implementation
strategy.  The difference is purely in how fast the compiler itself runs:

- Interpretive BURG: flexible, easy to modify, slower at scale
- Table-driven BURG: faster label phase, harder to modify, requires a
  separate tool to regenerate the tables when the grammar changes

For Flux's use case — compiling S-expressions interactively — the
interpretive approach is completely adequate.  Compilation latency is
dominated by Python startup and ctypes overhead, not by the BURG phase.

---

## Source

The implementation lives in `flux/core/burg.py`.  The rule table is
encoded as match arms in `_label()` (cost computation) and `_reduce()`
(code generation).  Adding a new expression type requires:

1. A new `Expr` subclass in `flux/core/tree.py`
2. New rules in `_label()` with cost computation
3. Corresponding match arms in `_reduce()` with the action
4. A new `Opcode` and `FunctionBuilder` method if a new IR instruction
   is needed
5. New cases in `Allocator._lower()` and `X86_64Emitter`
