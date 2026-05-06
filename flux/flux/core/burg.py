from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, Union

from flux.core.operands import Imm
from flux.core.ir       import VReg
from flux.core.builder  import FunctionBuilder
from flux.core.tree     import Expr, Const, Arg, Add, Sub, Mul


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
    ID  Pattern           NT   Cost
     1  Const             imm   0    constant used directly as immediate
     2  Const             reg   1    load constant into a register
     3  Arg               reg   0    argument already in a register
     4  Add(reg, reg)     reg   1    add two registers
     5  Add(reg, imm)     reg   1    add register and immediate
     6  Sub(reg, reg)     reg   1    subtract two registers
     7  Sub(reg, imm)     reg   1    subtract immediate from register
     8  Mul(reg, reg)     reg   1    multiply two registers
     9  Mul(reg, imm)     reg   1    multiply register by immediate (3-operand imul)
    """

    def __init__(self, params: List[VReg], builder: FunctionBuilder) -> None:
        self.params  = params
        self.builder = builder
        self._cache: Dict[int, State] = {}   # id(node) → State

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

            case _:
                raise RuntimeError(f"Unknown rule id {entry.rule_id}")
