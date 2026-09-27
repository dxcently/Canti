// Config: every threshold of the extractor, field for field with extractor/vox_extract/config.py (same names,
// same order, same defaults). Integers are int, real numbers double (thresholds are compared once per sound
// against double values, as in the reference); the per-hop code keeps float copies. loud_calib_db is optional
// (None in Python): has_loud_calib_db says whether it is set.
// tools/check_extract.sh compares vx_config_json() of the defaults with Python's Config().to_json().
#pragma once
#include <stddef.h>
#include "vx_real.h"

// X(name, default) for each field, in config.py order.
#define VX_CONFIG_FIELDS(VX_I, VX_R, VX_O) \
    VX_I(sample_rate, 16000) \
    VX_I(hop, 160) \
    VX_I(win, 512) \
    VX_I(acf_fft, 1024) \
    VX_R(hpf_hz, 60.0) \
    VX_R(spec_lo_hz, 90.0) \
    VX_R(spec_hi_hz, 7600.0) \
    VX_R(lf_split_hz, 1000.0) \
    VX_R(hf_split_hz, 3500.0) \
    VX_R(flux_floor_db, -95.0) \
    VX_R(f0_min_hz, 75.0) \
    VX_R(f0_max_hz, 2600.0) \
    VX_R(mpm_k, 0.88) \
    VX_R(voiced_clarity, 0.6) \
    VX_R(voiced_min_db_over_floor, 6.0) \
    VX_I(floor_block_frames, 40) \
    VX_I(floor_blocks, 8) \
    VX_R(floor_bias_db, 0.0) \
    VX_R(floor_min_db, -85.0) \
    VX_I(warmup_frames, 25) \
    VX_I(floor_startup_blocks, 2) \
    VX_I(floor_startup_sub_frames, 5) \
    VX_R(floor_startup_pct, 0.25) \
    VX_R(floor_startup_keep_db, 3.0) \
    VX_R(floor_startup_trigger_db, 10.0) \
    VX_R(floor_rise_open_db_s, 3.0) \
    VX_R(gate_open_db, 9.0) \
    VX_R(gate_close_db, 5.0) \
    VX_R(gate_open_sigma, 2.5) \
    VX_R(gate_close_sigma, 1.5) \
    VX_I(open_frames, 1) \
    VX_I(hangover_frames, 10) \
    VX_I(max_segment_frames, 400) \
    VX_I(min_segment_frames, 1) \
    VX_I(median_frames, 5) \
    VX_R(jump_limit_st, 7.0) \
    VX_R(contour_db, 12.0) \
    VX_I(edge_frames, 5) \
    VX_I(smooth_frames, 5) \
    VX_R(flat_max_range_st, 1.5) \
    VX_R(shape_min_st, 1.0) \
    VX_R(arch_ratio, 1.0) \
    VX_R(exc_medium_st, 2.0) \
    VX_R(exc_large_st, 4.0) \
    VX_I(dur_short_ms, 150) \
    VX_I(dur_medium_ms, 400) \
    VX_I(dur_long_ms, 1000) \
    VX_R(tone_clear, 0.8) \
    VX_R(tone_breathy, 0.6) \
    VX_R(tone_min_voiced_frac, 0.5) \
    VX_R(loud_quiet_over_floor_db, 18.0) \
    VX_R(loud_loud_over_floor_db, 40.0) \
    VX_R(loud_ref_min_db, -80.0) \
    VX_O(loud_calib_db) \
    VX_R(loud_calib_span_db, 8.0) \
    VX_I(discrete_max_ms, 200) \
    VX_I(discrete_core_ms, 60) \
    VX_R(discrete_core_db, 15.0) \
    VX_I(discrete_max_voiced, 4) \
    VX_R(discrete_peak_pos, 0.4) \
    VX_R(pop_onset_flux_db, 6.0) \
    VX_I(pop_attack_frames, 3) \
    VX_R(click_centroid_hz, 1800.0) \
    VX_R(discrete_tonal_voiced_frac, 0.5) \
    VX_R(discrete_tonal_clarity, 0.8) \
    VX_I(hiss_min_ms, 100) \
    VX_R(hiss_max_voiced_frac, 0.25) \
    VX_R(hiss_centroid_hz, 2200.0) \
    VX_R(hiss_zcr, 0.18) \
    VX_R(hiss_bg_lf_ratio, 0.2) \
    VX_I(hiss_bg_steady_ms, 1500) \
    VX_R(hiss_steady_db, 3.0) \
    VX_R(whistle_min_hz, 600.0) \
    VX_R(syllable_prominence_db, 6.0) \
    VX_I(syllable_min_gap_frames, 8) \
    VX_I(talk_min_cues, 2) \
    VX_R(talk_max_voiced_frac, 0.85) \
    VX_I(talk_min_runs, 3) \
    VX_R(talk_centroid_spread_oct, 0.45) \
    VX_R(talk_strong_centroid_spread_oct, 0.7) \
    VX_I(talk_min_peaks, 2) \
    VX_R(talk_min_rate_hz, 2.0) \
    VX_R(talk_max_rate_hz, 9.0) \
    VX_R(talk_min_iqr_db, 8.0) \
    VX_I(train_gap_ms, 300) \
    VX_I(train_max_ms, 400) \
    VX_I(laugh_min_peaks, 3) \
    VX_R(laugh_rate_lo_hz, 3.0) \
    VX_R(laugh_rate_hi_hz, 8.0) \
    VX_R(laugh_max_interval_cv, 0.3) \
    VX_R(laugh_max_clarity, 0.88) \
    VX_R(cough_onset_flux_db, 5.0) \
    VX_R(cough_max_voiced_frac, 0.6) \
    VX_R(cough_decay_db, 10.0) \
    VX_R(cough_peak_pos, 0.35) \
    VX_I(cough_max_ms, 900) \
    VX_I(music_min_ms, 900) \
    VX_R(music_max_clarity, 0.9) \
    VX_R(music_max_flatness, 0.12) \
    VX_R(music_min_jumps_hz, 0.8) \
    VX_R(machine_max_pitch_std_st, 0.04) \
    VX_I(machine_min_ms, 900) \
    VX_I(max_gesture_ms, 3000) \
    VX_I(hold_start_ms, 300) \
    VX_R(hold_min_voiced_frac, 0.8) \
    VX_R(hold_min_clarity, 0.85) \
    VX_R(hold_max_drift_st, 1.0) \
    VX_R(hold_max_mad_st, 0.5) \
    VX_R(hold_flat_st, 1.5) \
    VX_I(hold_pitch_ms, 200) \
    VX_R(hold_pitch_min_voiced_frac, 0.5) \
    VX_I(hold_glide_ms, 250) \
    VX_R(hold_glide_min_st, 2.0) \
    VX_R(hold_glide_peak_st, 1.5) \
    VX_I(hold_glide_quiet_ms, 700) \
    VX_I(hold_glide_delay_ms, 300) \
    VX_I(cooldown_ms, 0) \

struct VxConfig {
#define VX_DECL_I(n, d) int n;
#define VX_DECL_R(n, d) double n;
#define VX_DECL_O(n) bool has_##n; double n;
    VX_CONFIG_FIELDS(VX_DECL_I, VX_DECL_R, VX_DECL_O)
#undef VX_DECL_I
#undef VX_DECL_R
#undef VX_DECL_O
    double frame_ms() const { return 1000.0 * hop / sample_rate; }
};

void vx_config_default(VxConfig *c);
// NULL if the config fits the compiled capacities and is sane, else a reason.
const char *vx_config_check(const VxConfig *c);
// Set one field from a JSON value text ("12", "0.5", "null"); false if the key is unknown or the value bad.
bool vx_config_set(VxConfig *c, const char *key, const char *value);
// Load a flat JSON object {"key": value, ...} (config.json / results/real_tuned_config.json). Unknown keys are
// rejected like Config.from_dict. Returns NULL or an error text (static buffer).
const char *vx_config_load_json(VxConfig *c, const char *json);
// {"sample_rate": 16000, ...} in field order (compact, one line). Returns the length written (snprintf semantics).
size_t vx_config_json(const VxConfig *c, char *out, size_t cap);
