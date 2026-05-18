; =============================================================================
; config.inc - Build configuration
; =============================================================================
; Select the target platform by setting PLATFORM to one of:

PLATFORM_WINDOWS = 1
PLATFORM_BIOS    = 2        ; future: BIOS bootloader (16/32-bit)
PLATFORM_UEFI    = 3        ; future: UEFI bootloader (64-bit)

PLATFORM = PLATFORM_WINDOWS
