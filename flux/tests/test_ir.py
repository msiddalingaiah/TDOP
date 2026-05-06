"""
Tests for the linear IR and FunctionBuilder.
"""
from flux.core.operands import Imm
from flux.core.ir       import VReg, Opcode, Instr, BasicBlock, Function
from flux.core.builder  import FunctionBuilder


class TestVReg:

    def test_repr(self):
        assert repr(VReg(0))  == "%0"
        assert repr(VReg(42)) == "%42"

    def test_equality(self):
        assert VReg(1) == VReg(1)
        assert VReg(1) != VReg(2)

    def test_hashable(self):
        # VRegs must be usable as dict keys (needed by the allocator later).
        d = {VReg(0): "a", VReg(1): "b"}
        assert d[VReg(0)] == "a"


class TestInstr:

    def test_repr_with_result(self):
        i = Instr(Opcode.LOAD_IMM, VReg(0), [Imm(42)])
        assert repr(i) == "%0 = load_imm #42"

    def test_repr_ret(self):
        i = Instr(Opcode.RET, None, [VReg(0)])
        assert repr(i) == "ret %0"

    def test_repr_add(self):
        i = Instr(Opcode.ADD, VReg(2), [VReg(0), VReg(1)])
        assert repr(i) == "%2 = add %0, %1"


class TestFunctionBuilder:

    def test_no_params(self):
        b = FunctionBuilder("const42")
        v = b.load_imm(42)
        b.ret(v)
        fn = b.build()

        assert fn.name   == "const42"
        assert fn.params == []
        assert len(fn.blocks) == 1
        block = fn.blocks[0]
        assert len(block.instrs) == 2
        assert block.instrs[0].opcode == Opcode.LOAD_IMM
        assert block.instrs[1].opcode == Opcode.RET

    def test_single_param(self):
        b  = FunctionBuilder("identity")
        a, = b.params(1)
        b.ret(a)
        fn = b.build()

        assert fn.params == [VReg(0)]
        instr = fn.blocks[0].instrs[0]
        assert instr.opcode      == Opcode.RET
        assert instr.operands[0] == VReg(0)

    def test_add_two_params(self):
        b = FunctionBuilder("add")
        a, x = b.params(2)
        r = b.add(a, x)
        b.ret(r)
        fn = b.build()

        assert fn.params == [VReg(0), VReg(1)]
        add_instr = fn.blocks[0].instrs[0]
        assert add_instr.opcode      == Opcode.ADD
        assert add_instr.result      == VReg(2)
        assert add_instr.operands    == [VReg(0), VReg(1)]

    def test_add_immediate(self):
        b = FunctionBuilder("inc")
        a, = b.params(1)
        r = b.add(a, Imm(1))
        b.ret(r)
        fn = b.build()

        add_instr = fn.blocks[0].instrs[0]
        assert add_instr.operands[1] == Imm(1)

    def test_sub(self):
        b = FunctionBuilder("sub")
        a, x = b.params(2)
        r = b.sub(a, x)
        b.ret(r)
        fn = b.build()

        sub_instr = fn.blocks[0].instrs[0]
        assert sub_instr.opcode == Opcode.SUB

    def test_move(self):
        b = FunctionBuilder("copy")
        a, = b.params(1)
        c = b.move(a)
        b.ret(c)
        fn = b.build()

        move_instr = fn.blocks[0].instrs[0]
        assert move_instr.opcode      == Opcode.MOVE
        assert move_instr.operands[0] == VReg(0)
        assert move_instr.result      == VReg(1)

    def test_vreg_ids_are_unique(self):
        b = FunctionBuilder("f")
        a, x = b.params(2)
        r1 = b.add(a, x)
        r2 = b.sub(r1, x)
        b.ret(r2)
        fn = b.build()

        # Collect every VReg that appears anywhere in the function.
        vregs = set(fn.params)
        for block in fn.blocks:
            for instr in block.instrs:
                if instr.result is not None:
                    vregs.add(instr.result)
        # All IDs must be distinct.
        ids = [v.id for v in vregs]
        assert len(ids) == len(set(ids))


class TestPrettyPrint:

    def test_function_repr(self):
        b = FunctionBuilder("add")
        a, x = b.params(2)
        r = b.add(a, x)
        b.ret(r)
        fn = b.build()

        text = repr(fn)
        assert "function add(%0, %1):" in text
        assert "%2 = add %0, %1"       in text
        assert "ret %2"                in text
