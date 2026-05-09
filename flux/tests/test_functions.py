"""
Tests for function definitions (defun) and calls (call).

Each test creates its own FunctionRegistry to avoid cross-test contamination.
"""
import pytest
from flux.core.registry  import FunctionRegistry
from flux.core.compiler  import compile_and_run
from flux.core.parser    import parse_expr
from flux.core.tree      import Defun, Call, Const, Arg, Mul


def reg():
    return FunctionRegistry()


# ------------------------------------------------------------------
# Parser
# ------------------------------------------------------------------

class TestParser:

    def test_defun_parses(self):
        expr = parse_expr("(defun square (x) (* x x))")
        assert isinstance(expr, Defun)
        assert expr.name   == "square"
        assert expr.params == ("x",)
        assert isinstance(expr.body, Mul)

    def test_call_parses(self):
        expr = parse_expr("(call square 7)")
        assert isinstance(expr, Call)
        assert expr.name == "square"
        assert expr.args == (Const(7),)

    def test_defun_multiple_params(self):
        expr = parse_expr("(defun add (a b) (+ a b))")
        assert expr.params == ("a", "b")

    def test_defun_multi_body_implicit_begin(self):
        from flux.core.tree import Begin
        expr = parse_expr("(defun f (x) (* x 2) (* x 3))")
        assert isinstance(expr.body, Begin)

    def test_defun_missing_name_raises(self):
        with pytest.raises(ValueError):
            parse_expr("(defun)")

    def test_call_missing_name_raises(self):
        with pytest.raises(ValueError):
            parse_expr("(call)")

    def test_call_with_expression_args(self):
        expr = parse_expr("(call f (+ 1 2))")
        assert isinstance(expr, Call)
        from flux.core.tree import Add
        assert isinstance(expr.args[0], Add)


# ------------------------------------------------------------------
# Basic function definitions and calls
# ------------------------------------------------------------------

class TestBasic:

    def test_identity(self):
        r = reg()
        compile_and_run("(defun id (x) x)", registry=r)
        assert compile_and_run("(call id 42)", registry=r) == 42

    def test_constant_function(self):
        r = reg()
        compile_and_run("(defun forty_two () 42)", registry=r)
        assert compile_and_run("(call forty_two)", registry=r) == 42

    def test_square(self):
        r = reg()
        compile_and_run("(defun square (x) (* x x))", registry=r)
        assert compile_and_run("(call square 6)", registry=r) == 36
        assert compile_and_run("(call square 7)", registry=r) == 49

    def test_add(self):
        r = reg()
        compile_and_run("(defun add (a b) (+ a b))", registry=r)
        assert compile_and_run("(call add 10 32)", registry=r) == 42

    def test_max_two(self):
        r = reg()
        compile_and_run("(defun mymax (a b) (if (> a b) a b))", registry=r)
        assert compile_and_run("(call mymax 3 7)",  registry=r) == 7
        assert compile_and_run("(call mymax 7 3)",  registry=r) == 7
        assert compile_and_run("(call mymax 5 5)",  registry=r) == 5

    def test_abs(self):
        r = reg()
        compile_and_run("(defun myabs (x) (if (< x 0) (* x -1) x))", registry=r)
        assert compile_and_run("(call myabs -42)", registry=r) == 42
        assert compile_and_run("(call myabs  42)", registry=r) == 42

    def test_defun_returns_zero(self):
        """defun expression itself returns 0."""
        r = reg()
        result = compile_and_run("(defun f (x) (* x 2))", registry=r)
        assert result == 0

    def test_call_from_expression(self):
        """Function call embedded in a larger expression."""
        r = reg()
        compile_and_run("(defun double (x) (* x 2))", registry=r)
        assert compile_and_run("(+ (call double 10) (call double 11))", registry=r) == 42


# ------------------------------------------------------------------
# Chained (non-recursive) function calls
# ------------------------------------------------------------------

class TestChained:

    def test_two_functions(self):
        r = reg()
        compile_and_run("(defun double (x) (* x 2))", registry=r)
        compile_and_run("(defun quad   (x) (call double (call double x)))", registry=r)
        assert compile_and_run("(call quad 3)", registry=r) == 12

    def test_function_calling_function(self):
        r = reg()
        compile_and_run("(defun inc (x) (+ x 1))", registry=r)
        compile_and_run("(defun inc3 (x) (call inc (call inc (call inc x))))", registry=r)
        assert compile_and_run("(call inc3 0)", registry=r) == 3


# ------------------------------------------------------------------
# Recursive functions
# ------------------------------------------------------------------

class TestRecursion:

    def test_factorial(self):
        r = reg()
        compile_and_run(
            "(defun fact (n) (if (= n 0) 1 (* n (call fact (- n 1)))))",
            registry=r
        )
        assert compile_and_run("(call fact 0)",  registry=r) == 1
        assert compile_and_run("(call fact 1)",  registry=r) == 1
        assert compile_and_run("(call fact 5)",  registry=r) == 120
        assert compile_and_run("(call fact 10)", registry=r) == 3628800

    def test_fibonacci_recursive(self):
        r = reg()
        compile_and_run(
            "(defun fib (n) (if (< n 2) n (+ (call fib (- n 1)) (call fib (- n 2)))))",
            registry=r
        )
        fibs = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55]
        for i, expected in enumerate(fibs):
            assert compile_and_run(f"(call fib {i})", registry=r) == expected, \
                f"fib({i}) should be {expected}"

    def test_sum_recursive(self):
        r = reg()
        compile_and_run(
            "(defun sum (n) (if (= n 0) 0 (+ n (call sum (- n 1)))))",
            registry=r
        )
        assert compile_and_run("(call sum 10)", registry=r) == 55
        assert compile_and_run("(call sum 100)", registry=r) == 5050

    def test_power(self):
        r = reg()
        compile_and_run(
            "(defun pow (base exp) (if (= exp 0) 1 (* base (call pow base (- exp 1)))))",
            registry=r
        )
        assert compile_and_run("(call pow 2 10)", registry=r) == 1024
        assert compile_and_run("(call pow 3 4)",  registry=r) == 81

    def test_gcd_recursive(self):
        r = reg()
        compile_and_run(
            "(defun gcd (a b) (if (= b 0) a (call gcd b (% a b))))",
            registry=r
        )
        assert compile_and_run("(call gcd 48 18)",  registry=r) == 6
        assert compile_and_run("(call gcd 100 75)", registry=r) == 25
        assert compile_and_run("(call gcd 17 13)",  registry=r) == 1


# ------------------------------------------------------------------
# Functions with local variables
# ------------------------------------------------------------------

class TestWithVars:

    def test_iterative_factorial(self):
        r = reg()
        compile_and_run("""
            (defun fact_iter (n)
              (var acc 1
                (var i n
                  (while (> i 0)
                    (set! acc (* acc i))
                    (set! i (- i 1)))
                  acc)))
        """, registry=r)
        assert compile_and_run("(call fact_iter 5)",  registry=r) == 120
        assert compile_and_run("(call fact_iter 10)", registry=r) == 3628800

    def test_function_with_let(self):
        r = reg()
        compile_and_run(
            "(defun hyp2 (a b) (let ((a2 (* a a)) (b2 (* b b))) (+ a2 b2)))",
            registry=r
        )
        assert compile_and_run("(call hyp2 3 4)", registry=r) == 25
        assert compile_and_run("(call hyp2 5 12)", registry=r) == 169


# ------------------------------------------------------------------
# Stack-passed arguments (beyond register count)
# Windows: 4 register args → stack starts at arg 5
# Linux:   6 register args → stack starts at arg 7
# Tests use 7+ args so they exercise stack passing on both platforms.
# ------------------------------------------------------------------

class TestStackArgs:

    def test_5_args(self):
        r = reg()
        compile_and_run(
            "(defun sum5 (a b c d e) (+ (+ (+ a b) (+ c d)) e))",
            registry=r
        )
        assert compile_and_run("(call sum5 1 2 3 4 5)", registry=r) == 15

    def test_7_args(self):
        """7 arguments: exercises stack passing on both Windows and Linux."""
        r = reg()
        compile_and_run(
            "(defun sum7 (a b c d e f g) (+ (+ (+ a b) (+ c d)) (+ (+ e f) g)))",
            registry=r
        )
        assert compile_and_run("(call sum7 1 2 3 4 5 6 7)", registry=r) == 28

    def test_8_args(self):
        r = reg()
        compile_and_run(
            "(defun sum8 (a b c d e f g h) (+ (+ (+ a b) (+ c d)) (+ (+ e f) (+ g h))))",
            registry=r
        )
        assert compile_and_run("(call sum8 1 2 3 4 5 6 7 8)", registry=r) == 36

    def test_stack_args_correct_values(self):
        """Verify each stack argument lands in the right parameter slot."""
        r = reg()
        # Return each argument individually to verify correct mapping.
        for defn, idx, expected in [
            ("(defun get7th (a b c d e f g) g)", 7, 7),
            ("(defun get6th (a b c d e f g) f)", 6, 6),
            ("(defun get5th (a b c d e f g) e)", 5, 5),
        ]:
            compile_and_run(defn, registry=r)
            name = defn.split()[1]
            assert compile_and_run(
                f"(call {name} 1 2 3 4 5 6 7)", registry=r
            ) == expected, f"{name} should return {expected}"

    def test_stack_arg_arithmetic(self):
        """Stack args participate in arithmetic like register args."""
        r = reg()
        compile_and_run(
            "(defun weighted (a b c d e f g) (+ (* a 1) (+ (* b 2) (+ (* c 3) (+ (* d 4) (+ (* e 5) (+ (* f 6) (* g 7))))))))",
            registry=r
        )
        # 1*1 + 2*2 + 3*3 + 4*4 + 5*5 + 6*6 + 7*7 = 1+4+9+16+25+36+49 = 140
        assert compile_and_run("(call weighted 1 2 3 4 5 6 7)", registry=r) == 140

    def test_call_with_stack_args_from_expression(self):
        """Stack arguments can be computed expressions, not just literals."""
        r = reg()
        compile_and_run(
            "(defun sum7 (a b c d e f g) (+ (+ (+ a b) (+ c d)) (+ (+ e f) g)))",
            registry=r
        )
        # Call with expressions as arguments
        assert compile_and_run(
            "(call sum7 (+ 1 0) (* 1 2) 3 4 5 6 (- 8 1))", registry=r
        ) == 28

    def test_recursive_with_stack_args(self):
        """A recursive function with more args than register count."""
        r = reg()
        # sum from lo to hi (inclusive) — 3 args, fine for both platforms,
        # but call it recursively to test interaction of calls + args.
        compile_and_run(
            "(defun range_sum (lo hi acc) (if (> lo hi) acc (call range_sum (+ lo 1) hi (+ acc lo))))",
            registry=r
        )
        assert compile_and_run("(call range_sum 1 10 0)", registry=r) == 55
        assert compile_and_run("(call range_sum 1 100 0)", registry=r) == 5050


# ------------------------------------------------------------------
# Registry isolation
# ------------------------------------------------------------------

class TestRegistry:

    def test_separate_registries_dont_share(self):
        r1 = reg()
        r2 = reg()
        compile_and_run("(defun f (x) (* x 2))", registry=r1)
        compile_and_run("(defun f (x) (* x 3))", registry=r2)
        assert compile_and_run("(call f 7)", registry=r1) == 14
        assert compile_and_run("(call f 7)", registry=r2) == 21

    def test_function_in_registry_can_be_called_multiple_times(self):
        r = reg()
        compile_and_run("(defun double (x) (* x 2))", registry=r)
        results = [compile_and_run("(call double n)", registry=r, n=i)
                   for i in range(5)]
        assert results == [0, 2, 4, 6, 8]
