from __future__ import annotations
import re
import sys

from flux.core.parser   import _tokenize
from flux.core.compiler import compile_and_run, compile_expr


BANNER = """\
┌─────────────────────────────────────────┐
│  Flux  ·  native code from S-expressions │
└─────────────────────────────────────────┘
  operators : +  -  *
  type 'help' for commands, 'quit' to exit
"""

HELP = """
  Expressions
  ───────────
  (+ a b)              arithmetic  ( +  -  * )
  (+ (* x 3) (- y 1))  nested expressions
  _                    last result

  Bindings
  ────────
  (def x 42)           bind x to an integer
  (def y (* x 2))      bind y to an expression

  Commands
  ────────
  :vars                show all bindings
  :clear               clear all bindings
  :ir                  show linear IR for last expression
  help                 show this message
  quit  /  exit        exit
"""

_VALID_NAME = re.compile(r'^[a-zA-Z_]\w*$')


class FluxRepl:
    """Interactive REPL for the Flux compiler backend."""

    def __init__(self) -> None:
        self.bindings: dict[str, int] = {}
        self._last_fn = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self) -> None:
        print(BANNER)
        while True:
            try:
                line = input("flux> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye.")
                break
            if not line:
                continue
            self._eval(line)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _eval(self, line: str) -> None:
        match line:
            case "quit" | "exit":
                print("Bye.")
                raise SystemExit(0)
            case "help":
                print(HELP)
            case ":vars":
                self._show_vars()
            case ":clear":
                self.bindings.clear()
                print("Bindings cleared.")
            case ":ir":
                if self._last_fn is None:
                    print("Nothing compiled yet.")
                else:
                    print(repr(self._last_fn))
            case _ if self._is_def(line):
                self._handle_def(line)
            case _:
                self._run_expr(line)

    # ------------------------------------------------------------------
    # Variable scanning
    # ------------------------------------------------------------------

    def _used_bindings(self, expr_str: str) -> dict[str, int]:
        """Return only the bindings whose names appear in *expr_str*,
        in the order they first appear as tokens.  This prevents unused
        variables (including the implicit ``_``) from becoming spurious
        function parameters.
        """
        seen:   set[str]  = set()
        result: dict[str, int] = {}
        for token in _tokenize(expr_str):
            if token in self.bindings and token not in seen:
                seen.add(token)
                result[token] = self.bindings[token]
        return result

    # ------------------------------------------------------------------
    # (def name expr)
    # ------------------------------------------------------------------

    def _is_def(self, line: str) -> bool:
        tokens = _tokenize(line)
        return (len(tokens) >= 4
                and tokens[0] == "("
                and tokens[1] == "def")

    def _handle_def(self, line: str) -> None:
        tokens = _tokenize(line)
        # Expected shape: ( def name value... )
        if len(tokens) < 5:
            print("Usage: (def name expr)")
            return

        name = tokens[2]
        if not _VALID_NAME.match(name):
            print(f"Error: '{name}' is not a valid name")
            return

        # Reconstruct the value expression from the remaining tokens.
        # Joining with spaces is safe because our tokenizer splits on
        # whitespace and parentheses, so the round-trip is lossless.
        value_str = " ".join(tokens[3:-1])
        if not value_str:
            print("Error: (def name expr) — missing expression")
            return

        try:
            used         = self._used_bindings(value_str)
            fn, code     = compile_expr(value_str, **used)
            result       = self._execute(code, used)
        except Exception as e:
            print(f"Error: {e}")
            return

        self._last_fn        = fn
        self.bindings[name]  = result
        self.bindings["_"]   = result
        print(f"{name} = {result}")

    # ------------------------------------------------------------------
    # Execution helper
    # ------------------------------------------------------------------

    def _execute(self, code: bytes, used: dict[str, int]) -> int:
        """Run *code* in memory, passing the values from *used* as arguments."""
        import ctypes
        from flux.core.jit import make_callable, free_code
        arg_values   = list(used.values())
        argtypes     = [ctypes.c_int64] * len(arg_values)
        func, handle = make_callable(code, ctypes.c_int64, *argtypes)
        value        = func(*arg_values)
        free_code(handle)
        return value

    # ------------------------------------------------------------------
    # Expression evaluation
    # ------------------------------------------------------------------

    def _run_expr(self, expr_str: str) -> None:
        try:
            used         = self._used_bindings(expr_str)
            fn, code     = compile_expr(expr_str, **used)
        except Exception as e:
            print(f"Error: {e}")
            return

        try:
            result = self._execute(code, used)
        except Exception as e:
            print(f"Error: {e}")
            return

        self._last_fn          = fn
        self.bindings["_"]     = result
        print(result)

    # ------------------------------------------------------------------
    # :vars
    # ------------------------------------------------------------------

    def _show_vars(self) -> None:
        user_vars = {k: v for k, v in self.bindings.items() if k != "_"}
        if not user_vars and "_" not in self.bindings:
            print("  (no bindings)")
            return
        for name, value in user_vars.items():
            print(f"  {name} = {value}")
        if "_" in self.bindings:
            print(f"  _ = {self.bindings['_']}")
