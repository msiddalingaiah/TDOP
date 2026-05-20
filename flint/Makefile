# =============================================================================
# Makefile — Flint FORTH
#
# Targets:
#   make              build flint.exe (Windows, default)
#   make windows      build flint.exe
#   make linux        build flint     (Linux ELF64 — stub implementation)
#   make bare         build flint.bin (raw binary — stub implementation)
#   make clean        remove build outputs
#   make run          build and run flint.exe (Windows)
#
# Requires: fasm (https://flatassembler.net) on PATH
# =============================================================================

FASM    := fasm
SRC     := flint.asm

# --- Windows (primary) -------------------------------------------------------
.PHONY: windows
windows: flint.exe

flint.exe: $(SRC) config.inc macros.inc \
           platform/detect.inc platform/windows.inc \
           primitives.inc dict.inc boot.inc
	$(FASM) -d TARGET=windows $(SRC) $@

# --- Linux (stub) ------------------------------------------------------------
.PHONY: linux
linux: flint

flint: $(SRC) config.inc macros.inc \
       platform/detect.inc platform/linux.inc \
       primitives.inc dict.inc boot.inc
	$(FASM) -d TARGET=linux $(SRC) $@

# --- Bare metal (stub) -------------------------------------------------------
.PHONY: bare
bare: flint.bin

flint.bin: $(SRC) config.inc macros.inc \
           platform/detect.inc platform/bare.inc \
           primitives.inc dict.inc boot.inc
	$(FASM) -d TARGET=bare $(SRC) $@

# --- Default -----------------------------------------------------------------
.DEFAULT_GOAL := windows

# --- Run (Windows) -----------------------------------------------------------
.PHONY: run
run: flint.exe
	./flint.exe

# --- Clean -------------------------------------------------------------------
.PHONY: clean
clean:
	$(RM) flint.exe flint flint.bin
