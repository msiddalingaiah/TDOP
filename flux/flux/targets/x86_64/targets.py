from flux.core.target import Target
from flux.targets.x86_64 import regs

# Windows x64 ABI
# Integer args:  RCX, RDX, R8, R9
# Caller-saved:  RAX, RCX, RDX, R8-R11
# Callee-saved:  RBX, RBP, RDI, RSI, R12-R15
WINDOWS = Target(
    name            = "x86-64-windows",
    registers       = [regs.RAX, regs.RCX, regs.RDX, regs.RBX,
                       regs.RSI, regs.RDI,
                       regs.R8,  regs.R9,  regs.R10, regs.R11,
                       regs.R12, regs.R13, regs.R14, regs.R15],
    caller_saved    = [regs.RAX, regs.RCX, regs.RDX,
                       regs.R8,  regs.R9,  regs.R10, regs.R11],
    callee_saved    = [regs.RBX, regs.RBP, regs.RDI, regs.RSI,
                       regs.R12, regs.R13, regs.R14, regs.R15],
    arg_registers   = [regs.RCX, regs.RDX, regs.R8, regs.R9],
    return_register = regs.RAX,
    stack_pointer   = regs.RSP,
    frame_pointer   = regs.RBP,
)

# System V AMD64 ABI (Linux / macOS)
# Integer args:  RDI, RSI, RDX, RCX, R8, R9
# Caller-saved:  RAX, RCX, RDX, RSI, RDI, R8-R11
# Callee-saved:  RBX, RBP, R12-R15
LINUX = Target(
    name            = "x86-64-linux",
    registers       = [regs.RAX, regs.RCX, regs.RDX, regs.RBX,
                       regs.RSI, regs.RDI,
                       regs.R8,  regs.R9,  regs.R10, regs.R11,
                       regs.R12, regs.R13, regs.R14, regs.R15],
    caller_saved    = [regs.RAX, regs.RCX, regs.RDX, regs.RSI, regs.RDI,
                       regs.R8,  regs.R9,  regs.R10, regs.R11],
    callee_saved    = [regs.RBX, regs.RBP,
                       regs.R12, regs.R13, regs.R14, regs.R15],
    arg_registers   = [regs.RDI, regs.RSI, regs.RDX,
                       regs.RCX, regs.R8,  regs.R9],
    return_register = regs.RAX,
    stack_pointer   = regs.RSP,
    frame_pointer   = regs.RBP,
)
