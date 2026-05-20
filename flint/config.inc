; =============================================================================
; config.inc — compile-time constants for Flint
; =============================================================================

CELL            = 8         ; cell size in bytes (64-bit)
CELL_SHIFT      = 3         ; log2(CELL)

; --- word header flags -------------------------------------------------------
F_IMMED         = 0x80      ; immediate word — executed even in compile mode
F_HIDDEN        = 0x20      ; hidden from dictionary search (smudge bit)
F_LENMASK       = 0x1F      ; name length mask (max 31 characters)

; --- memory arena layout (sizes) --------------------------------------------
DSTACK_SIZE     = 65536     ; data stack:   64 KB
RSTACK_SIZE     = 65536     ; return stack: 64 KB  (for >R / R>)
DICT_SIZE       = 1048576   ; dictionary:    1 MB

ARENA_SIZE      = DSTACK_SIZE + RSTACK_SIZE + DICT_SIZE

; --- input / word buffer sizes -----------------------------------------------
IBUF_SIZE       = 512       ; input line buffer
WBUF_SIZE       = 64        ; parsed word buffer (max word name = 31 + headroom)
