# clisp — Flat Assembler build
#
# Usage:
#   make          build lisp.exe
#   make clean    remove lisp.exe
#
# Requires FASM on PATH.
# Works with GNU make (MSYS2 / Git Bash) and nmake.
# For cmd.exe native clean: del lisp.exe

ASM    = fasm
TARGET = lisp.exe

SRCS = main.asm                \
       config.inc              \
       defs.inc                \
       platform/interface.inc  \
       platform/windows.asm    \
       tokenizer.asm           \
       memory.asm              \
       parser.asm              \
       printer.asm             \
       env.asm                 \
       eval.asm                \
       primitives.asm

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(SRCS)
	$(ASM) main.asm $(TARGET)

clean:
	-rm -f $(TARGET)
