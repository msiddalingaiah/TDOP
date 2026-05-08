"""
Tests for the S-expression parser and the compile_and_run entry point.
"""
import pytest

from flux.core.tree     import Const, Arg, Add, Sub, Mul
from flux.core.parser   import parse_expr
from flux.core.compiler import compile_and_run


# ------------------------------------------------------------------
# Parser tests
# ------------------------------------------------------------------

class TestParser:

    def test_integer_literal(self):
        assert parse_expr("42") == Const(42)

    def test_negative_literal(self):
        assert parse_expr("-7") == Const(-7)

    def test_named_arg(self):
        assert parse_expr("x", args=["x"]) == Arg(0)

    def test_second_arg(self):
        assert parse_expr("y", args=["x", "y"]) == Arg(1)

    def test_add(self):
        assert parse_expr("(+ 1 2)") == Add(Const(1), Const(2))

    def test_sub(self):
        assert parse_expr("(- 5 3)") == Sub(Const(5), Const(3))

    def test_mul(self):
        assert parse_expr("(* 3 7)") == Mul(Const(3), Const(7))

    def test_nested(self):
        assert parse_expr("(+ (* 3 4) 2)") == Add(
            Mul(Const(3), Const(4)), Const(2)
        )

    def test_arg_in_expression(self):
        assert parse_expr("(* x 3)", args=["x"]) == Mul(Arg(0), Const(3))

    def test_two_args(self):
        assert parse_expr("(+ x y)", args=["x", "y"]) == Add(Arg(0), Arg(1))

    def test_whitespace_tolerance(self):
        assert parse_expr("  ( +  1   2 )  ") == Add(Const(1), Const(2))

    def test_deeply_nested(self):
        # (+ (* x 3) (- y 1))
        result = parse_expr("(+ (* x 3) (- y 1))", args=["x", "y"])
        expected = Add(Mul(Arg(0), Const(3)), Sub(Arg(1), Const(1)))
        assert result == expected

    def test_unknown_operator_raises(self):
        with pytest.raises(ValueError, match="Unknown operator"):
            parse_expr("(/ 4 2)")

    def test_unknown_symbol_raises(self):
        # An invalid token (not a number, operator, or valid identifier) raises.
        with pytest.raises(ValueError, match="Unknown symbol"):
            parse_expr("123abc")   # not a valid identifier or integer

    def test_wrong_arity_raises(self):
        with pytest.raises(ValueError, match="exactly 2 operands"):
            parse_expr("(+ 1 2 3)")

    def test_missing_close_paren_raises(self):
        with pytest.raises(ValueError, match="Missing closing"):
            parse_expr("(+ 1 2")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="Empty expression"):
            parse_expr("")


# ------------------------------------------------------------------
# compile_and_run tests
# ------------------------------------------------------------------

class TestCompileAndRun:

    def test_constant(self):
        assert compile_and_run("42") == 42

    def test_negative_constant(self):
        assert compile_and_run("-7") == -7

    def test_add_constants(self):
        assert compile_and_run("(+ 20 22)") == 42

    def test_sub_constants(self):
        assert compile_and_run("(- 50 8)") == 42

    def test_mul_constants(self):
        assert compile_and_run("(* 6 7)") == 42

    def test_single_variable(self):
        assert compile_and_run("x", x=42) == 42

    def test_add_variable_and_const(self):
        assert compile_and_run("(+ x 1)", x=41) == 42

    def test_mul_variable_and_const(self):
        assert compile_and_run("(* x 6)", x=7) == 42

    def test_two_variables(self):
        assert compile_and_run("(+ x y)", x=10, y=32) == 42

    def test_nested_arithmetic(self):
        assert compile_and_run("(+ (* x 3) (- y 1))", x=10, y=13) == 42

    def test_deep_expression(self):
        # ((a * b) + (c - d))
        assert compile_and_run(
            "(+ (* a b) (- c d))", a=5, b=7, c=10, d=3
        ) == 42

    def test_mul_imm_uses_3op_form(self):
        # Constant on the right of * should tile as 3-operand imul.
        assert compile_and_run("(* x 7)", x=6) == 42

    def test_all_operators(self):
        # (((x + y) * 2) - z)
        assert compile_and_run(
            "(- (* (+ x y) 2) z)", x=10, y=11, z=0
        ) == 42
