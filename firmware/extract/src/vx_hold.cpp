#include "vx_impl.h"
#include "vx_hold.h"
#include "vx_classify.h"

const char *const VX_HOLD_KINDS[3] = {"start", "pitch", "end"};

// Scratch for one window (<= VX_MAX_SEG frames).
static double s_st[VX_MAX_SEG], s_clar[VX_MAX_SEG], s_work[VX_MAX_SEG];

static int t_int(double ms) { return (int)nearbyint(ms < 0.0 ? 0.0 : ms); }   // hold.py _t: round(max(0, ms))

static bool voiced(const VxSegStats *s, int i, const VxConfig *cfg) {   // hold.py _voiced, as classify
    double e = s->e_db[i], f0 = s->f0[i], c = s->clarity[i];
    return c >= cfg->voiced_clarity && f0 > 0 && e >= s->floor_db + cfg->voiced_min_db_over_floor;
}

static int window(int ms, double frame_ms, int min_frames) {
    if (ms <= 0) return 0;
    int k = (int)nearbyint(ms / frame_ms);
    return k > min_frames ? k : min_frames;
}

void vx_hold_init(VxHoldTracker *h, const VxConfig *cfg) {
    h->cfg = cfg;
    h->w = window(cfg->hold_start_ms, cfg->frame_ms(), 2);    // hold_window
    h->wg = window(cfg->hold_glide_ms, cfg->frame_ms(), 2);   // glide_window
    h->dg = window(cfg->hold_glide_delay_ms, cfg->frame_ms(), 1);   // glide_delay
    h->pk = window(cfg->hold_pitch_ms, cfg->frame_ms(), 1);   // pitch_frames
    h->next_pitch = 0;
    h->sound = 0;
    h->cur = false;
    h->held = false;
    h->glide_ok = false;
    h->glide_run = 0;
    h->has_last = false;
    h->last_end_ms = 0;
}

// hold.py _steady(): the steadiness test on the sound's last w frames. True with med = their median pitch (st re
// 100 Hz) if they look like one steady voiced tone.
static bool steady(const VxSegStats *s, const VxConfig *cfg, int w, double *med_st) {
    if (w <= 0 || s->n < w) return false;
    const int a = s->n - w;
    int nv = 0;
    for (int i = a; i < s->n; i++) {
        s_clar[i - a] = s->clarity[i];
        if (voiced(s, i, cfg)) s_st[nv++] = 12.0 * log2((double)s->f0[i] / 100.0);
    }
    if (nv < 2 || (double)nv / w < cfg->hold_min_voiced_frac) return false;
    if (vx_np_median(s_clar, w, s_work) < cfg->hold_min_clarity) return false;
    const int half = nv / 2;
    if (fabs(vx_np_median(s_st + half, nv - half, s_work) - vx_np_median(s_st, half, s_work)) > cfg->hold_max_drift_st)
        return false;
    const double med = vx_np_median(s_st, nv, s_work);
    for (int i = 0; i < nv; i++) s_clar[i] = fabs(s_st[i] - med);   // s_clar reused: |st - med|
    if (vx_np_median(s_clar, nv, s_work) > cfg->hold_max_mad_st) return false;
    if (vx_np_std(s_st, nv) < cfg->machine_max_pitch_std_st) return false;
    *med_st = med;
    return true;
}

// hold.py _start_st(): the sound's start pitch (st re 100 Hz), median of its first edge_frames voiced frames (over
// all its frames so far). Only after steady() passed, so there is a voiced frame.
static double start_st(const VxSegStats *s, const VxConfig *cfg) {
    int ns = 0;
    for (int i = 0; i < s->n && ns < cfg->edge_frames; i++)
        if (voiced(s, i, cfg)) s_clar[ns++] = 12.0 * log2((double)s->f0[i] / 100.0);
    return vx_np_median(s_clar, ns, s_work);
}

static double st_hz(double st) { return vx_py_round(100.0 * pow(2.0, st / 12.0), 1); }   // hold.py _hz

// hold.py check(): the hold test on the sound's last w frames. True with (f0_hz, flat) if it qualifies.
static bool check(const VxSegStats *s, const VxConfig *cfg, int w, double *f0_hz, bool *flat) {
    double med;
    if (!steady(s, cfg, w, &med)) return false;
    *f0_hz = st_hz(med);
    *flat = fabs(med - start_st(s, cfg)) <= cfg->hold_flat_st;
    return true;
}

// hold.py glide_check(): glide-and-hold on the sound's last w frames: steady, at least hold_glide_min_st from the
// sound's start pitch, and within hold_glide_peak_st of its highest (up) / lowest (down) voiced pitch so far. True
// with (f0_hz, dir +1 up / -1 down) if it qualifies.
static bool glide_check(const VxSegStats *s, const VxConfig *cfg, int w, double *f0_hz, int *dir) {
    double med;
    if (!steady(s, cfg, w, &med)) return false;
    const double d = med - start_st(s, cfg);
    if (fabs(d) < cfg->hold_glide_min_st) return false;
    if (cfg->hold_glide_peak_st > 0) {
        double peak = med;   // the window's own frames are voiced, so the extreme is at least as far as med
        for (int i = 0; i < s->n; i++) {
            if (!voiced(s, i, cfg)) continue;
            const double st = 12.0 * log2((double)s->f0[i] / 100.0);
            if (d > 0 ? st > peak : st < peak) peak = st;
        }
        if (fabs(peak - med) > cfg->hold_glide_peak_st) return false;
    }
    *f0_hz = st_hz(med);
    *dir = d > 0 ? 1 : -1;
    return true;
}

// hold.py pitch_report(): median f0 of the voiced frames among the sound's last k, or false if too few are voiced.
static bool pitch_report(const VxSegStats *s, const VxConfig *cfg, int k, double *f0_hz) {
    if (k <= 0 || s->n < k) return false;
    int nv = 0;
    for (int i = s->n - k; i < s->n; i++)
        if (voiced(s, i, cfg)) s_st[nv++] = s->f0[i];
    if (nv == 0 || (double)nv / k < cfg->hold_pitch_min_voiced_frac) return false;
    *f0_hz = vx_py_round(vx_np_median(s_st, nv, s_work), 1);
    return true;
}

static void fill(VxHold *o, int kind, const VxHoldTracker *h, const VxSegStats *s, double f0_hz, bool flat,
                 int dir = 0) {
    o->kind = kind;
    o->sound = h->sound;
    o->t_start_ms = t_int(s->t_start_ms);
    o->t_ms = t_int(s->t_start_ms + s->n * h->cfg->frame_ms());
    o->f0_hz = f0_hz;
    o->flat = flat;
    o->dir = dir;
}

static void open_sound(VxHoldTracker *h, const VxSegStats *s) {
    h->sound++;
    h->cur = true;
    h->held = false;
    h->glide_run = 0;
    h->glide_ok = !h->has_last || t_int(s->t_start_ms) - h->last_end_ms >= h->cfg->hold_glide_quiet_ms;
}

bool vx_hold_frame(VxHoldTracker *h, const VxSegStats *s, bool active, VxHold *out) {
    if (!s) return false;
    if (!h->cur) open_sound(h, s);
    if (!active || h->w <= 0) return false;
    double f0 = 0;
    if (h->held) {
        if (h->pk > 0 && s->n >= h->next_pitch) {
            h->next_pitch = s->n + h->pk;
            if (pitch_report(s, h->cfg, h->pk, &f0)) {
                fill(out, VX_HOLD_PITCH, h, s, f0, false);
                return true;
            }
        }
        return false;
    }
    int dir = 0;
    if (h->wg > 0 && h->glide_ok && glide_check(s, h->cfg, h->wg, &f0, &dir)) {   // glide-and-hold first
        if (++h->glide_run <= h->dg) return false;   // late start: not yet (the flat test waits too)
        h->held = true;
        h->next_pitch = s->n + h->pk;
        fill(out, VX_HOLD_START, h, s, f0, false, dir);
        return true;
    }
    h->glide_run = 0;
    bool flat = false;
    if (!check(s, h->cfg, h->w, &f0, &flat)) return false;
    h->held = true;
    h->next_pitch = s->n + h->pk;
    fill(out, VX_HOLD_START, h, s, f0, flat);
    return true;
}

bool vx_hold_closed(VxHoldTracker *h, const VxSegStats *s, VxHold *out, int *sound, bool *held) {
    if (!h->cur) open_sound(h, s);   // not seen open (cannot happen: a sound is open for at least one frame)
    *sound = h->sound;
    *held = h->held;
    h->has_last = true;
    h->last_end_ms = t_int(s->t_start_ms + s->n * h->cfg->frame_ms());
    if (h->held) fill(out, VX_HOLD_END, h, s, 0.0, false);
    h->cur = false;
    h->held = false;
    return *held;
}
