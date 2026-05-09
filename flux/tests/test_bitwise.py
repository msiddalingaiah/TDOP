"""Tests for bitwise operators: & | ^ << >>"""
import pytest
from flux.core.compiler import compile_and_run
from flux.core.parser   import parse_expr
from flux.core.tree     import And, Or, Xor, Shl, Shr, Const, Arg


class TestParser:
    def test_and(self):  assert parse_expr("(& 3 5)")        == And(Const(3), Const(5))
    def test_or(self):   assert parse_expr("(| 3 5)")        == Or (Const(3), Const(5))
    def test_xor(self):  assert parse_expr("(^ 3 5)")        == Xor(Const(3), Const(5))
    def test_shl(self):  assert parse_expr("(<< a 2)", args=["a"]) == Shl(Arg(0), Const(2))
    def test_shr(self):  assert parse_expr("(>> a 1)", args=["a"]) == Shr(Arg(0), Const(1))


class TestAnd:
    def test_basic(self):
        assert compile_and_run("(& a b)", a=0xFF, b=0x0F) == 0x0F
        assert compile_and_run("(& a b)", a=0b1010, b=0b1100) == 0b1000

    def test_imm(self):
        assert compile_and_run("(& n 1)", n=42) == 0    # even
        assert compile_and_run("(& n 1)", n=41) == 1    # odd

    def test_mask_high_byte(self):
        assert compile_and_run("(& n 255)", n=0xABCD) == 0xCD

    def test_clear_all(self):
        assert compile_and_run("(& a 0)", a=0xDEADBEEF) == 0


class TestOr:
    def test_basic(self):
        assert compile_and_run("(| a b)", a=0b1010, b=0b0101) == 0b1111
        assert compile_and_run("(| a b)", a=0xFF00, b=0x00FF) == 0xFFFF

    def test_imm(self):
        assert compile_and_run("(| n 1)", n=42) == 43   # set low bit

    def test_set_all(self):
        assert compile_and_run("(| a 0)", a=0xABC) == 0xABC


class TestXor:
    def test_basic(self):
        assert compile_and_run("(^ a b)", a=0b1010, b=0b1100) == 0b0110

    def test_imm(self):
        assert compile_and_run("(^ n 1)", n=42) == 43   # toggle low bit
        assert compile_and_run("(^ n 1)", n=43) == 42

    def test_self_clears(self):
        assert compile_and_run("(^ a a)", a=0xDEAD) == 0

    def test_swap_trick(self):
        # XOR swap: a ^= b; b ^= a; a ^= b
        assert compile_and_run("""
            (var a x
              (var b y
                (set! a (^ a b))
                (set! b (^ b a))
                (set! a (^ a b))
                a))
        """, x=3, y=7) == 7


class TestShl:
    def test_imm(self):
        assert compile_and_run("(<< n 1)", n=1)  == 2
        assert compile_and_run("(<< n 3)", n=1)  == 8
        assert compile_and_run("(<< n 4)", n=3)  == 48

    def test_multiply_by_power_of_two(self):
        assert compile_and_run("(<< a 1)", a=21) == 42

    def test_reg_count(self):
        assert compile_and_run("(<< a b)", a=1, b=6)  == 64
        assert compile_and_run("(<< a b)", a=3, b=4)  == 48

    def test_zero_shift(self):
        assert compile_and_run("(<< n 0)", n=42) == 42


class TestShr:
    def test_imm(self):
        assert compile_and_run("(>> n 1)", n=84)  == 42
        assert compile_and_run("(>> n 2)", n=168) == 42

    def test_divide_by_power_of_two(self):
        assert compile_and_run("(>> a 1)", a=84) == 42

    def test_reg_count(self):
        assert compile_and_run("(>> a b)", a=168, b=2) == 42

    def test_sign_preserving(self):
        # Arithmetic right shift preserves sign (SAR)
        assert compile_and_run("(>> n 1)", n=-2)  == -1
        assert compile_and_run("(>> n 2)", n=-8)  == -2

    def test_zero_shift(self):
        assert compile_and_run("(>> n 0)", n=42) == 42


class TestPractical:

    def test_even_odd_with_and(self):
        even = "(if (= (& n 1) 0) 1 0)"
        assert compile_and_run(even, n=42) == 1
        assert compile_and_run(even, n=41) == 0

    def test_power_of_two_check(self):
        # n is a power of two iff n > 0 and (n & (n-1)) == 0
        is_pow2 = "(if (= (& n (- n 1)) 0) 1 0)"
        assert compile_and_run(is_pow2, n=8)  == 1
        assert compile_and_run(is_pow2, n=16) == 1
        assert compile_and_run(is_pow2, n=0)  == 1   # edge case: 0 & -1 == 0
        assert compile_and_run(is_pow2, n=6)  == 0
        assert compile_and_run(is_pow2, n=7)  == 0

    def test_count_bits(self):
        # Kernighan's bit count: while n != 0: n &= n-1; count++
        popcount = """
            (var n x
              (var count 0
                (while (> n 0)
                  (set! n (& n (- n 1)))
                  (set! count (+ count 1)))
                count))
        """
        assert compile_and_run(popcount, x=0)    == 0
        assert compile_and_run(popcount, x=1)    == 1
        assert compile_and_run(popcount, x=255)  == 8
        assert compile_and_run(popcount, x=0xFF) == 8
        assert compile_and_run(popcount, x=42)   == 3   # 101010

    def test_bit_reversal(self):
        # Reverse the low 8 bits of n
        reverse_byte = """
            (var n (& x 255)
              (var result 0
                (var i 0
                  (while (< i 8)
                    (set! result (| (<< result 1) (& n 1)))
                    (set! n (>> n 1))
                    (set! i (+ i 1)))
                  result)))
        """
        assert compile_and_run(reverse_byte, x=0b10110001) == 0b10001101
        assert compile_and_run(reverse_byte, x=0b00000001) == 0b10000000
