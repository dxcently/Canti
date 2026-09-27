// Decimator3: 48 kHz -> 16 kHz, as extractor/vox_extract/resample.py. A 63-tap Kaiser low-pass (cutoff 7.2 kHz,
// beta 8, scipy firwin design, taps rounded to float32 as in the reference), evaluated at every 3rd input sample:
// output m = sum_k h[k] x[3m - k], x[<0] = 0. The Pico's mic runs at 16 kHz, so the firmware does not use this;
// it is here for the 48 kHz test vectors and `ext feed ... 48000`.
#pragma once
#include "vx_real.h"

#define VX_DECIM_TAPS 63

struct VxDecim3 {
    vx_real hist[VX_DECIM_TAPS - 1];   // the previous 62 input samples, oldest first
    int phase;                         // index (in the next block) of the next input sample that yields an output
};

const float *vx_decim_taps();          // the 63 taps (float32, like decim_taps())
void vx_decim_reset(VxDecim3 *d);
// Feed n samples; writes the 16 kHz outputs to out (at most n / 3 + 1) and returns how many.
int vx_decim_push(VxDecim3 *d, const vx_real *x, int n, vx_real *out);
