# Register Allocation and Spilling

Flux uses a **linear scan** register allocator based on Poletto &
Sarkar (1999), extended with stack spilling.  The allocator is
implemented in `flux/core/linear_scan.py` and inherits shared
instruction-lowering logic from `flux/core/allocator.py`.

---

## Overview

Register allocation maps virtual registers (VRegs) produced by the
instruction selector to physical machine registers.  The allocator
operates on the flat IR produced by SSA destruction — a single
instruction list with embedded `LABEL` and branch pseudo-instructions.

The two allocators in Flux share a base class:

| Class | Strategy | Spilling |
|---|---|---|
| `TrivialAllocator` | First-seen order | No — raises `RuntimeError` |
| `LinearScanAllocator` | Live intervals, Poletto & Sarkar (1999) | Yes — RBP-relative stack slots |

---

## Live intervals

A **live interval** `[start, end]` for a VReg is the range of
instruction positions over which it must be kept in a register.

- `start` — the position where the VReg is first defined (params use
  `start = -1` to mark them as live before the first instruction)
- `end` — the position of the VReg's last use

`compute_intervals()` computes these with a single forward scan over
the flat instruction list.  For each instruction:
- If it defines a new VReg, open an interval starting at the current position
- For each VReg operand, extend its interval to cover the current position

Because the current IR is a flat list (including branch/label
pseudo-instructions that use no VRegs), the scan is straightforward.
Cross-block liveness — where a variable is live across a branch — is
handled correctly because the flat ordering preserves the execution
sequence.

---

## Linear scan algorithm

Intervals are processed in **start-point order**.  A set of *active*
intervals tracks which VRegs currently hold a physical register.

```
for each interval IV in start-point order:
    expire active intervals whose end < IV.start  →  return registers to pool
    if free pool is not empty:
        assign IV the next free register
        add IV to active (sorted by end point)
    else:
        spill_at_interval(IV)
```

The **expiry** step is the key reuse mechanism: as soon as a VReg's
live range ends, its register is returned to the pool and can be
immediately reassigned.

Parameters are pre-assigned to the target's argument registers (RCX,
RDX, R8, R9 on Windows; RDI, RSI, RDX, RCX, R8, R9 on Linux) and
added to the initial active set.  Their registers become available for
reuse once the parameter's interval expires.

---

## Spilling

When the free pool is empty, the allocator must **spill** — store a
VReg's value to the stack and reload it only when needed.

### Victim selection

The interval with the **furthest end point** is chosen as the spill
candidate.  This maximises the time the freed register is available for
other intervals.  If the current interval IV has a further end point
than any active interval, IV itself is spilled; otherwise, the active
interval with the furthest end is spilled and IV takes its register.

### Spill slots

Spill slots are addressed as `[RBP + offset]` where offset is negative:
- Slot 0: `[rbp - 8]`
- Slot 1: `[rbp - 16]`
- Slot k: `[rbp - (k+1) * 8]`

The total frame size is rounded up to a multiple of 16 bytes to
maintain stack alignment.

### Scratch registers

Two physical registers are **reserved** from the allocatable pool and
used exclusively for spill reload and store:

| ABI | Scratch 1 | Scratch 2 |
|---|---|---|
| Windows x64 | R14 | R15 |
| Linux x64 | R14 | R15 |

Both are callee-saved on both ABIs, so they must be preserved across
function calls.  They are saved and restored in the prologue and
epilogue when spilling is active.

### Scratch register assignment

When lowering a spilled instruction:
- Operand 0 (lhs), if spilled → reloaded into scratch register 1
- Operand 1 (rhs), if spilled → reloaded into scratch register 2
- Result, if spilled → written to scratch register 1, then stored to its slot

Using scratch 1 for both operand 0 and the result is safe for x86
two-address operations: the lhs is consumed before the result is
written (the operation overwrites lhs with the result).

---

## Stack frame layout

A stack frame is emitted only when spilling is required.  The prologue
and epilogue wrap the function body.

### Prologue

```asm
push  rbp          ; save caller's frame pointer
push  r14          ; save scratch register 2
push  r15          ; save scratch register 1
mov   rbp, rsp     ; establish frame pointer (after the three pushes)
sub   rsp, N       ; allocate spill area (N = frame_size, multiple of 16)
```

After the prologue, the stack layout is:

```
rbp + 0   : saved r15   ← rbp was set here (after all three pushes)
rbp + 8   : saved r14
rbp + 16  : saved rbp
rbp + 24  : return address
rbp - 8   : spill slot 0
rbp - 16  : spill slot 1
    ...
rbp - N   : spill slot N/8 - 1
```

### Epilogue

```asm
mov   rsp, rbp     ; release spill area
pop   r15          ; restore scratch register 1
pop   r14          ; restore scratch register 2
pop   rbp          ; restore caller's frame pointer
ret
```

### Alignment

At function entry (after the `call` instruction pushed the return
address), RSP is 8-byte aligned mod 16.  After `push rbp; push r14;
push r15` (three 8-byte pushes), RSP is 16-byte aligned.  `sub rsp, N`
maintains alignment when N is a multiple of 16.

### Spilled parameters

When a parameter's register is claimed by a longer-lived interval, the
parameter is assigned a spill slot.  Its original value is in the
argument register at function entry.  Immediately after the prologue,
the allocator emits a `store_spill` to save that value to the slot
before any instruction can overwrite the register.

---

## Instruction lowering

The `Allocator` base class (`flux/core/allocator.py`) provides
`_lower()`, which walks the flat instruction list and drives the emitter
using the physical register assignment.

```python
match instr.opcode:
    case Opcode.LOAD_IMM: emitter.mov(reg(result), imm)
    case Opcode.MOVE:     emitter.mov(reg(result), reg(src))  # if dst ≠ src
    case Opcode.ADD:      emitter.mov(reg(result), reg(lhs))  # if result ≠ lhs
                          emitter.add(reg(result), resolve(rhs))
    ...
    case Opcode.RET:      emitter.mov(return_reg, reg(value))  # if needed
                          emitter.ret()
```

`LinearScanAllocator` overrides `allocate()` to:
1. Emit the prologue if spilling is required
2. Store spilled parameters immediately after the prologue
3. Call `_lower_spilling()` instead of `_lower()` when spills are present

`_lower_spilling()` builds a temporary allocation dict with spilled
VRegs mapped to scratch registers, emits the necessary reloads, calls
the base `_lower()` with the temporary dict, then emits any result store.

---

## Calling conventions

Flux defines two `Target` instances in `flux/targets/x86_64/targets.py`.

### Windows x64 (Microsoft ABI)

| Role | Registers |
|---|---|
| Integer arguments | RCX, RDX, R8, R9 |
| Return value | RAX |
| Caller-saved | RAX, RCX, RDX, R8–R11 |
| Callee-saved | RBX, RBP, RDI, RSI, R12–R15 |
| Allocatable | RAX, RCX, RDX, RBX, RSI, RDI, R8–R13 (12 registers) |
| Scratch | R14, R15 |

### Linux x64 (System V AMD64 ABI)

| Role | Registers |
|---|---|
| Integer arguments | RDI, RSI, RDX, RCX, R8, R9 |
| Return value | RAX |
| Caller-saved | RAX, RCX, RDX, RSI, RDI, R8–R11 |
| Callee-saved | RBX, RBP, R12–R15 |
| Allocatable | RAX, RCX, RDX, RBX, RSI, RDI, R8–R13 (12 registers) |
| Scratch | R14, R15 |

The active target is selected from `sys.platform` at runtime.

---

## Design decisions

**Linear scan over graph colouring.** Graph colouring produces optimal
register assignments but is NP-complete in general and complex to
implement correctly.  Linear scan is O(n) in the number of intervals,
simple to implement, and produces good results in practice — especially
after SSA construction shortens live ranges.

**Furthest-end-point spill heuristic.** Spilling the interval with the
furthest end point maximises the time a register is free for other
intervals.  This is the heuristic recommended by Poletto & Sarkar and
performs well on typical code.

**Two scratch registers, not one.** Binary operations with two spilled
operands require two simultaneous reloads.  Using a single scratch
register would require serialising operand loads with a stack-based
temporary, complicating the lowering logic.  Two scratch registers
(R14 and R15) handle all cases cleanly at the cost of two fewer
allocatable registers.

**Frame emitted only when needed.** Functions without spills produce no
prologue or epilogue overhead.  Simple leaf functions that fit within
the 12 allocatable registers run as lean, frame-less code.

---

## Source

| File | Contents |
|---|---|
| `flux/core/allocator.py` | `Allocator` base class, shared `_lower()` |
| `flux/core/trivial_allocator.py` | `TrivialAllocator` |
| `flux/core/linear_scan.py` | `LiveInterval`, `compute_intervals`, `LinearScanAllocator` |
| `flux/core/operands.py` | `SpillSlot` |
| `flux/core/target.py` | `Target` descriptor |
| `flux/targets/x86_64/targets.py` | `WINDOWS` and `LINUX` target instances |
| `flux/tests/test_linear_scan.py` | interval computation, register reuse tests |
| `flux/tests/test_spill.py` | spill detection and correctness tests |
