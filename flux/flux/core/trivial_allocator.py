from __future__ import annotations
from typing import Dict

from flux.core.ir        import VReg, Function
from flux.core.allocator import Allocator


class TrivialAllocator(Allocator):
    """Assigns virtual registers to physical registers in first-seen order.

    Rules:
    - Function parameters are pinned to the target's arg_registers in order.
    - All other result VRegs receive the next available register from the
      pool (all allocatable registers, minus those already pinned, minus
      the stack and frame pointers).
    - No spilling: raises RuntimeError if the pool is exhausted.

    This allocator exists solely to connect the pipeline end-to-end.
    It will be replaced by LinearScanAllocator for production use.
    """

    def _build_allocation(self, fn: Function) -> Dict[VReg, object]:
        alloc: Dict[VReg, object] = {}

        # Pin parameters to argument registers.
        if len(fn.params) > len(self.target.arg_registers):
            raise RuntimeError(
                f"Function has {len(fn.params)} parameters but target "
                f"only supports {len(self.target.arg_registers)} argument registers."
            )
        for vreg, reg in zip(fn.params, self.target.arg_registers):
            alloc[vreg] = reg

        # Build the pool of remaining allocatable registers.
        reserved = {self.target.stack_pointer, self.target.frame_pointer}
        used     = set(alloc.values())
        pool     = [r for r in self.target.registers
                    if r not in used and r not in reserved]
        pool_it  = iter(pool)

        # Assign result VRegs in the order they are first defined.
        for block in fn.blocks:
            for instr in block.instrs:
                if instr.result is not None and instr.result not in alloc:
                    try:
                        alloc[instr.result] = next(pool_it)
                    except StopIteration:
                        raise RuntimeError(
                            "Register spill required — not supported by TrivialAllocator."
                        )
        return alloc
