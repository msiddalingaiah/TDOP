from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, Union

from flux.core.operands import Imm
from flux.core.ir       import VReg
from flux.core.builder  import FunctionBuilder
from flux.core.tree     import (Expr, Const, Arg, Add, Sub, Mul, Div, Mod,
                                And, Or, Xor, Shl, Shr,
                                Lt, Gt, Eq, If, Let, Var,
                                MutVar, SetBang, Begin, While)


# ------------------------------------------------------------------
# Non-terminals
# ------------------------------------------------------------------

class NT(Enum):
    """Non-terminals in the BURG grammar.

    REG — the expression's value resides in a virtual register.
    IMM — the expression's value can be used as an immediate operand.
    """
    REG = auto()
    IMM = auto()


# ------------------------------------------------------------------
# State
# ------------------------------------------------------------------

INF = float("inf")

@dataclass(frozen=True)
class RuleEntry:
    """Best rule found so far for one NT at one node."""
    cost:    float
    rule_id: int    # 0 means "not reachable"

_UNREACHABLE = RuleEntry(INF, 0)

State = Dict[NT, RuleEntry]

def _empty_state() -> State:
    return {NT.REG: _UNREACHABLE, NT.IMM: _UNREACHABLE}

def _better(state: State, nt: NT, cost: float, rule_id: int) -> State:
    """Return an updated state if (cost, rule_id) improves on the current entry."""
    if cost < state[nt].cost:
        return {**state, nt: RuleEntry(cost, rule_id)}
    return state


# ------------------------------------------------------------------
# Result type
# ------------------------------------------------------------------

Result = Union[VReg, Imm]


# ------------------------------------------------------------------
# Selector
# ------------------------------------------------------------------

class BurgSelector:
    """BURG instruction selector.

    Tiles an Expr tree into linear-IR instructions using dynamic
    programming, in two phases:

    Phase 1 — label (bottom-up)
        For each node, compute the minimum cost to derive each NT.

    Phase 2 — reduce (top-down)
        Walk the tree using the recorded best rules and emit
        instructions into the FunctionBuilder.

    Rule table
    ----------
    ID  Pattern               NT   Cost
     1  Const                 imm   0    constant used directly as immediate
     2  Const                 reg   1    load constant into a register
     3  Arg                   reg   0    argument already in a register
     4  Add(reg, reg)         reg   1    add two registers
     5  Add(reg, imm)         reg   1    add register and immediate
     6  Sub(reg, reg)         reg   1    subtract two registers
     7  Sub(reg, imm)         reg   1    subtract immediate from register
     8  Mul(reg, reg)         reg   1    multiply two registers
     9  Mul(reg, imm)         reg   1    multiply register by immediate (3-operand imul)
    10  If(Lt/Gt/Eq, reg, reg) reg  1    conditional: cmp + branch + merge
    11  Let(name, reg, reg)   reg   0    bind name to value VReg, evaluate body
    12  Var(name)             reg   0    look up name in let-scope or emit load_var
    13  MutVar(name, reg, reg) reg  1    allocate slot, store init, evaluate body
    14  SetBang(name, reg)    reg   1    store value to mutable var, return value
    15  Begin(reg, reg)       reg   0    evaluate first (side effects), return second
    16  While(cond, reg)      reg   2    loop: label, cmp, branch, body, jmp-back
    17  Div(reg, reg)         reg   3    signed integer division (idiv)
    18  Mod(reg, reg)         reg   3    signed integer remainder (idiv)
    19  And(reg, reg)         reg   1    bitwise AND
    20  And(reg, imm)         reg   1    bitwise AND with immediate
    21  Or(reg, reg)          reg   1    bitwise OR
    22  Or(reg, imm)          reg   1    bitwise OR with immediate
    23  Xor(reg, reg)         reg   1    bitwise XOR
    24  Xor(reg, imm)         reg   1    bitwise XOR with immediate
    25  Shl(reg, reg)         reg   2    left shift (count in CL)
    26  Shl(reg, imm)         reg   1    left shift by immediate
    27  Shr(reg, reg)         reg   2    arithmetic right shift (count in CL)
    28  Shr(reg, imm)         reg   1    arithmetic right shift by immediate
    """

    def __init__(self, params: List[VReg], builder: FunctionBuilder) -> None:
        self.params    = params
        self.builder   = builder
        self._cache:   Dict[int, State] = {}   # id(node) → State
        self.scope:    Dict[str, VReg]  = {}   # immutable let-bound names → VReg
        self.mut_scope: Dict[str, object] = {} # mutable var names → MutableVar

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def select(self, root: Expr) -> VReg:
        """Tile *root*, emit instructions, and return the result VReg."""
        self._label(root)
        result = self._reduce(root, NT.REG)
        assert isinstance(result, VReg)
        return result

    # ------------------------------------------------------------------
    # Phase 1 — labeling (bottom-up DP)
    # ------------------------------------------------------------------

    def _label(self, node: Expr) -> State:
        key = id(node)
        if key in self._cache:
            return self._cache[key]

        state = _empty_state()

        match node:
            case Const():
                state = _better(state, NT.IMM, 0, 1)   # rule 1
                state = _better(state, NT.REG, 1, 2)   # rule 2

            case Arg():
                state = _better(state, NT.REG, 0, 3)   # rule 3

            case Add(left=l, right=r):
                lc = self._label(l)[NT.REG].cost
                rs = self._label(r)

                # rule 4: Add(reg, reg)
                c4 = lc + rs[NT.REG].cost + 1
                state = _better(state, NT.REG, c4, 4)

                # rule 5: Add(reg, imm)
                c5 = lc + rs[NT.IMM].cost + 1
                state = _better(state, NT.REG, c5, 5)

            case Sub(left=l, right=r):
                lc = self._label(l)[NT.REG].cost
                rs = self._label(r)

                # rule 6: Sub(reg, reg)
                c6 = lc + rs[NT.REG].cost + 1
                state = _better(state, NT.REG, c6, 6)

                # rule 7: Sub(reg, imm)
                c7 = lc + rs[NT.IMM].cost + 1
                state = _better(state, NT.REG, c7, 7)

            case Mul(left=l, right=r):
                lc = self._label(l)[NT.REG].cost
                rs = self._label(r)

                # rule 8: Mul(reg, reg)
                c8 = lc + rs[NT.REG].cost + 1
                state = _better(state, NT.REG, c8, 8)

                # rule 9: Mul(reg, imm)
                c9 = lc + rs[NT.IMM].cost + 1
                state = _better(state, NT.REG, c9, 9)

            case If(cond=c, then_=t, else_=e) if isinstance(c, (Lt, Gt, Eq)):
                # rule 10: If(comparison, expr, expr) → reg
                lc  = self._label(c.left)[NT.REG].cost
                rs  = self._label(c.right)
                rc  = min(rs[NT.REG].cost, rs[NT.IMM].cost)
                tc  = self._label(t)[NT.REG].cost
                ec  = self._label(e)[NT.REG].cost
                c10 = lc + rc + tc + ec + 1
                state = _better(state, NT.REG, c10, 10)

            case Lt() | Gt() | Eq():
                pass  # only valid as condition inside If

            case Let(value=v, body=b):
                # rule 11: Let → reg, cost = value cost + body cost + 0
                vc  = self._label(v)[NT.REG].cost
                bc  = self._label(b)[NT.REG].cost
                c11 = vc + bc
                state = _better(state, NT.REG, c11, 11)

            case Var():
                # rule 12: Var → reg, cost 0 (resolved at reduction time)
                state = _better(state, NT.REG, 0, 12)

            case MutVar(init=v, body=b):
                # rule 13: MutVar → reg, cost = init + store(1) + body
                vc  = self._label(v)[NT.REG].cost
                bc  = self._label(b)[NT.REG].cost
                c13 = vc + 1 + bc
                state = _better(state, NT.REG, c13, 13)

            case SetBang(value=v):
                # rule 14: SetBang → reg, cost = value + store(1)
                vc  = self._label(v)[NT.REG].cost
                c14 = vc + 1
                state = _better(state, NT.REG, c14, 14)

            case Begin(first=f, second=s):
                # rule 15: Begin → reg, cost = first + second
                fc  = self._label(f)[NT.REG].cost
                sc  = self._label(s)[NT.REG].cost
                c15 = fc + sc
                state = _better(state, NT.REG, c15, 15)

            case While(cond=c, body=b) if isinstance(c, (Lt, Gt, Eq)):
                # rule 16: While → reg, cost = cond + body + 2 (cmp + jmp)
                lc  = self._label(c.left)[NT.REG].cost
                rs  = self._label(c.right)
                rc  = min(rs[NT.REG].cost, rs[NT.IMM].cost)
                bc  = self._label(b)[NT.REG].cost
                c16 = lc + rc + bc + 2
                state = _better(state, NT.REG, c16, 16)

            case Div(left=l, right=r):
                # rule 17: Div(reg, reg) — no immediate form (idiv has none)
                lc  = self._label(l)[NT.REG].cost
                rc  = self._label(r)[NT.REG].cost
                state = _better(state, NT.REG, lc + rc + 3, 17)

            case Mod(left=l, right=r):
                # rule 18: Mod(reg, reg)
                lc  = self._label(l)[NT.REG].cost
                rc  = self._label(r)[NT.REG].cost
                state = _better(state, NT.REG, lc + rc + 3, 18)

            case And(left=l, right=r):
                lc, rs = self._label(l)[NT.REG].cost, self._label(r)
                state = _better(state, NT.REG, lc + rs[NT.REG].cost + 1, 19)
                state = _better(state, NT.REG, lc + rs[NT.IMM].cost + 1, 20)

            case Or(left=l, right=r):
                lc, rs = self._label(l)[NT.REG].cost, self._label(r)
                state = _better(state, NT.REG, lc + rs[NT.REG].cost + 1, 21)
                state = _better(state, NT.REG, lc + rs[NT.IMM].cost + 1, 22)

            case Xor(left=l, right=r):
                lc, rs = self._label(l)[NT.REG].cost, self._label(r)
                state = _better(state, NT.REG, lc + rs[NT.REG].cost + 1, 23)
                state = _better(state, NT.REG, lc + rs[NT.IMM].cost + 1, 24)

            case Shl(left=l, right=r):
                lc, rs = self._label(l)[NT.REG].cost, self._label(r)
                state = _better(state, NT.REG, lc + rs[NT.REG].cost + 2, 25)
                state = _better(state, NT.REG, lc + rs[NT.IMM].cost + 1, 26)

            case Shr(left=l, right=r):
                lc, rs = self._label(l)[NT.REG].cost, self._label(r)
                state = _better(state, NT.REG, lc + rs[NT.REG].cost + 2, 27)
                state = _better(state, NT.REG, lc + rs[NT.IMM].cost + 1, 28)

        self._cache[key] = state
        return state

    # ------------------------------------------------------------------
    # Phase 2 — reduction (top-down code generation)
    # ------------------------------------------------------------------

    def _reduce(self, node: Expr, nt: NT) -> Result:
        entry = self._cache[id(node)][nt]

        if entry.cost == INF:
            raise RuntimeError(
                f"No rule can derive {nt.name} for {node!r}"
            )

        match entry.rule_id:

            case 1:  # Const → imm
                assert isinstance(node, Const)
                return Imm(node.value)

            case 2:  # Const → reg
                assert isinstance(node, Const)
                return self.builder.load_imm(node.value)

            case 3:  # Arg → reg
                assert isinstance(node, Arg)
                return self.params[node.index]

            case 4:  # Add(reg, reg) → reg
                assert isinstance(node, Add)
                lhs = self._reduce(node.left,  NT.REG)
                rhs = self._reduce(node.right, NT.REG)
                assert isinstance(lhs, VReg) and isinstance(rhs, VReg)
                return self.builder.add(lhs, rhs)

            case 5:  # Add(reg, imm) → reg
                assert isinstance(node, Add)
                lhs = self._reduce(node.left,  NT.REG)
                rhs = self._reduce(node.right, NT.IMM)
                assert isinstance(lhs, VReg) and isinstance(rhs, Imm)
                return self.builder.add(lhs, rhs)

            case 6:  # Sub(reg, reg) → reg
                assert isinstance(node, Sub)
                lhs = self._reduce(node.left,  NT.REG)
                rhs = self._reduce(node.right, NT.REG)
                assert isinstance(lhs, VReg) and isinstance(rhs, VReg)
                return self.builder.sub(lhs, rhs)

            case 7:  # Sub(reg, imm) → reg
                assert isinstance(node, Sub)
                lhs = self._reduce(node.left,  NT.REG)
                rhs = self._reduce(node.right, NT.IMM)
                assert isinstance(lhs, VReg) and isinstance(rhs, Imm)
                return self.builder.sub(lhs, rhs)

            case 8:  # Mul(reg, reg) → reg
                assert isinstance(node, Mul)
                lhs = self._reduce(node.left,  NT.REG)
                rhs = self._reduce(node.right, NT.REG)
                assert isinstance(lhs, VReg) and isinstance(rhs, VReg)
                return self.builder.mul(lhs, rhs)

            case 9:  # Mul(reg, imm) → reg
                assert isinstance(node, Mul)
                lhs = self._reduce(node.left,  NT.REG)
                rhs = self._reduce(node.right, NT.IMM)
                assert isinstance(lhs, VReg) and isinstance(rhs, Imm)
                return self.builder.mul(lhs, rhs)

            case 10:  # If(cond, then, else) → reg
                assert isinstance(node, If)
                cond, then_, else_ = node.cond, node.then_, node.else_

                # Reduce condition operands — pick cheaper NT for rhs
                lhs = self._reduce(cond.left, NT.REG)
                cond_rs = self._cache[id(cond.right)]
                rhs_nt  = NT.IMM if cond_rs[NT.IMM].cost <= cond_rs[NT.REG].cost \
                          else NT.REG
                rhs = self._reduce(cond.right, rhs_nt)

                # Emit comparison
                self.builder.cmp(lhs, rhs)

                # Allocate branch targets
                else_label  = self.builder.new_label()
                merge_label = self.builder.new_label()

                # Conditional jump: invert condition → jump to else branch
                if isinstance(cond, Lt):
                    self.builder.jge(else_label)   # not (lhs < rhs) → lhs >= rhs
                elif isinstance(cond, Gt):
                    self.builder.jle(else_label)   # not (lhs > rhs) → lhs <= rhs
                elif isinstance(cond, Eq):
                    self.builder.jne(else_label)   # not (lhs = rhs)
                else:
                    raise RuntimeError(f"Unsupported condition: {type(cond)}")

                # Pre-allocate result VReg shared by both branches
                result = self.builder.alloc_vreg()

                # Then branch
                then_val = self._reduce(then_, NT.REG)
                assert isinstance(then_val, VReg)
                self.builder.move_to(result, then_val)
                self.builder.jmp(merge_label)

                # Else branch
                self.builder.place_label(else_label)
                else_val = self._reduce(else_, NT.REG)
                assert isinstance(else_val, VReg)
                self.builder.move_to(result, else_val)

                # Merge point
                self.builder.place_label(merge_label)
                return result

            case 11:  # Let(name, value, body) → reg
                assert isinstance(node, Let)
                # Evaluate the bound value.
                val_vreg = self._reduce(node.value, NT.REG)
                assert isinstance(val_vreg, VReg)

                # Extend scope: save any previous binding for the same name.
                prev = self.scope.get(node.name)
                self.scope[node.name] = val_vreg

                # Evaluate the body with the extended scope.
                body_result = self._reduce(node.body, NT.REG)

                # Restore scope.
                if prev is not None:
                    self.scope[node.name] = prev
                else:
                    del self.scope[node.name]

                assert isinstance(body_result, VReg)
                return body_result

            case 12:  # Var(name) → reg
                assert isinstance(node, Var)
                if node.name in self.mut_scope:
                    # Mutable variable: emit a load from its stack slot.
                    return self.builder.load_var(self.mut_scope[node.name])
                elif node.name in self.scope:
                    # Immutable let-binding: return the VReg directly.
                    return self.scope[node.name]
                else:
                    raise RuntimeError(f"Unbound variable: '{node.name!r}'")

            case 13:  # MutVar(name, init, body) → reg
                assert isinstance(node, MutVar)
                var       = self.builder.alloc_mutable_var()
                init_vreg = self._reduce(node.init, NT.REG)
                assert isinstance(init_vreg, VReg)
                self.builder.store_var(var, init_vreg)

                prev = self.mut_scope.get(node.name)
                self.mut_scope[node.name] = var
                body_vreg = self._reduce(node.body, NT.REG)
                if prev is not None:
                    self.mut_scope[node.name] = prev
                else:
                    del self.mut_scope[node.name]

                assert isinstance(body_vreg, VReg)
                return body_vreg

            case 14:  # SetBang(name, value) → reg
                assert isinstance(node, SetBang)
                if node.name not in self.mut_scope:
                    raise RuntimeError(
                        f"(set! {node.name!r} ...) — '{node.name}' is not a "
                        f"mutable variable"
                    )
                var       = self.mut_scope[node.name]
                val_vreg  = self._reduce(node.value, NT.REG)
                assert isinstance(val_vreg, VReg)
                self.builder.store_var(var, val_vreg)
                return val_vreg   # set! returns the assigned value

            case 15:  # Begin(first, second) → reg
                assert isinstance(node, Begin)
                self._reduce(node.first, NT.REG)   # side effects only
                return self._reduce(node.second, NT.REG)

            case 16:  # While(cond, body) → reg
                assert isinstance(node, While)
                cond = node.cond

                loop_start = self.builder.new_label()
                loop_exit  = self.builder.new_label()

                # ── loop header ──────────────────────────────────────────
                self.builder.place_label(loop_start)

                # Evaluate condition operands.
                lhs = self._reduce(cond.left, NT.REG)
                cond_rs = self._cache[id(cond.right)]
                rhs_nt  = NT.IMM if cond_rs[NT.IMM].cost <= cond_rs[NT.REG].cost \
                          else NT.REG
                rhs = self._reduce(cond.right, rhs_nt)

                self.builder.cmp(lhs, rhs)

                # Jump to exit if condition is false (inverted).
                if isinstance(cond, Lt):
                    self.builder.jge(loop_exit)
                elif isinstance(cond, Gt):
                    self.builder.jle(loop_exit)
                elif isinstance(cond, Eq):
                    self.builder.jne(loop_exit)
                else:
                    raise RuntimeError(f"Unsupported loop condition: {type(cond)}")

                # ── loop body ─────────────────────────────────────────────
                self._reduce(node.body, NT.REG)   # side effects only

                # ── back-edge ─────────────────────────────────────────────
                self.builder.jmp(loop_start)

                # ── loop exit ─────────────────────────────────────────────
                self.builder.place_label(loop_exit)

                # While returns 0 (the result is usually discarded).
                return self.builder.load_imm(0)

            case 17:  # Div(reg, reg) → reg
                assert isinstance(node, Div)
                lhs = self._reduce(node.left,  NT.REG)
                rhs = self._reduce(node.right, NT.REG)
                assert isinstance(lhs, VReg) and isinstance(rhs, VReg)
                return self.builder.div(lhs, rhs)

            case 18:  # Mod(reg, reg) → reg
                assert isinstance(node, Mod)
                lhs = self._reduce(node.left,  NT.REG)
                rhs = self._reduce(node.right, NT.REG)
                assert isinstance(lhs, VReg) and isinstance(rhs, VReg)
                return self.builder.mod(lhs, rhs)

            case 19:  # And(reg, reg)
                assert isinstance(node, And)
                lhs = self._reduce(node.left, NT.REG)
                rhs = self._reduce(node.right, NT.REG)
                return self.builder.band(lhs, rhs)
            case 20:  # And(reg, imm)
                assert isinstance(node, And)
                lhs = self._reduce(node.left, NT.REG)
                rhs = self._reduce(node.right, NT.IMM)
                return self.builder.band(lhs, rhs)
            case 21:  # Or(reg, reg)
                assert isinstance(node, Or)
                lhs = self._reduce(node.left, NT.REG)
                rhs = self._reduce(node.right, NT.REG)
                return self.builder.bor(lhs, rhs)
            case 22:  # Or(reg, imm)
                assert isinstance(node, Or)
                lhs = self._reduce(node.left, NT.REG)
                rhs = self._reduce(node.right, NT.IMM)
                return self.builder.bor(lhs, rhs)
            case 23:  # Xor(reg, reg)
                assert isinstance(node, Xor)
                lhs = self._reduce(node.left, NT.REG)
                rhs = self._reduce(node.right, NT.REG)
                return self.builder.bxor(lhs, rhs)
            case 24:  # Xor(reg, imm)
                assert isinstance(node, Xor)
                lhs = self._reduce(node.left, NT.REG)
                rhs = self._reduce(node.right, NT.IMM)
                return self.builder.bxor(lhs, rhs)
            case 25:  # Shl(reg, reg)
                assert isinstance(node, Shl)
                lhs = self._reduce(node.left, NT.REG)
                rhs = self._reduce(node.right, NT.REG)
                return self.builder.shl(lhs, rhs)
            case 26:  # Shl(reg, imm)
                assert isinstance(node, Shl)
                lhs = self._reduce(node.left, NT.REG)
                rhs = self._reduce(node.right, NT.IMM)
                return self.builder.shl(lhs, rhs)
            case 27:  # Shr(reg, reg)
                assert isinstance(node, Shr)
                lhs = self._reduce(node.left, NT.REG)
                rhs = self._reduce(node.right, NT.REG)
                return self.builder.shr(lhs, rhs)
            case 28:  # Shr(reg, imm)
                assert isinstance(node, Shr)
                lhs = self._reduce(node.left, NT.REG)
                rhs = self._reduce(node.right, NT.IMM)
                return self.builder.shr(lhs, rhs)

            case _:
                raise RuntimeError(f"Unknown rule id {entry.rule_id}")
