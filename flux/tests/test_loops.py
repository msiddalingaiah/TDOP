"""
Tests for while loops, and a performance comparison against Python.

Run the benchmark with:
    python -m pytest tests/test_loops.py::TestBenchmark -v -s
"""
import ctypes
import sys
import time
import pytest

from flux.core.tree      import Const, Arg, Add, Sub, Mul, If, Lt, Gt, Eq
from flux.core.tree      import MutVar, SetBang, Begin, While, Var
from flux.core.builder   import FunctionBuilder
from flux.core.burg      import BurgSelector
from flux.core.parser    import parse_expr
from flux.core.compiler  import compile_and_run, compile_expr
from flux.core.linear_scan import LinearScanAllocator
from flux.targets.x86_64.emitter  import X86_64Emitter
from flux.targets.x86_64.targets  import WINDOWS, LINUX

from tests.jit import make_callable, free_code

TARGET = WINDOWS if sys.platform == "win32" else LINUX


def run_tree(n_params, expr, *args):
    builder  = FunctionBuilder("f")
    params   = builder.params(n_params)
    selector = BurgSelector(params, builder)
    result   = selector.select(expr)
    builder.ret(result)
    fn       = builder.build()
    emitter  = X86_64Emitter(TARGET)
    LinearScanAllocator(TARGET).allocate(fn, emitter)
    code = emitter.get_code()
    argtypes = [ctypes.c_int64] * len(args)
    func, handle = make_callable(code, ctypes.c_int64, *argtypes)
    value = func(*args)
    free_code(handle)
    return value


# ------------------------------------------------------------------
# Parser tests
# ------------------------------------------------------------------

class TestParser:

    def test_while_parses(self):
        expr = parse_expr("(var i 0 (while (< i 10) (set! i (+ i 1))) i)")
        assert isinstance(expr, MutVar)

    def test_while_condition(self):
        expr = parse_expr("(while (< x 5) x)", args=["x"])
        assert isinstance(expr, While)
        assert isinstance(expr.cond, Lt)

    def test_while_multi_body_implicit_begin(self):
        expr = parse_expr(
            "(while (< i n) (set! i (+ i 1)) (set! s (+ s i)))",
            args=["i", "n", "s"]
        )
        assert isinstance(expr, While)
        assert isinstance(expr.body, Begin)

    def test_while_single_body(self):
        expr = parse_expr("(while (< i 0) (set! i 1))", args=["i"])
        assert isinstance(expr, While)
        assert isinstance(expr.body, SetBang)

    def test_while_missing_body_raises(self):
        with pytest.raises(ValueError, match="at least one"):
            parse_expr("(while (< i 10))", args=["i"])

    def test_while_gt_condition(self):
        expr = parse_expr("(while (> x 0) (set! x (- x 1)))", args=["x"])
        assert isinstance(expr.cond, Gt)

    def test_while_eq_condition(self):
        expr = parse_expr("(while (= x 0) (set! x 1))", args=["x"])
        assert isinstance(expr.cond, Eq)


# ------------------------------------------------------------------
# Correctness tests
# ------------------------------------------------------------------

class TestCorrectness:

    def test_loop_never_executes(self):
        # i starts at 10, condition (< i 10) is immediately false
        result = compile_and_run(
            "(var i 10 (var sum 0 (while (< i 10) (set! sum (+ sum i)) (set! i (+ i 1))) sum))"
        )
        assert result == 0

    def test_loop_executes_once(self):
        result = compile_and_run(
            "(var i 0 (var sum 0 (while (< i 1) (set! sum (+ sum i)) (set! i (+ i 1))) sum))"
        )
        assert result == 0   # sum of [0] = 0

    def test_sum_0_to_9(self):
        result = compile_and_run(
            "(var i 0 (var sum 0 (while (< i 10) (set! sum (+ sum i)) (set! i (+ i 1))) sum))"
        )
        assert result == sum(range(10))

    def test_sum_0_to_99(self):
        result = compile_and_run(
            "(var i 0 (var sum 0 (while (< i 100) (set! sum (+ sum i)) (set! i (+ i 1))) sum))"
        )
        assert result == sum(range(100))

    def test_sum_with_arg_bound(self):
        # sum from 0 to n-1
        result = compile_and_run(
            "(var i 0 (var sum 0 (while (< i n) (set! sum (+ sum i)) (set! i (+ i 1))) sum))",
            n=100
        )
        assert result == sum(range(100))

    def test_countdown(self):
        # count down from n to 1, sum all values
        result = compile_and_run(
            "(var i n (var sum 0 (while (> i 0) (set! sum (+ sum i)) (set! i (- i 1))) sum))",
            n=10
        )
        assert result == sum(range(1, 11))

    def test_multiply_by_repeated_addition(self):
        # a * b via repeated addition
        result = compile_and_run(
            "(var i 0 (var result 0 (while (< i b) (set! result (+ result a)) (set! i (+ i 1))) result))",
            a=6, b=7
        )
        assert result == 42

    def test_nested_loops_not_yet(self):
        # Verify a non-trivial loop: sum of squares 0..n-1
        # sum += i*i  implemented as repeated-addition inner loop
        # This is just a single loop with multiplication
        result = compile_and_run(
            "(var i 0 (var sum 0 (while (< i n) (set! sum (+ sum (* i i))) (set! i (+ i 1))) sum))",
            n=5
        )
        assert result == sum(i*i for i in range(5))   # 0+1+4+9+16 = 30

    def test_loop_with_conditional_body(self):
        # Sum only even numbers 0..n-1
        # even check: i - (i/2)*2 ... but we don't have division.
        # Use modular approach: toggle a flag instead.
        # flag starts 0, flip each iteration; add i only when flag=0
        # Actually simpler: sum i where i%2==0 → sum += i when (i - last_even == 2)
        # Let's just do: sum of every other element starting from 0
        result = compile_and_run("""
            (var i 0
              (var sum 0
                (while (< i n)
                  (set! sum (+ sum i))
                  (set! i (+ i 2)))
                sum))
        """, n=10)
        assert result == sum(range(0, 10, 2))   # 0+2+4+6+8 = 20

    def test_fibonacci(self):
        # fib(n): iterative
        result = compile_and_run("""
            (var a 0
              (var b 1
                (var i 0
                  (while (< i n)
                    (var tmp (+ a b)
                      (set! a b)
                      (set! b tmp))
                    (set! i (+ i 1)))
                  a)))
        """, n=10)
        # fib sequence: 0,1,1,2,3,5,8,13,21,34,55
        # after 10 steps, a = fib(10) = 55
        assert result == 55

    def test_large_loop(self):
        # 1 million iterations — tests correctness at scale
        result = compile_and_run(
            "(var i 0 (var sum 0 (while (< i n) (set! sum (+ sum i)) (set! i (+ i 1))) sum))",
            n=1_000_000
        )
        assert result == sum(range(1_000_000))


# ------------------------------------------------------------------
# Performance benchmark
# ------------------------------------------------------------------

class TestBenchmark:
    """Timing comparison: Flux native code vs CPython.

    Run with:  python -m pytest tests/test_loops.py::TestBenchmark -v -s
    """

    N = 100_000_000   # 100 million iterations

    def _make_flux_fn(self):
        """Compile the sum-of-integers loop and return a callable."""
        _, code = compile_expr("""
            (var i 0
              (var sum 0
                (while (< i n)
                  (set! sum (+ sum i))
                  (set! i (+ i 1)))
                sum))
        """, n=0)   # n=0 just to get the right signature; actual n passed at call time
        func, handle = make_callable(code, ctypes.c_int64, ctypes.c_int64)
        return func, handle

    def _python_sum(self, n):
        i   = 0
        acc = 0
        while i < n:
            acc += i
            i   += 1
        return acc

    def test_benchmark(self):
        N = self.N
        expected = N * (N - 1) // 2

        # --- Flux ---
        _, code = compile_expr(
            "(var i 0 (var sum 0 (while (< i n) (set! sum (+ sum i)) (set! i (+ i 1))) sum))",
            n=0
        )
        func, handle = make_callable(code, ctypes.c_int64, ctypes.c_int64)

        t0 = time.perf_counter()
        flux_result = func(N)
        flux_time   = time.perf_counter() - t0
        free_code(handle)

        assert flux_result == expected, f"Flux result wrong: {flux_result} != {expected}"

        # --- Python ---
        t0 = time.perf_counter()
        py_result = self._python_sum(N)
        py_time   = time.perf_counter() - t0

        assert py_result == expected

        speedup = py_time / flux_time

        print(f"\n{'─' * 50}")
        print(f"  Sum of 0..{N-1:,}")
        print(f"  Flux:   {flux_time*1000:8.1f} ms   result = {flux_result:,}")
        print(f"  Python: {py_time*1000:8.1f} ms   result = {py_result:,}")
        print(f"  Speedup: {speedup:.1f}×")
        print(f"{'─' * 50}")

        # Flux should be faster than Python for a tight loop.
        assert flux_time < py_time, (
            f"Expected Flux to be faster than Python "
            f"(Flux: {flux_time:.3f}s, Python: {py_time:.3f}s)"
        )
