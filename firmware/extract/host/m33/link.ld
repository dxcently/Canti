/* QEMU mps2-an505 (Cortex-M33), secure alias of SSRAM1: everything in RAM, loaded by QEMU from the ELF */
MEMORY { RAM (rwx) : ORIGIN = 0x10000000, LENGTH = 4M }
ENTRY(reset_handler)
SECTIONS {
  .text : { KEEP(*(.vectors)) *(.text*) *(.rodata*) KEEP(*(.init)) KEEP(*(.fini))
            . = ALIGN(4); __preinit_array_start = .; KEEP(*(.preinit_array)) __preinit_array_end = .;
            __init_array_start = .; KEEP(*(SORT(.init_array.*))) KEEP(*(.init_array)) __init_array_end = .;
            __fini_array_start = .; KEEP(*(.fini_array)) __fini_array_end = .; } > RAM
  .ARM.exidx : { *(.ARM.exidx*) } > RAM
  .data : { *(.data*) } > RAM
  .bss (NOLOAD) : { __bss_start__ = .; *(.bss*) *(COMMON) . = ALIGN(8); __bss_end__ = .; } > RAM
  end = .; _end = .;
  __stack = ORIGIN(RAM) + LENGTH(RAM);
  __StackTop = __stack;
}
