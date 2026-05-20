; =============================================================================
; platform/detect.inc -- select and include the platform implementation
;
; Build with:
;   fasm -d TARGET=windows  flint.asm  flint.exe      (default)
;   fasm -d TARGET=linux    flint.asm  flint
;   fasm -d TARGET=bare     flint.asm  flint.bin
;
; Note: -d TARGET=windows defines TARGET as the bare token `windows`, not the
; string literal 'windows'.  Comparisons must use unquoted tokens to match.
; =============================================================================

if ~ defined TARGET
    TARGET equ windows
end if

if TARGET eq windows
    include 'windows.inc'
else if TARGET eq linux
    include 'linux.inc'
else if TARGET eq bare
    include 'bare.inc'
else
    err 'Unknown TARGET - valid values: windows  linux  bare'
end if
