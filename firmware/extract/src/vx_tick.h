// Joystick ticks, as extractor/joystick_core.py Analyzer (the voice joystick's per-tick analysis,
// wiki/voice-cursor.md "Joystick cursor"): 16 kHz samples in, one VxTickOut per 20 ms (320 samples) on the newest
// 512-sample window: pitch (voice_cursor_v2's MPM: the first NSDF peak within mpm_k of the highest), clarity, level
// and the non-periodic floor (10th percentile over 5 s), F1/F2 (order-18 LPC roots with the broad-F2 rule) and the
// streaming F2 continuity filter. Independent of the extractor's own front end (its own 70 Hz high-pass, window,
// NSDF): VxExtractor feeds it the same 16 kHz samples when ex->tick is set (vx_extractor.h), so the phone mic and
// later the Pico can stream it. Fixed memory (about 10 KB), no allocation. Per-tick DSP in double except the
// autocorrelation FFT (vx_real, the shared vx_fft scratch: not reentrant, same thread as the extractor).
#pragma once
#include "vx_real.h"

#define VX_TICK_WIN 512
#define VX_TICK_MAX_LEVELS 256
#define VX_TICK_MAX_ORDER 24
#define VX_TICK_MAX_RUN 16

enum { VX_TICK_WHY_NONE = 0, VX_TICK_WHY_QUIET = 1, VX_TICK_WHY_UNCLEAR = 2, VX_TICK_WHY_NO_PITCH = 3 };

struct VxTickOut {
    double t_ms;       // samples consumed * 1000 / fs (the end of the window)
    double f0;         // Hz, 0 unless voiced
    double f0_raw;     // the pitch before the voicing gate (0 = none)
    double clarity;
    double db;         // level of the high-passed window
    double floor_db;   // the floor this tick was judged against (before its own level was added)
    double f1, f2;     // Hz, NAN = none
    bool voiced;
    int why;           // VX_TICK_WHY_*
};

struct VxTickConfig {
    int fs, win, hop;                      // 16000, 512, 320 (tick_ms 20)
    double hpf_hz;                         // 70
    double f0_min_hz, f0_max_hz, mpm_k;    // 60, 1100, 0.88
    double clarity_on;                     // 0.8 (voicing.clarity_min; the person's own after the setup)
    double level_over_floor_db;            // 6
    int floor_ticks;                       // floor_window_s / tick = 250
    double floor_pct;                      // 10
    int lpc_order;                         // 18
    double preemph;                        // 0.97
    double f1_lo, f1_hi, f2_lo, f2_hi;     // 200, 1100, 600, 3600
    double f2_min_gap_hz, max_bw_hz, f2_max_bw_hz;   // 150, 500, 1000
    double f2_jump_hz;                     // 500 (0 = no continuity filter)
    int f2_jump_frames;                    // 5
};

struct VxTick {
    VxTickConfig cfg;
    double b0, b1, b2, a1, a2, z1, z2;     // high-pass (transposed direct form II, as scipy lfilter)
    double buf[VX_TICK_WIN];               // newest win high-passed samples, oldest first
    int fill;                              // samples of the current hop so far
    uint64_t n;                            // samples consumed
    double hamming[VX_TICK_WIN];
    // floor: the levels of the last floor_ticks non-periodic ticks (ring in arrival order + the same values sorted)
    double lv_ring[VX_TICK_MAX_LEVELS];
    double lv_sorted[VX_TICK_MAX_LEVELS];
    int lv_n, lv_head;
    // F2 continuity
    double f2_last;
    int f2_since, run_n;
    double run[VX_TICK_MAX_RUN];
    double hopbuf[VX_TICK_WIN];            // the current hop so far
    // scratch (kept off the stack: the Pico core-1 stack is small)
    double s_a[VX_TICK_WIN], s_b[VX_TICK_WIN], s_c[VX_TICK_WIN];
    vx_real x[VX_TICK_WIN];
    vx_real acf_p[VX_TICK_WIN + 1];
    vx_real r[VX_TICK_WIN];
};

void vx_tick_config_default(VxTickConfig *c);
// NULL = defaults. Returns NULL, or why the config does not fit.
const char *vx_tick_init(VxTick *t, const VxTickConfig *c);
void vx_tick_reset(VxTick *t);            // a new stream (the config and clarity_on kept)
// One 16 kHz sample in; true when a tick is out (written to *out).
bool vx_tick_push(VxTick *t, vx_real x, VxTickOut *out);
const char *vx_tick_why_name(int why);

// Exposed for tests: MPM of one mean-removed frame (f0 Hz or 0, clarity), and (F1, F2) of one frame (false = none).
double vx_tick_nsdf_f0(VxTick *t, const double *x, int n, double *clarity);
bool vx_tick_formants(VxTick *t, const double *x, int n, double *f1, double *f2);
