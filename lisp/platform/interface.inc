; =============================================================================
; platform/interface.inc - HAL (Hardware Abstraction Layer) Contract
;
; This file defines the interface that every platform implementation must
; satisfy. It contains no executable code — only documentation and constants.
;
; To add a new platform:
;   1. Create platform/<name>.asm
;   2. Implement every procedure listed below with the exact signatures
;   3. Add a PLATFORM_<NAME> constant to config.inc
;   4. Add an 'if' branch in main.asm to include it
; =============================================================================

; =============================================================================
; Calling Convention (HAL-internal)
;
;   Arguments:   rcx, rdx, r8, r9  (first four; mirrors Windows x64 ABI)
;   Return:      rax  (or al for single-byte values)
;   Clobbered:   rax, rcx, rdx, r8, r9, r10, r11
;   Preserved:   rbx, rbp, rsi, rdi, r12-r15
;   Stack:       must be 16-byte aligned on entry to every HAL procedure
;
; Using the Windows register layout as our baseline keeps the Windows
; implementation simple, and costs nothing on other targets.
; =============================================================================

; =============================================================================
; Procedures
;
; hal_init
;   One-time platform initialisation. Must be the first HAL call made.
;   In:  (none)
;   Out: (none)
;
; hal_write_char
;   Write one ASCII byte to the output device.
;   In:  cl  = character
;   Out: (none)
;
; hal_write_string
;   Write a byte string to the output device.
;   In:  rcx = pointer to bytes
;        rdx = length in bytes
;   Out: (none)
;
; hal_read_char
;   Block until one byte is available from the input device.
;   In:  (none)
;   Out: al  = byte read
;
; hal_alloc
;   Allocate a zeroed block of memory. Returns NULL (0) on failure.
;   In:  rcx = size in bytes
;   Out: rax = pointer to block, or 0 on failure
;
; hal_exit
;   Terminate the program. Does not return.
;   In:  rcx = exit code (0 = success)
; =============================================================================
