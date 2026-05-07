# SSA Construction and Destruction

Flux includes an SSA (Static Single Assignment) pass that transforms the
flat linear IR into SSA form and back.  The pass is implemented as two
pure functions in `flux/core/ssa.py`, with CFG utilities in
`flux/core/cfg.py`.

```python
from flux.core.ssa import to_ssa, from_ssa

ssa = to_ssa(fn)    # Function → SSAFunction
out = from_ssa(ssa) # SSAFunction → Function  (ready for allocation)
```

---

## What SSA is

In SSA form every variable is defined exactly once.  At points where
control flow merges — join points — a special **phi node** (φ-function)
selects which definition reaches this point depending on which
predecessor block was executed.

Before SSA, `(if (< x 0) (* x -1) x)` produces:

```
cmp  %0, #0
jge  L0
%1 = mul %0, #-1
%2 = move %1        ← result written here …
jmp  L1
label L0
%2 = move %0        ← … and here (same VReg, two definitions)
label L1
ret  %2
```

After SSA construction:

```
entry:
  cmp  %0, #0  →  jge L0
then:
  %3 = mul  %0, #-1
  %4 = move %3
  →  jmp L1
L0 (else):
  %5 = move %0
L1 (merge):
  %6 = φ(then → %4, L0 → %5)   ← phi node
  ret  %6
```

`%6` is defined exactly once — by the phi — and its value is
whichever of `%4` or `%5` was computed on the taken path.

---

## Why SSA matters

SSA makes dataflow analysis trivial:

- **Each use has exactly one reaching definition** — no need to track
  which of several assignments reaches a particular use point.
- **Optimisations become local reasoning** — constant propagation,
  dead code elimination, and GVN all reduce to simple checks on the
  single definition of each variable.
- **Register allocation quality improves** — live ranges are shorter
  and more precise because each definition is unique.

---

## Data structures

### `SSAFunction`

```python
@dataclass
class SSAFunction:
    name:        str
    params:      List[VReg]
    entry:       str                    # label of entry block
    blocks:      Dict[str, SSABlock]    # label → block
    block_order: List[str]              # original split order
```

### `SSABlock`

```python
@dataclass
class SSABlock:
    label:  str
    phis:   List[PhiNode]     # phi nodes at block entry
    instrs: List[Instr]       # body instructions
    term:   Optional[Instr]   # terminator (None = fall-through)
    succs:  List[str]
    preds:  List[str]
```

### `PhiNode`

```python
@dataclass
class PhiNode:
    result:   VReg                  # renamed result VReg
    original: VReg                  # pre-SSA variable being tracked
    incoming: Dict[str, VReg]       # pred_label → reaching VReg
```

---

## `to_ssa()` — construction

SSA construction runs in five steps.

### Step 1 — CFG construction (`cfg.py`)

The flat instruction list (a single `BasicBlock` with embedded `LABEL`
and branch pseudo-instructions) is split into proper basic blocks.

**Leaders** (first instructions of blocks) are identified as:
- Instruction 0 (always)
- Any `LABEL` instruction
- The instruction immediately following any branch (`JGE`, `JLE`,
  `JNE`, `JMP`, `RET`)

Each block gets a label:
- Block at position 0 → `"entry"`
- Blocks starting with a `LABEL` instruction → `"L{id}"`
- Blocks reachable only by fall-through → `"__b{n}"`

Successor edges are derived from each block's terminator:
- `JMP L{id}` → one successor: `L{id}`
- `JGE/JLE/JNE L{id}` → two successors: `[fall-through, L{id}]`
- `RET` → no successors
- No terminator (fall-through) → one successor: next block

Predecessor edges are the reverse.

### Step 2 — Dominator computation

Dominators are computed using the **Cooper, Harvey & Kennedy (2001)**
iterative algorithm, which is simpler to implement than
Lengauer-Tarjan while being fast enough in practice.

Block A **dominates** block B if every path from the entry to B passes
through A.  The immediate dominator `idom[B]` is the closest dominator
of B (other than B itself).

The algorithm iterates over blocks in **reverse post-order** (RPO),
computing `idom` for each block from its predecessors' `idom` values,
until no further changes occur.  Convergence is guaranteed and fast
for typical CFG shapes.

### Step 3 — Dominance frontiers

The **dominance frontier** of block A is the set of blocks where A's
dominance ends — blocks that have a predecessor dominated by A but are
not themselves strictly dominated by A.

```
DF(A) = { Y | ∃ P ∈ preds(Y) : A dom P, A does not strictly dom Y }
```

This is computed with the standard algorithm: for each join point Y
(block with two or more predecessors), walk up the idom chain from each
predecessor until reaching `idom[Y]`, adding Y to the frontier of each
block visited along the way.

Dominance frontiers identify exactly where phi nodes are needed.

### Step 4 — Phi insertion

For each variable (VReg) that is defined in two or more blocks, phi
nodes are inserted using an **iterated work-list**:

```
for each variable V with defs in blocks D1, D2, ...:
    work = {D1, D2, ...}
    while work is not empty:
        B = work.pop()
        for each F in DF(B):
            if F has no phi for V:
                insert phi for V at F
                add F to work
```

This places phi nodes at all dominance frontiers of V's definition
blocks, iterating because placing a phi at F makes F a new definition
site, potentially requiring further phis at DF(F).

**Conservative insertion:** this algorithm places phis at all frontiers
regardless of whether the variable is actually live at that block
(non-pruned SSA).  A post-renaming pruning pass removes any phi whose
result is never used, making it correct without requiring a full
liveness analysis before insertion.

### Step 5 — Variable renaming

Renaming transforms each definition into a unique VReg and rewires uses
to the correct version.  The algorithm is a **DFS over the dominator
tree**, maintaining a renaming stack for each original variable.

```
Rename(B):
    for each phi in B:
        phi.result = fresh VReg for phi.original
        push to stack

    for each instruction in B:
        replace each use V with current(V)    ← top of stack for V
        if instruction defines V:
            V's result = fresh VReg
            push to stack

    rename terminator uses

    for each successor S of B:
        for each phi in S:
            phi.incoming[B] = current(phi.original)

    for each child of B in the dominator tree:
        Rename(child)

    pop all values pushed in this block
```

Parameters are initialised as version-0 of themselves (`stacks[p] = [p]`)
so that `current(p)` correctly returns the param VReg in any block.

Fresh VReg IDs start above the highest existing ID in the function, so
renamed variables never collide with original ones.

**Pruning:** after renaming, phi nodes whose result VReg is never
referenced by any instruction or other phi are removed.  These arise
from conservative insertion when a variable is not live at a frontier.

---

## `from_ssa()` — destruction

SSA destruction converts phi nodes back to ordinary copy instructions
and reconstructs the flat IR.

### Phi copy insertion

For each phi `%r = φ(P1 → %v1, P2 → %v2, ...)` in block B:
- At the end of P1's body (before its terminator): insert `%r = move %v1`
- At the end of P2's body: insert `%r = move %v2`
- Remove the phi from B

### Sequentialisation

Multiple copies inserted into the same predecessor block form a set of
**parallel copies** — conceptually, all assignments happen
simultaneously.  Emitting them sequentially can produce incorrect
results if one copy's destination is another's source.

Example (swap problem):
```
parallel:   %a ← %b,  %b ← %a

naive seq:  %a = move %b    ← correct
            %b = move %a    ← wrong: reads new %a, not old
```

Flux sequentialises using a topological sort of the copy dependency
graph.  Copies whose source is not written by another pending copy are
emitted first (safe copies).  This is repeated until all copies are
emitted.  Genuine cycles (which only arise from loop back-edges, not
from if-then-else) are emitted in order as a TODO — they do not appear
in the current IR.

### Reconstruction

Blocks are flattened back into a single instruction list in the
original split order, which preserves fall-through relationships.
`LABEL` pseudo-instructions are re-emitted for all blocks with real
label IDs (`L{n}`).  Blocks reachable only by fall-through (labelled
`__b{n}`) need no explicit label.

The resulting `Function` has the same structure as the pre-SSA IR and
is passed directly to the register allocator.

---

## Design decisions

**Pass-based rather than SSA-native IR.** The existing IR types
(`Instr`, `BasicBlock`, `Function`) are reused unchanged.  The SSA pass
is a pure transformation: `Function → SSAFunction → Function`.  This
keeps the BURG selector, allocator, and emitter completely unaware of
SSA, which simplifies each component and makes the pass optional.

**Non-pruned insertion with post-renaming pruning.** Pruned SSA
(inserting phis only where a variable is live) requires liveness
analysis before insertion.  Non-pruned insertion is simpler to implement
and the spurious phis are cheaply removed after renaming by checking
whether each phi's result is used.

**Cooper et al. dominators.** The Lengauer-Tarjan algorithm is
asymptotically faster but significantly more complex.  Cooper et al.'s
iterative algorithm is ~25 lines, correct, and fast enough for the
function sizes Flux targets.

---

## Source

| File | Contents |
|---|---|
| `flux/core/cfg.py` | `CFGBlock`, `build_cfg`, `reverse_postorder`, `compute_dominators`, `compute_frontiers` |
| `flux/core/ssa.py` | `PhiNode`, `SSABlock`, `SSAFunction`, `to_ssa`, `from_ssa` |
| `flux/tests/test_ssa.py` | CFG, dominator, phi, renaming, destruction, and end-to-end tests |
