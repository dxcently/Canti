// VOX extractor, C++ port: number types.
//
// vx_real  per-frame DSP (FFT, spectra, MPM pitch, per-frame arrays). float32 by default: the RP2350's Cortex-M33
//          has a single-precision FPU only. Build with -DVX_REAL_DOUBLE to run the same code in double, which is
//          how the host check separates porting bugs (double must match the Python reference to ~1e-9) from
//          float32 rounding (see firmware/README.md "Extractor").
// vx_acc   the few per-hop scalar accumulators where float32 cancels badly (noise-floor block sums of dB and dB^2,
//          the segment's energy-weighted sums). double by default: a handful of soft-double operations per hop.
//          -DVX_ACC_FLOAT makes them float32 too.
// Per-sound work (classify.cpp, fingerprint.cpp) uses double: it runs once per sound, compares against thresholds
// and against values the reference rounds (round(x, 3) etc.), exactly like the float64 Python.
#pragma once
#include <math.h>
#include <stdint.h>

#ifdef VX_REAL_DOUBLE
typedef double vx_real;
#define VX_LOG10 log10
#define VX_LOG log
#define VX_LOG2 log2
#define VX_EXP exp
#define VX_POW pow
#define VX_SQRT sqrt
#define VX_FLOOR floor
#define VXF(x) (x)
#else
typedef float vx_real;
#define VX_LOG10 log10f
#define VX_LOG logf
#define VX_LOG2 log2f
#define VX_EXP expf
#define VX_POW powf
#define VX_SQRT sqrtf
#define VX_FLOOR floorf
#define VXF(x) (x##f)
#endif

#if defined(VX_ACC_FLOAT) && !defined(VX_REAL_DOUBLE)
typedef float vx_acc;
#else
typedef double vx_acc;
#endif

// Compile-time capacities (fixed buffers; nothing is allocated after init). vx_config_check() rejects a Config
// that does not fit.
#define VX_MAX_WIN 512           // analysis window (power of two)
#define VX_MAX_ACF 1024          // MPM autocorrelation FFT (power of two, >= win + tau_max)
#define VX_MAX_HOP 512
#define VX_MAX_SEG 400           // max_segment_frames
#define VX_MAX_HANG 64           // hangover_frames
#define VX_MAX_OPEN 16           // open_frames
#define VX_MAX_BLOCKS 32         // floor_blocks
#define VX_MAX_SUB 128           // floor_block_frames / floor_startup_sub_frames (+1)
#define VX_PREROLL 3             // segmenter.PREROLL
#define VX_ONSET_FRAMES 3        // SegmentStats.ONSET_FRAMES
#define VX_N_MEL 8
#define VX_FP_LEN 24
#define VX_PITCH16 16
#define VX_CONTOUR64 64

// Profiling marks (extract/host/m33/m33_bench.cpp builds with -DVX_PROFILE); nothing otherwise.
#ifdef VX_PROFILE
extern "C" void vx_prof_mark(int where);
#define VX_PROF(i) vx_prof_mark(i)
#else
#define VX_PROF(i) ((void)0)
#endif
