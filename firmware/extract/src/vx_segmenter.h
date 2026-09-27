// Noise floor, gate and per-sound accumulation, as extractor/vox_extract/segmenter.py.
//   VxNoiseFloor  minimum statistics over 0.4 s blocks (ring of the last 8 block means and stds), with the robust
//                 start-up rule (50 ms sub-blocks) for the first 2 blocks
//   VxSegStats    what is kept per sound: e_db / f0 / clarity per frame (<= 400), the first 3 fluxes, and running
//                 energy-weighted sums (plus the fp1 sums)
//   VxSegmenter   the gate: open / close thresholds from floor + spread, pre-roll, hangover, 4 s cap
#pragma once
#include "vx_config.h"
#include "vx_frontend.h"

struct VxSub { vx_acc sum, sq; int n; };

struct VxNoiseFloor {
    const VxConfig *cfg;
    vx_acc block_sum, block_sq;
    int block_n;
    double means[VX_MAX_BLOCKS], stds[VX_MAX_BLOCKS];   // ring, oldest first (n_means entries)
    int n_means;
    long n;
    int blocks;
    VxSub sub[VX_MAX_SUB];
    int n_sub;
    vx_acc sub_sum, sub_sq;
    int sub_n;
};

void vx_floor_reset(VxNoiseFloor *nf, const VxConfig *cfg);
double vx_floor_update(VxNoiseFloor *nf, vx_real e_db);   // returns value()
double vx_floor_value(const VxNoiseFloor *nf);
double vx_floor_spread(const VxNoiseFloor *nf);

struct VxSegStats {
    int32_t start_index;
    double t_start_ms;
    double floor_db;                 // floor when the sound started
    double close_over_floor_db;
    int n;
    vx_real e_db[VX_MAX_SEG], f0[VX_MAX_SEG], clarity[VX_MAX_SEG];
    vx_real flux[VX_ONSET_FRAMES];
    int n_flux;
    vx_real floor_lin;               // 10^(floor_db / 10), for the weights
    vx_acc w_sum, centroid_sum, flatness_sum, zcr_sum, lf_sum, hf_sum, flux_sum;
    vx_acc cent_sum, cent_sq;
    int cent_n;
    vx_acc mel8_sum[VX_N_MEL];
    vx_acc p_band_sum, p_1k6_sum, p_voiced_sum, p_hi35_sum;
    vx_real peak_db, peak_centroid, peak_flatness, peak_zcr;
    bool has_peak;
    bool truncated;
};

double vx_seg_wmean(const VxSegStats *s, vx_acc v);

struct VxSegmenter {
    const VxConfig *cfg;
    VxNoiseFloor floor;
    double floor_db;
    bool open;                       // a sound is open (seg valid)
    VxSegStats seg;
    VxFrame pending[VX_MAX_HANG];    // frames after the last active one (hangover)
    int n_pending;
    VxFrame recent[VX_PREROLL + VX_MAX_OPEN + 1];   // the last PREROLL + open_frames frames while idle
    int n_recent;
    int above;
    int cooldown;
    int fill_frames;
    vx_real open_thr_f, close_thr_f;             // last thresholds used (for stats / debugging)
};

void vx_seg_reset(VxSegmenter *sg, const VxConfig *cfg);
// Feed one frame. Returns true when a sound ended; it is then in sg->seg until the next push.
bool vx_seg_push(VxSegmenter *sg, const VxFrame *f);
// End of stream: close an open sound as if its hangover had run out. True if one was open.
bool vx_seg_flush(VxSegmenter *sg);
