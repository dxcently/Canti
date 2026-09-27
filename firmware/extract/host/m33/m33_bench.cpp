// Instruction-count estimate of the extractor on a Cortex-M33 (the RP2350's core) under QEMU:
//   qemu-system-arm -M mps2-an505 -icount shift=0 -semihosting -nographic -kernel m33_bench.elf
// -icount shift=0 advances the virtual clock 1 ns per instruction, and SysTick runs from that clock, so SysTick
// ticks measure instructions (calibrated below against a loop of known length). Built with the Pico's flags
// (-mcpu=cortex-m33 -mfloat-abi=hard -mfpu=fpv5-sp-d16, -Os). Doubles here are libgcc soft-float, slower than the
// RP2350's double coprocessor that arduino-pico uses, so the sound-end (classify) numbers are upper bounds.
// Instructions are not cycles: on the M33 most take 1 cycle, loads/branches/FP divides more; see README.md.
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include "vox_extract.h"

#define SYST_CSR (*(volatile uint32_t *)0xE000E010)
#define SYST_RVR (*(volatile uint32_t *)0xE000E014)
#define SYST_CVR (*(volatile uint32_t *)0xE000E018)
#define CPACR (*(volatile uint32_t *)0xE000ED88)

extern "C" int main();
extern "C" void initialise_monitor_handles();
extern "C" void __libc_init_array();
extern "C" char __bss_start__[], __bss_end__[];
extern "C" void _init() {}
extern "C" void _fini() {}
extern "C" void c_start() {
    memset(__bss_start__, 0, __bss_end__ - __bss_start__);
    initialise_monitor_handles();   // newlib rdimon: stdio and files through semihosting
    __libc_init_array();
    exit(main());
}
static volatile uint32_t s_wraps;
extern "C" void systick_handler() { s_wraps++; }
extern "C" void default_handler() { for (;;) {} }
extern "C" __attribute__((naked)) void reset_handler() {
    __asm volatile("ldr r0, =0xE000ED88\n ldr r1, [r0]\n orr r1, r1, #(0xF << 20)\n str r1, [r0]\n dsb\n isb\n"
                   "ldr r0, =__StackTop\n mov sp, r0\n b c_start\n");
}
extern "C" uint32_t __StackTop;
__attribute__((section(".vectors"), used)) static void (*const s_vectors[16])() = {
    (void (*)())&__StackTop, reset_handler, default_handler, default_handler, default_handler, default_handler,
    default_handler, 0, 0, 0, 0, default_handler, default_handler, 0, default_handler, systick_handler};

static uint32_t ticks() {   // free-running, 24-bit SysTick extended by its wrap count
    uint32_t w, c;
    do {
        w = s_wraps;
        c = SYST_CVR;
    } while (w != s_wraps);
    return (w << 24) + (0xFFFFFFu - c);
}

static uint64_t s_prof[16];
static uint32_t s_prof_last;
static int s_prof_prev = -1;
// time between consecutive marks, charged to the section that starts at the earlier mark
extern "C" void vx_prof_mark(int where) {
    uint32_t t = ticks();
    if (s_prof_prev >= 0 && where != 0) s_prof[s_prof_prev] += t - s_prof_last;
    s_prof_prev = where;
    s_prof_last = ticks();
}
static const char *const PROF_NAMES[] = {"energy+zcr+window", "fft512", "centroid/flatness(log)", "flux(log10)",
                                         "acf fft1024", "acf ifft1024", "nsdf+peaks", "mel/fp sums+slide", ""};

static VxExtractor s_ex;
static int s_events;
static void on_event(const VxEvent *ev, void *) { s_events++; }
static vx_real s_x[1600];
static int16_t s_pcm[1600];

int main() {
    SYST_RVR = 0xFFFFFF;
    SYST_CVR = 0;
    SYST_CSR = 7;   // processor clock, interrupt, enable
    while (SYST_CVR == 0) {}   // the first reload
    // calibration: 4,000,000 iterations of a 3-instruction loop (subs, bne + the nop) = 12,000,000 instructions
    uint32_t t0 = ticks();
    __asm volatile("ldr r0, =4000000\n1: nop\n subs r0, r0, #1\n bne 1b\n" ::: "r0", "cc");
    uint32_t t1 = ticks();
    double ipt = 12000000.0 / (t1 - t0);   // instructions per tick
    printf("calibration: %.3f instructions per SysTick tick\n", ipt);
    static const char *const cases[] = {"silence", "rise_20db", "talk_20db", "music_20db", "click_pop_30db",
                                        "fan_motor_20db", "rise_10db_cafe", "laugh_20db", "cough_20db", "hiss_20db",
                                        "flat_20db"};
    for (const char *c : cases) {
        char path[256];
        snprintf(path, sizeof(path), "%s/%s.pcm", VECTORS, c);
        FILE *f = fopen(path, "rb");
        if (!f) {
            printf("cannot open %s\n", path);
            continue;
        }
        vx_extractor_init(&s_ex, NULL, 16000);
        s_ex.cycles = ticks;
        s_events = 0;
        size_t n;
        uint32_t t_all = ticks();
        while ((n = fread(s_pcm, 2, 1600, f)) > 0) {
            for (size_t i = 0; i < n; i++) s_x[i] = (vx_real)s_pcm[i] * VXF(1.0 / 32768.0);
            vx_extractor_push(&s_ex, s_x, (int)n, on_event, NULL);
        }
        vx_extractor_flush(&s_ex, on_event, NULL);
        fclose(f);
        (void)t_all;
        const VxStats &st = s_ex.stats;
#ifdef VX_PROFILE
        if (!strcmp(c, "silence") || !strcmp(c, "talk_20db")) {
            printf("  per hop:");
            for (int i = 0; i < 9; i++)
                if (PROF_NAMES[i][0]) printf(" %s %.0f,", PROF_NAMES[i], s_prof[i] * ipt / st.hops);
            printf("\n");
        }
        memset(s_prof, 0, sizeof(s_prof));
#endif
        printf("%-16s hops %5lu  hop mean %7.0f  hop max %7.0f  sound end max %8.0f instructions  (%d sounds); hold test mean %6.0f max %7.0f\n", c,
               (unsigned long)st.hops, (double)st.hop_sum / st.hops * ipt, st.hop_max * ipt, st.seg_max * ipt,
               s_events, (double)st.hold_sum / st.hops * ipt, st.hold_max * ipt);
    }
    return 0;
}
