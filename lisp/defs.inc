; =============================================================================
; defs.inc - Shared constants and struct layouts
; =============================================================================

; ── Token types ──────────────────────────────────────────────────────────────

TOK_EOF    = 0      ; end of input
TOK_LPAREN = 1      ; (
TOK_RPAREN = 2      ; )
TOK_ATOM   = 3      ; symbol or number: foo, bar, 42, +, nil, true ...
TOK_STRING = 4      ; "..." (reserved for later)

; ── Token struct field offsets ────────────────────────────────────────────────
;
;   struct Token {
;       type  : qword   ; TOK_* constant
;       start : qword   ; pointer to text (TOK_ATOM only)
;       len   : qword   ; byte length    (TOK_ATOM only)
;   }

TOK.type  = 0
TOK.start = 8
TOK.len   = 16
TOK_SIZE  = 24

; ── Value tags ────────────────────────────────────────────────────────────────

TAG_NIL     = 0
TAG_BOOL    = 1
TAG_INT     = 2
TAG_SYM     = 3
TAG_CONS    = 4
TAG_PRIM    = 5     ; built-in function   — Cell.val = function pointer
TAG_CLOSURE = 6     ; lambda + captured env — Cell.val = Closure*

; ── Cell (uniform tagged value, 16 bytes) ─────────────────────────────────────
;
;   struct Cell {
;       tag : qword     ; TAG_* constant
;       val : qword     ; integer value, or pointer (SymData*, Cons*)
;   }

Cell.tag  = 0
Cell.val  = 8
CELL_SIZE = 16

; ── Cons (pair of Cell pointers, 16 bytes) ────────────────────────────────────
;
;   struct Cons {
;       car : qword     ; pointer to Cell (head)
;       cdr : qword     ; pointer to Cell (tail / rest)
;   }

Cons.car  = 0
Cons.cdr  = 8
CONS_SIZE = 16

; ── Closure (lambda + captured environment) ──────────────────────────────────
;
;   struct Closure {
;       params : qword   ; Cell* — list of parameter symbol Cells
;       body   : qword   ; Cell* — single body expression
;       env    : qword   ; Cell* — lexically captured environment alist
;   }

Closure.params = 0
Closure.body   = 8
Closure.env    = 16
CLOSURE_SIZE   = 24
;
;   struct SymData {
;       len   : qword           ; byte count (not including null terminator)
;       chars : byte[len+1]     ; null-terminated UTF-8 string
;   }
;
;   Allocate with: hal_alloc(SYMDATA_HDR + len + 1)

SymData.len   = 0
SymData.chars = 8
SYMDATA_HDR   = 8
