// Front end, as extractor/vox_extract/frontend.py: high-pass biquad, then one Frame per hop (10 ms) from the
// latest win (512) samples. Energy from the central hop, ZCR from the central 2 hops, spectral features from a
// periodic-Hann 512-point FFT, MPM pitch + clarity from a 1024-point FFT autocorrelation of the unwindowed window,
// and the fp1 per-frame sums (8 mel bands, band / 1-6 kHz / pitched / above-3.5-f0 power).
// Frame j describes the window centre: t_ms = 10 j - 11.
#pragma once
#include "vx_config.h"
#include "vx_real.h"

struct VxFrame {
    int32_t index;
    int32_t t_ms;         // integer-valued in the reference (10 j - 11)
    vx_real e_db, zcr, centroid, flatness, flux, lf_ratio, hf_ratio, f0, clarity;
    vx_real mel8[VX_N_MEL];
    vx_real p_band, p_1k6, p_voiced, p_hi35;
};

struct VxFrontend {
    // constants (from the Config at init)
    int n, hop, nfft_acf, sr;
    int k_lo, k_hi, k_lf, k_hf, k_1k, k_6k;
    int tau_min, tau_max;
    vx_real b0, b1, b2, a1, a2;          // high-pass biquad (a0 = 1)
    vx_real win_pow, df, mpm_k, voiced_clarity, flux_floor_db;
    vx_real window[VX_MAX_WIN];
    vx_real freqs[VX_MAX_WIN / 2 + 1];
    // mel filterbank, sparse: band i covers bins mel_k0[i] .. mel_k0[i] + mel_len[i] - 1, weights at mel_w[mel_off[i]..]
    int mel_k0[VX_N_MEL], mel_len[VX_N_MEL], mel_off[VX_N_MEL];
    vx_real mel_w[2 * (VX_MAX_WIN / 2 + 1)];
    // state
    vx_real z1, z2;                       // biquad state (transposed direct form II)
    vx_real buf[VX_MAX_WIN];              // the latest n high-passed samples, oldest first
    int fill;                             // samples of the current hop so far
    int32_t index;
    vx_real floor_init;                   // Config.floor_min_db
    vx_real floor_db;                     // the segmenter's floor after the previous frame (flux floor)
    bool have_prev;
    vx_real prev_lin[VX_MAX_WIN / 2 + 1];  // the previous frame's p + floor_p (flux)
    // scratch
    vx_real p[VX_MAX_WIN / 2 + 1];
    vx_real acf_p[VX_MAX_ACF / 2 + 1];
    vx_real r[VX_MAX_ACF];
    vx_real m[VX_MAX_ACF];
    vx_real wx[VX_MAX_WIN];              // the windowed frame
    bool pitch_enabled;                   // optimisation hook: false skips MPM (f0 = clarity = 0)
};

void vx_frontend_init(VxFrontend *fe, const VxConfig *cfg);
void vx_frontend_reset(VxFrontend *fe);
// High-pass one sample and append it; returns true when a hop is complete (then call vx_frontend_frame).
bool vx_frontend_push(VxFrontend *fe, vx_real x);
void vx_frontend_frame(VxFrontend *fe, VxFrame *f);
// MPM on one window (exposed for tests): returns f0 (0 if none), clarity in *clarity.
vx_real vx_mpm_pitch(VxFrontend *fe, const vx_real *x, vx_real *clarity);
