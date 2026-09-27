#include "vx_impl.h"
#include "vx_json.h"
#include <stdio.h>
#include <string.h>
#include "vx_fingerprint.h"
#include "vx_vocab.h"

void vx_json_init(VxJson *j, char *buf, size_t cap) {
    j->buf = buf;
    j->cap = cap;
    j->n = 0;
    if (cap) buf[0] = 0;
}

static void put(VxJson *j, const char *s, size_t len) {
    if (j->n + len < j->cap) {
        memcpy(j->buf + j->n, s, len);
        j->buf[j->n + len] = 0;
    } else if (j->n < j->cap) {
        j->buf[j->n] = 0;
    }
    j->n += len;
}

void vx_json_raw(VxJson *j, const char *s) { put(j, s, strlen(s)); }

void vx_json_num(VxJson *j, double v, int decimals) {
    char b[48];
    int len = snprintf(b, sizeof(b), "%.*f", decimals, v);
    if (len <= 0 || len >= (int)sizeof(b)) {
        put(j, "0.0", 3);
        return;
    }
    if (decimals > 0) {   // strip trailing zeros, keep one digit after the point
        while (len > 2 && b[len - 1] == '0' && b[len - 2] != '.') len--;
    } else {
        b[len++] = '.';
        b[len++] = '0';
    }
    put(j, b, (size_t)len);
}

void vx_json_int(VxJson *j, long v) {
    char b[24];
    int len = snprintf(b, sizeof(b), "%ld", v);
    put(j, b, (size_t)len);
}

void vx_json_str(VxJson *j, const char *s) {
    put(j, "\"", 1);
    for (; *s; s++) {
        if (*s == '"' || *s == '\\') put(j, "\\", 1);
        put(j, s, 1);
    }
    put(j, "\"", 1);
}

static void key(VxJson *j, const char *k, bool first = false) {
    if (!first) put(j, ", ", 2);
    vx_json_str(j, k);
    put(j, ": ", 2);
}

static void kb(VxJson *j, const char *k, bool v) {
    key(j, k);
    vx_json_raw(j, v ? "true" : "false");
}
static void kn(VxJson *j, const char *k, double v, int d) {
    key(j, k);
    vx_json_num(j, v, d);
}
static void ki(VxJson *j, const char *k, long v) {
    key(j, k);
    vx_json_int(j, v);
}
static void list(VxJson *j, const float *v, int n, int d) {
    put(j, "[", 1);
    for (int i = 0; i < n; i++) {
        if (i) put(j, ", ", 2);
        vx_json_num(j, v[i], d);
    }
    put(j, "]", 1);
}

static const char *const CUES[3] = {"broken voicing", "consonant / formant changes", "syllable-like loudness"};

void vx_json_event(VxJson *j, const VxEvent *ev, bool with_raw) {
    const VxRaw *r = &ev->raw;
    put(j, "{", 1);
    key(j, "t_start_ms", true);
    vx_json_int(j, ev->t_start_ms);
    ki(j, "t_end_ms", ev->t_end_ms);
    key(j, "label");
    vx_json_str(j, VX_LABELS[ev->label]);
    key(j, "sounds_like");
    vx_json_str(j, VX_SOUNDS_LIKE[ev->like]);
    key(j, "text");
    vx_json_str(j, ev->text);
    kb(j, "emit", ev->emit);
    kb(j, "truncated", ev->truncated);
    if (ev->sound) ki(j, "sound", ev->sound);   // Event.to_dict order: after truncated, before raw
    if (ev->held) kb(j, "held", true);
    if (with_raw) {
        key(j, "raw");
        put(j, "{", 1);
        key(j, "dur_ms", true);
        vx_json_int(j, r->dur_ms);
        ki(j, "frames", r->frames);
        kn(j, "floor_db", r->floor_db, 2);
        kn(j, "level_db", r->level_db, 2);
        kn(j, "snr_db", r->snr_db, 2);
        kn(j, "voiced_frac", r->voiced_frac, 3);
        kn(j, "clarity_med", r->clarity_med, 3);
        kn(j, "f0_med_hz", r->f0_med_hz, 1);
        kn(j, "onset_flux_db", r->onset_flux_db, 2);
        kn(j, "decay_db", r->decay_db, 2);
        kn(j, "peak_pos", r->peak_pos, 3);
        kn(j, "energy_iqr_db", r->energy_iqr_db, 2);
        kb(j, "truncated", r->truncated);
        kn(j, "gate_close_over_floor_db", r->gate_close_over_floor_db, 2);
        kn(j, "peak_centroid_hz", r->peak_centroid_hz, 1);
        kn(j, "centroid_hz", r->centroid_hz, 1);
        kn(j, "flatness", r->flatness, 4);
        kn(j, "zcr", r->zcr, 4);
        kn(j, "lf_ratio", r->lf_ratio, 4);
        kn(j, "hf_ratio", r->hf_ratio, 4);
        kn(j, "flux_mean_db", r->flux_mean_db, 3);
        kn(j, "centroid_spread_oct", r->centroid_spread_oct, 3);
        ki(j, "syllable_peaks", r->syllable_peaks);
        kn(j, "syllable_rate_hz", r->syllable_rate_hz, 2);
        kn(j, "interval_cv", r->interval_cv, 3);
        ki(j, "voiced_runs", r->voiced_runs);
        kn(j, "strong_voiced_frac", r->strong_voiced_frac, 3);
        kn(j, "voicing_breaks_hz", r->voicing_breaks_hz, 2);
        kn(j, "pitch_rough_st", r->pitch_rough_st, 3);
        kn(j, "pitch_resid_std_st", r->pitch_resid_std_st, 3);
        kn(j, "pitch_jumps_hz", r->pitch_jumps_hz, 2);
        if (r->has_shape) {
            kn(j, "excursion_st", r->excursion_st, 2);
            kn(j, "net_st", r->net_st, 2);
            kn(j, "hump_st", r->hump_st, 2);
            kn(j, "valley_st", r->valley_st, 2);
            kn(j, "max_st", r->max_st, 2);
            kn(j, "min_st", r->min_st, 2);
            key(j, "contour64");
            list(j, r->contour64, VX_CONTOUR64, 2);
        }
        if (r->has_impulsive) {
            kb(j, "impulsive", r->impulsive);
            kn(j, "core_ms", r->core_ms, 1);
            kb(j, "tonal", r->tonal);
        }
        if (r->has_ctx) {
            key(j, "gap_ms");
            if (r->has_gap) vx_json_num(j, r->gap_ms, 6);
            else vx_json_raw(j, "null");
            kb(j, "prev_talky", r->prev_talky);
        }
        if (r->has_cues) {
            key(j, "speech_cues");
            put(j, "[", 1);
            bool first = true;
            for (int i = 0; i < 3; i++)
                if (r->cues & (1 << i)) {
                    if (!first) put(j, ", ", 2);
                    vx_json_str(j, CUES[i]);
                    first = false;
                }
            put(j, "]", 1);
        }
        key(j, "why");
        vx_json_str(j, r->why);
        key(j, "fp_version");
        vx_json_str(j, VX_FP_VERSION);
        key(j, "fp");
        list(j, r->fp, VX_FP_LEN, 4);
        key(j, "pitch16");
        list(j, r->pitch16, r->n_pitch16, 2);
        put(j, "}", 1);
    }
    put(j, "}", 1);
}

void vx_json_features(VxJson *j, const VxEvent *ev) {
    put(j, "{\"fp\":", 6);
    list(j, ev->raw.fp, VX_FP_LEN, 4);
    put(j, ",\"fp_version\":\"" VX_FP_VERSION "\",\"pitch16\":", 30);
    list(j, ev->raw.pitch16, ev->raw.n_pitch16, 2);
    put(j, "}", 1);
}

void vx_json_hold(VxJson *j, const VxHold *h) {
    put(j, "{", 1);
    key(j, "hold", true);
    vx_json_str(j, VX_HOLD_KINDS[h->kind]);
    ki(j, "sound", h->sound);
    if (h->kind != VX_HOLD_PITCH) ki(j, "t_start_ms", h->t_start_ms);
    ki(j, "t_ms", h->t_ms);
    if (h->kind != VX_HOLD_END) kn(j, "f0_hz", h->f0_hz, 1);
    if (h->kind == VX_HOLD_START) kb(j, "flat", h->flat);
    if (h->kind == VX_HOLD_START && h->dir) {   // glide-and-hold
        key(j, "from", false);
        vx_json_str(j, "glide");
        key(j, "dir", false);
        vx_json_str(j, h->dir > 0 ? "up" : "down");
    }
    put(j, "}", 1);
}
