// Real FFT helpers for the front end: a radix-2 complex FFT of n/2 points plus the real-split step.
// Everything the front end needs goes through these two calls, so a CMSIS-DSP (arm_rfft_fast_f32) or other
// backend can replace this file without touching frontend.cpp. arduino-pico 6.1.1 ships no CMSIS-DSP, hence
// this small one. Sizes: powers of two up to VX_MAX_ACF (1024). Twiddles: one table of exp(-2 pi i k / 1024),
// computed once in double by vx_fft_init() (4 KB). Not reentrant: one static work buffer (4 KB).
#pragma once
#include "vx_real.h"

void vx_fft_init();
// p[k] = |X[k]|^2 for k = 0..nfft/2, X = DFT of x[0..n-1] zero-padded to nfft (n <= nfft).
void vx_rfft_power(const vx_real *x, int n, int nfft, vx_real *p);
// Same as numpy irfft(P, nfft)[:nout] for a REAL spectrum P[0..nfft/2] (e.g. a power spectrum): the circular
// autocorrelation when P = |X|^2.
void vx_irfft_real(const vx_real *P, int nfft, vx_real *r, int nout);
