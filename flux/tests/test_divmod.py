"""
Tests for division (/) and modulo (%).

x86-64 IDIV specifics:
  - Dividend in RDX:RAX, divisor in any GP register
  - Quotient → RAX, remainder → RDX
  - Signed division — truncates toward zero
"""
import pytest
from flux.core.compiler import compile_and_run
from flux.core.parser   import parse_expr
from flux.core.tree     import Div, Mod, Const, Arg


# ------------------------------------------------------------------
# Parser
# ------------------------------------------------------------------

class TestParser:

    def test_div_parses(self):
        assert parse_expr("(/ 10 2)") == Div(Const(10), Const(2))

    def test_mod_parses(self):
        assert parse_expr("(% 10 3)") == Mod(Const(10), Const(3))

    def test_div_with_args(self):
        assert parse_expr("(/ a b)", args=["a", "b"]) == Div(Arg(0), Arg(1))

    def test_nested(self):
        from flux.core.tree import Add
        expr = parse_expr("(+ (/ a b) (% a b))", args=["a", "b"])
        assert isinstance(expr, Add)
        assert isinstance(expr.left, Div)
        assert isinstance(expr.right, Mod)


# ------------------------------------------------------------------
# Division correctness
# ------------------------------------------------------------------

class TestDivision:

    def test_basic(self):
        assert compile_and_run("(/ 42 6)")    == 7
        assert compile_and_run("(/ 100 10)")  == 10
        assert compile_and_run("(/ 7 2)")     == 3    # truncates toward zero

    def test_with_args(self):
        assert compile_and_run("(/ a b)", a=100, b=4) == 25
        assert compile_and_run("(/ a b)", a=17,  b=5) == 3

    def test_negative_dividend(self):
        assert compile_and_run("(/ a b)", a=-42, b=6)  == -7
        assert compile_and_run("(/ a b)", a=-7,  b=2)  == -3  # truncates toward zero

    def test_negative_divisor(self):
        assert compile_and_run("(/ a b)", a=42, b=-6)  == -7
        assert compile_and_run("(/ a b)", a=7,  b=-2)  == -3

    def test_both_negative(self):
        assert compile_and_run("(/ a b)", a=-42, b=-6) == 7

    def test_result_one(self):
        assert compile_and_run("(/ a b)", a=7, b=7) == 1

    def test_result_zero(self):
        assert compile_and_run("(/ a b)", a=3, b=7) == 0

    def test_nested_division(self):
        assert compile_and_run("(/ (/ a b) c)", a=100, b=5, c=4) == 5

    def test_div_in_expression(self):
        # (a / b) + (a % b) = a for positive a and b
        assert compile_and_run(
            "(+ (* (/ a b) b) (% a b))", a=17, b=5
        ) == 17


# ------------------------------------------------------------------
# Modulo correctness
# ------------------------------------------------------------------

class TestModulo:

    def test_basic(self):
        assert compile_and_run("(% 17 5)")  == 2
        assert compile_and_run("(% 10 3)")  == 1
        assert compile_and_run("(% 9 3)")   == 0

    def test_with_args(self):
        assert compile_and_run("(% a b)", a=17, b=5) == 2
        assert compile_and_run("(% a b)", a=42, b=7) == 0

    def test_negative_dividend(self):
        # x86 IDIV truncates toward zero, so remainder sign matches dividend
        assert compile_and_run("(% a b)", a=-17, b=5) == -2
        assert compile_and_run("(% a b)", a=-7,  b=3) == -1

    def test_zero_remainder(self):
        assert compile_and_run("(% a b)", a=42, b=6) == 0

    def test_mod_larger_than_divisor(self):
        assert compile_and_run("(% a b)", a=3, b=7) == 3


# ------------------------------------------------------------------
# Practical uses
# ------------------------------------------------------------------

class TestPractical:

    def test_even_check(self):
        even = "(if (= (% n 2) 0) 1 0)"
        assert compile_and_run(even, n=42) == 1
        assert compile_and_run(even, n=41) == 0
        assert compile_and_run(even, n=0)  == 1

    def test_divisible_by_three(self):
        expr = "(if (= (% n 3) 0) 1 0)"
        assert compile_and_run(expr, n=9)  == 1
        assert compile_and_run(expr, n=10) == 0

    def test_gcd(self):
        # Euclidean GCD using while loop
        gcd = """
            (var a x
              (var b y
                (while (> b 0)
                  (var tmp (% a b)
                    (set! a b)
                    (set! b tmp)))
                a))
        """
        assert compile_and_run(gcd, x=48,  y=18)  == 6
        assert compile_and_run(gcd, x=100, y=75)  == 25
        assert compile_and_run(gcd, x=17,  y=13)  == 1
        assert compile_and_run(gcd, x=0,   y=42)  == 42

    def test_integer_sqrt_floor(self):
        # floor(sqrt(n)) via loop: find largest i where i*i <= n
        isqrt = """
            (var i 0
              (while (< (* (+ i 1) (+ i 1)) (+ n 1))
                (set! i (+ i 1)))
              i)
        """
        assert compile_and_run(isqrt, n=0)   == 0
        assert compile_and_run(isqrt, n=1)   == 1
        assert compile_and_run(isqrt, n=8)   == 2
        assert compile_and_run(isqrt, n=9)   == 3
        assert compile_and_run(isqrt, n=15)  == 3
        assert compile_and_run(isqrt, n=100) == 10
