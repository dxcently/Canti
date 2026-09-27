// One finished sound (VxSegStats) -> an event with a schema-exact line, as extractor/vox_extract/classify.py.
// Runs once per sound. Decision order: pop / click (short + impulsive, not a tonal fragment), else a dropped blip;
// mostly unvoiced -> hiss / coughing / laughing / background noise; voiced -> rise / fall / arch / dip / flat
// with excursion, duration, tone, loudness and "sounds like".
// The raw measurements are kept exactly as the reference's raw dict: ROUNDED (round(x, 2) etc.), because several
// later decisions (sounds_like_voiced, speech_cues, the talking-train context, fp1) read the rounded values.
#pragma once
#include "vx_config.h"
#include "vx_lines.h"
#include "vx_segmenter.h"

enum VxLabel { VX_L_RISE, VX_L_FALL, VX_L_ARCH, VX_L_DIP, VX_L_FLAT, VX_L_POP, VX_L_CLICK, VX_L_HISS, VX_L_UNKNOWN };
extern const char *const VX_LABELS[9];

enum { VX_CUE_BROKEN = 1, VX_CUE_FORMANT = 2, VX_CUE_SYLLABLE = 4 };

struct VxRaw {
    int dur_ms, frames;
    double floor_db, level_db, snr_db, voiced_frac, clarity_med, f0_med_hz, onset_flux_db, decay_db, peak_pos,
        energy_iqr_db;
    bool truncated;
    double gate_close_over_floor_db, peak_centroid_hz, centroid_hz, flatness, zcr, lf_ratio, hf_ratio, flux_mean_db,
        centroid_spread_oct;
    int syllable_peaks;
    double syllable_rate_hz, interval_cv;
    int voiced_runs;
    double strong_voiced_frac, voicing_breaks_hz, pitch_rough_st, pitch_resid_std_st, pitch_jumps_hz;
    bool has_shape;                  // the contour fields below are present
    double excursion_st, net_st, hump_st, valley_st, max_st, min_st;
    float contour64[VX_CONTOUR64];   // rounded to 2 decimals
    int n_pitch16;                   // 16, or 0 (the extractor clears it for non-contour labels)
    float pitch16[VX_PITCH16];
    bool has_impulsive;              // impulsive / core_ms / tonal present (not for very short blips? always set)
    bool impulsive, tonal;
    double core_ms;
    bool has_ctx;                    // gap_ms / prev_talky present (voiced path only)
    bool has_gap;
    double gap_ms;
    bool prev_talky;
    bool has_cues;
    int cues;                        // VX_CUE_* bits, in the reference's order
    char why[128];   // longest: "speech cues: " + the three cue names = 85 chars
    float fp[VX_FP_LEN];             // fp1, rounded to 4 decimals (fingerprint.cpp)
};

struct VxEvent {
    int t_start_ms, t_end_ms;        // stream time (the first sample is t = 0)
    int label;                       // VxLabel
    int like;                        // VxLike
    char text[VX_LINE_MAX];
    bool emit, truncated;
    int sound;                       // the sound's id in its stream (1, 2, ...; 0 = not numbered); its hold messages share it
    bool held;                       // a hold start was sent for this sound (vx_hold.h)
    VxRaw raw;
};

struct VxContext {
    bool has_prev;
    double gap_ms;
    bool prev_talky;
};

void vx_classify(const VxSegStats *seg, const VxConfig *cfg, const VxContext *ctx, VxEvent *ev);

// numpy semantics (np.median: middle pair averaged; np.std: population), for vx_hold.cpp. work: n doubles.
double vx_np_median(const double *x, int n, double *work);
double vx_np_std(const double *x, int n);

// Python round(x, nd): correctly rounded, half to even on exact ties.
double vx_py_round(double x, int nd);
