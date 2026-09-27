#include "vx_impl.h"
#include "vx_classify.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "vx_vocab.h"

const char *const VX_LABELS[9] = {"rise", "fall", "arch", "dip", "flat", "pop", "click", "hiss", "unknown"};

// Scratch for one sound (<= VX_MAX_SEG frames). Static: nothing is allocated, one classify at a time.
static double s_e[VX_MAX_SEG], s_f0[VX_MAX_SEG], s_clar[VX_MAX_SEG];
static double s_sort[VX_MAX_SEG];
static double s_env[VX_MAX_SEG];
static double s_st[VX_MAX_SEG], s_tmp[VX_MAX_SEG], s_sm[VX_MAX_SEG];
static int s_idx[VX_MAX_SEG];
static int s_peaks[VX_MAX_SEG];
static bool s_voiced[VX_MAX_SEG], s_vs[VX_MAX_SEG];
static double s_a[VX_MAX_SEG], s_b[VX_MAX_SEG];   // d2 / resid / intervals, contour work

double vx_py_round(double x, int nd) {
    // printf rounds the exact binary value correctly (glibc and newlib both use exact decimal conversion), which is
    // what Python's round(float, n) does.
    char b[64];
    snprintf(b, sizeof(b), "%.*f", nd, x);
    return strtod(b, NULL);
}

// ---------------------------------------------------------------- small helpers (numpy semantics)

static void sort_d(double *a, int n) {   // insertion sort for short arrays, Shell sort otherwise
    int gap = 1;
    while (gap < n / 3) gap = 3 * gap + 1;
    for (; gap >= 1; gap /= 3)
        for (int i = gap; i < n; i++) {
            double v = a[i];
            int j = i;
            while (j >= gap && a[j - gap] > v) {
                a[j] = a[j - gap];
                j -= gap;
            }
            a[j] = v;
        }
}

static double median_of(const double *x, int n, double *work) {   // np.median
    memcpy(work, x, sizeof(double) * n);
    sort_d(work, n);
    if (n & 1) return work[n / 2];
    return (work[n / 2 - 1] + work[n / 2]) / 2.0;
}

static double lerp_np(double a, double b, double t) {   // numpy _lerp
    double d = b - a;
    return t >= 0.5 ? b - d * (1.0 - t) : a + d * t;
}

static double percentile_sorted(const double *s, int n, double q) {   // np.percentile(..., method="linear")
    double v = (n - 1) * (q / 100.0);
    double pf = floor(v);
    int prev = (int)pf;
    int next = prev + 1;
    if (next > n - 1) next = n - 1;
    if (prev > n - 1) prev = n - 1;
    return lerp_np(s[prev], s[next], v - pf);
}

static double mean_of(const double *x, int n) {
    double s = 0;
    for (int i = 0; i < n; i++) s += x[i];
    return s / n;
}

static double std_of(const double *x, int n) {   // np.std (population)
    double m = mean_of(x, n), s = 0;
    for (int i = 0; i < n; i++) s += (x[i] - m) * (x[i] - m);
    return sqrt(s / n);
}

static void moving_average(const double *x, int n, int w, double *out) {
    int h = w / 2;
    for (int i = 0; i < n; i++) {
        int a = i - h < 0 ? 0 : i - h, b = i + h + 1 > n ? n : i + h + 1;
        double s = 0;
        for (int k = a; k < b; k++) s += x[k];
        out[i] = s / (b - a);
    }
}

static void running_median(const double *x, int n, int w, double *out) {
    int h = w / 2;
    for (int i = 0; i < n; i++) {
        int a = i - h < 0 ? 0 : i - h, b = i + h + 1 > n ? n : i + h + 1;
        if (b - a > 64) b = a + 64;   // median_frames is small (5); capacity guard
        double tmp[64];
        out[i] = median_of(x + a, b - a, tmp);
    }
}

static int hysteresis_peaks(const double *e, int n, double prom, int min_gap, int *peaks) {
    int np_ = 0;
    if (!n) return 0;
    double lo = e[0], hi = -INFINITY;
    int hi_i = -1;
    bool rising = true;
    for (int i = 0; i < n; i++) {
        double v = e[i];
        if (rising) {
            if (v > hi) hi = v, hi_i = i;
            if (hi - lo >= prom && hi - v >= prom) {
                if (np_ && hi_i - peaks[np_ - 1] < min_gap) {
                    if (e[hi_i] > e[peaks[np_ - 1]]) peaks[np_ - 1] = hi_i;
                } else {
                    peaks[np_++] = hi_i;
                }
                rising = false;
                lo = v;
            }
        } else {
            if (v < lo) lo = v;
            if (v - lo >= prom) {
                rising = true;
                hi = v;
                hi_i = i;
            }
        }
    }
    if (rising && hi_i >= 0 && hi - lo >= prom && (!np_ || hi_i - peaks[np_ - 1] >= min_gap)) peaks[np_++] = hi_i;
    return np_;
}

static int bucket(double v, const double *edges, int n_edges) {
    for (int i = 0; i < n_edges; i++)
        if (v < edges[i]) return i;
    return n_edges;
}

// ---------------------------------------------------------------- pitch post-processing

// voiced frames -> semitones re 100 Hz, median filtered, octave / jump corrected. Returns the count; s_st holds them.
static int clean_pitch(const bool *voiced, const double *f0, int n, const VxConfig *cfg) {
    int k = 0;
    for (int i = 0; i < n; i++)
        if (voiced[i]) {
            s_idx[k] = i;
            s_tmp[k] = 12.0 * log2(f0[i] / 100.0);
            k++;
        }
    if (!k) return 0;
    running_median(s_tmp, k, cfg->median_frames, s_sm);
    int nk = 0;
    int last_i = -1000000;
    for (int j = 0; j < k; j++) {
        int i = s_idx[j];
        double s = s_sm[j];
        if (nk && i - last_i <= 3) {   // within a voiced run: enforce continuity
            double prev = s_st[nk - 1];
            if (fabs(s - prev) > cfg->jump_limit_st) {
                double c1 = s - 12.0, c2 = s + 12.0;
                if (fabs(c1 - prev) <= cfg->jump_limit_st) s = c1;
                else if (fabs(c2 - prev) <= cfg->jump_limit_st) s = c2;
                else continue;
            }
        }
        last_i = i;
        s_st[nk++] = s;
    }
    return nk;
}

struct Shape {
    int shape;   // VxContour
    double excursion, net, hump, valley, hi, lo;
};

static Shape contour_shape(const double *st, int n, const VxConfig *cfg, double *sm) {
    int e = n / 3 < 1 ? 1 : n / 3;
    if (cfg->edge_frames < e) e = cfg->edge_frames;
    double *work = s_b;
    double start = median_of(st, e, work);
    double end = median_of(st + n - e, e, work);
    for (int i = 0; i < n; i++) work[i] = st[i] - start;
    moving_average(work, n, cfg->smooth_frames, sm);
    Shape r;
    r.net = end - start;
    r.hi = sm[0];
    r.lo = sm[0];
    for (int i = 1; i < n; i++) {
        if (sm[i] > r.hi) r.hi = sm[i];
        if (sm[i] < r.lo) r.lo = sm[i];
    }
    r.hump = r.hi - (r.net > 0.0 ? r.net : 0.0);
    r.valley = (r.net < 0.0 ? r.net : 0.0) - r.lo;
    double an = fabs(r.net);
    double biggest = an > r.hump ? an : r.hump;
    if (r.valley > biggest) biggest = r.valley;
    if (biggest < cfg->flat_max_range_st) {
        r.shape = VX_FLAT;
        r.excursion = biggest;
    } else if (r.hump >= cfg->shape_min_st && r.hump >= cfg->arch_ratio * an && r.hump >= r.valley) {
        r.shape = VX_ARCH;
        r.excursion = r.hump;
    } else if (r.valley >= cfg->shape_min_st && r.valley >= cfg->arch_ratio * an && r.valley > r.hump) {
        r.shape = VX_DIP;
        r.excursion = r.valley;
    } else {
        r.shape = r.net > 0 ? VX_RISE : VX_FALL;
        r.excursion = an;
    }
    return r;
}

// resample_contour: np.interp at np.linspace(0, n - 1, m), each value rounded to 2 decimals
static void resample_contour(const double *c, int n, int m, float *out) {
    if (n == 1) {
        for (int i = 0; i < m; i++) out[i] = (float)vx_py_round(c[0], 2);
        return;
    }
    double step = (double)(n - 1) / (m - 1);
    for (int i = 0; i < m; i++) {
        double x = i == m - 1 ? (double)(n - 1) : i * step;
        double v;
        if (x >= n - 1) {
            v = c[n - 1];
        } else {
            int j = (int)floor(x);
            double slope = (c[j + 1] - c[j]) / 1.0;
            v = slope * (x - j) + c[j];
        }
        out[i] = (float)vx_py_round(v, 2);
    }
}

// ---------------------------------------------------------------- buckets

static int tone_of(double clar_med, double voiced_frac, const VxConfig *cfg) {
    if (clar_med >= cfg->tone_clear && voiced_frac >= cfg->tone_min_voiced_frac) return 2;
    if (clar_med >= cfg->tone_breathy) return 1;
    return 0;
}

static int loudness_of(double level, double floor, const VxConfig *cfg) {
    if (cfg->has_loud_calib_db) {
        if (level < cfg->loud_calib_db - cfg->loud_calib_span_db) return 0;
        if (level >= cfg->loud_calib_db + cfg->loud_calib_span_db) return 2;
        return 1;
    }
    double ref = floor > cfg->loud_ref_min_db ? floor : cfg->loud_ref_min_db;
    double edges[2] = {cfg->loud_quiet_over_floor_db, cfg->loud_loud_over_floor_db};
    return bucket(level - ref, edges, 2);
}

static int speech_cues(const VxRaw *raw, const VxConfig *cfg, int *count) {
    int c = 0, n = 0;
    if (raw->strong_voiced_frac < cfg->talk_max_voiced_frac || raw->voiced_runs >= cfg->talk_min_runs) c |= VX_CUE_BROKEN, n++;
    if (raw->centroid_spread_oct >= cfg->talk_centroid_spread_oct) c |= VX_CUE_FORMANT, n++;
    if (raw->syllable_peaks >= cfg->talk_min_peaks &&
        ((cfg->talk_min_rate_hz <= raw->syllable_rate_hz && raw->syllable_rate_hz <= cfg->talk_max_rate_hz) ||
         raw->energy_iqr_db >= cfg->talk_min_iqr_db))
        c |= VX_CUE_SYLLABLE, n++;
    *count = n;
    return c;
}

static const char *const CUE_NAMES[3] = {"broken voicing", "consonant / formant changes", "syllable-like loudness"};

static int sounds_like_voiced(VxRaw *raw, bool coughy, bool laughy, int dur, const VxConfig *cfg, char *why) {
    if (dur > cfg->max_gesture_ms || raw->truncated) {
        bool tonal = raw->clarity_med < cfg->music_max_clarity && raw->flatness < cfg->music_max_flatness;
        strcpy(why, tonal ? "too long, tonal" : "too long");
        return tonal ? VX_LIKE_MUSIC : VX_LIKE_NOISE;
    }
    bool clear = raw->clarity_med >= cfg->tone_clear && raw->voiced_frac >= cfg->tone_min_voiced_frac;
    if (raw->f0_med_hz >= cfg->whistle_min_hz && clear) {
        strcpy(why, "clear tone with f0 >= whistle_min_hz");
        return VX_LIKE_WHISTLE;
    }
    if (dur >= cfg->machine_min_ms && raw->pitch_resid_std_st < cfg->machine_max_pitch_std_st) {
        strcpy(why, "machine-steady pitch");
        return VX_LIKE_NOISE;
    }
    if (coughy) {
        strcpy(why, "onset + early peak + decay");
        return VX_LIKE_COUGHING;
    }
    if (laughy) {
        strcpy(why, "regular bursts");
        return VX_LIKE_LAUGHING;
    }
    int n_cues;
    int cues = speech_cues(raw, cfg, &n_cues);
    raw->has_cues = true;
    raw->cues = cues;
    if (n_cues >= cfg->talk_min_cues || raw->centroid_spread_oct >= cfg->talk_strong_centroid_spread_oct) {
        strcpy(why, "speech cues: ");
        bool first = true;
        for (int i = 0; i < 3; i++)
            if (cues & (1 << i)) {
                if (!first) strcat(why, ", ");
                strcat(why, CUE_NAMES[i]);
                first = false;
            }
        return VX_LIKE_TALKING;
    }
    if (raw->has_gap && raw->gap_ms <= cfg->train_gap_ms && raw->prev_talky && (cues || dur <= cfg->train_max_ms)) {
        strcpy(why, "follows talking closely");
        return VX_LIKE_TALKING;
    }
    if (dur >= cfg->music_min_ms && raw->clarity_med < cfg->music_max_clarity && raw->flatness < cfg->music_max_flatness &&
        raw->pitch_jumps_hz >= cfg->music_min_jumps_hz) {
        strcpy(why, "long, tonal, stepping pitch, no single clear period");
        return VX_LIKE_MUSIC;
    }
    strcpy(why, "default voiced");
    return VX_LIKE_HUM;
}

// ---------------------------------------------------------------- the classifier

void vx_classify(const VxSegStats *seg, const VxConfig *cfg, const VxContext *ctx, VxEvent *ev) {
    const double fm = cfg->frame_ms();
    const int n = seg->n;
    VxRaw *raw = &ev->raw;
    memset(raw, 0, sizeof(*raw));
    double ts = seg->t_start_ms > 0.0 ? seg->t_start_ms : 0.0;
    double te = seg->t_start_ms + n * fm;
    if (te < 0.0) te = 0.0;
    const int t0 = (int)nearbyint(ts), t1 = (int)nearbyint(te);   // round half to even, like round()
    const int dur = t1 - t0;
    double *e = s_e, *f0 = s_f0, *clar = s_clar;
    for (int i = 0; i < n; i++) {
        e[i] = seg->e_db[i];
        f0[i] = seg->f0[i];
        clar[i] = seg->clarity[i];
    }
    const double floor = seg->floor_db;

    int n_voiced = 0;
    for (int i = 0; i < n; i++) {
        s_voiced[i] = clar[i] >= cfg->voiced_clarity && f0[i] > 0 && e[i] >= floor + cfg->voiced_min_db_over_floor;
        n_voiced += s_voiced[i];
    }
    const double voiced_frac = (double)n_voiced / n;
    const double clar_med = median_of(clar, n, s_sort);
    memcpy(s_sort, e, sizeof(double) * n);
    sort_d(s_sort, n);
    const double level = percentile_sorted(s_sort, n, 90.0);
    const double iqr = percentile_sorted(s_sort, n, 75.0) - percentile_sorted(s_sort, n, 25.0);
    int peak_i = 0;
    for (int i = 1; i < n; i++)
        if (e[i] > e[peak_i]) peak_i = i;
    double onset_flux = 0;
    if (seg->n_flux) {
        onset_flux = seg->flux[0];
        for (int i = 1; i < seg->n_flux; i++)
            if (seg->flux[i] > onset_flux) onset_flux = seg->flux[i];
    }
    const int nt = n < 3 ? n : 3;
    const double tail = mean_of(e + n - nt, nt);
    const double decay = e[peak_i] - tail;
    const double peak_pos = (double)peak_i / (n - 1 > 1 ? n - 1 : 1);

    // syllable-like energy modulation (talking / laughing)
    moving_average(e, n, 3, s_env);
    const int n_peaks = hysteresis_peaks(s_env, n, cfg->syllable_prominence_db, cfg->syllable_min_gap_frames, s_peaks);
    const double dur_s = (dur > 1 ? dur : 1) / 1000.0;
    const double rate = n_peaks / dur_s;
    double interval_cv = 1.0;
    if (n_peaks >= 3) {   // ints = diff(peaks) * fm, needs >= 2 intervals
        double *ints = s_a;
        for (int i = 0; i + 1 < n_peaks; i++) ints[i] = (s_peaks[i + 1] - s_peaks[i]) * fm;
        interval_cv = std_of(ints, n_peaks - 1) / mean_of(ints, n_peaks - 1);
    }
    int run_starts = s_voiced[0] ? 1 : 0;
    for (int i = 1; i < n; i++) run_starts += s_voiced[i] && !s_voiced[i - 1];
    const double breaks_hz = run_starts / dur_s;
    int runs = 0;
    for (int k = 0; k < n;) {
        if (s_voiced[k]) {
            int j = k;
            while (j < n && s_voiced[j]) j++;
            runs += j - k >= 2;
            k = j;
        } else {
            k++;
        }
    }

    // pitch: only frames near the sound's own level
    int n_strong = 0, n_vs = 0;
    for (int i = 0; i < n; i++) {
        bool strong = e[i] >= level - cfg->contour_db;
        n_strong += strong;
        s_vs[i] = s_voiced[i] && strong;
        n_vs += s_vs[i];
    }
    const double strong_voiced_frac = (double)n_vs / (n_strong > 1 ? n_strong : 1);
    const int ns = clean_pitch(s_vs, f0, n, cfg);
    const double *st = s_st;
    Shape shape = {};
    const bool has_shape = ns >= 3;
    double rough = 0, resid_std = 0, f0_med = 0;
    int jumps = 0;
    if (has_shape) {
        shape = contour_shape(st, ns, cfg, s_sm);   // s_sm = contour_rel
        double *d2 = s_a;
        // np.diff(st, 2) is (st[i+2] - st[i+1]) - (st[i+1] - st[i])
        for (int i = 0; i + 2 < ns; i++) d2[i] = fabs((st[i + 2] - st[i + 1]) - (st[i + 1] - st[i]));
        rough = median_of(d2, ns - 2, s_sort);
        double *resid = s_a;
        if (ns >= 4) {   // np.polyfit(t, st, 1)
            double tm = (ns - 1) / 2.0, sm = mean_of(st, ns), sxy = 0, sxx = 0;
            for (int i = 0; i < ns; i++) {
                sxy += (i - tm) * (st[i] - sm);
                sxx += (i - tm) * (i - tm);
            }
            double slope = sxy / sxx, icpt = sm - slope * tm;
            for (int i = 0; i < ns; i++) resid[i] = st[i] - (slope * i + icpt);
        } else {
            double m = mean_of(st, ns);
            for (int i = 0; i < ns; i++) resid[i] = st[i] - m;
        }
        resid_std = std_of(resid, ns);
        moving_average(st, ns, 3, s_tmp);
        for (int i = 0; i + 1 < ns; i++) jumps += fabs(s_tmp[i + 1] - s_tmp[i]) > 1.5;
        f0_med = 100.0 * pow(2.0, median_of(st, ns, s_sort) / 12.0);
    }
    const double jumps_hz = jumps / dur_s;

    raw->dur_ms = dur;
    raw->frames = n;
    raw->floor_db = vx_py_round(floor, 2);
    raw->level_db = vx_py_round(level, 2);
    raw->snr_db = vx_py_round(level - floor, 2);
    raw->voiced_frac = vx_py_round(voiced_frac, 3);
    raw->clarity_med = vx_py_round(clar_med, 3);
    raw->f0_med_hz = vx_py_round(f0_med, 1);
    raw->onset_flux_db = vx_py_round(onset_flux, 2);
    raw->decay_db = vx_py_round(decay, 2);
    raw->peak_pos = vx_py_round(peak_pos, 3);
    raw->energy_iqr_db = vx_py_round(iqr, 2);
    raw->truncated = seg->truncated;
    raw->gate_close_over_floor_db = vx_py_round(seg->close_over_floor_db, 2);
    raw->peak_centroid_hz = vx_py_round(seg->peak_centroid, 1);
    raw->centroid_hz = vx_py_round(vx_seg_wmean(seg, seg->centroid_sum), 1);
    raw->flatness = vx_py_round(vx_seg_wmean(seg, seg->flatness_sum), 4);
    raw->zcr = vx_py_round(vx_seg_wmean(seg, seg->zcr_sum), 4);
    raw->lf_ratio = vx_py_round(vx_seg_wmean(seg, seg->lf_sum), 4);
    raw->hf_ratio = vx_py_round(vx_seg_wmean(seg, seg->hf_sum), 4);
    raw->flux_mean_db = vx_py_round(vx_seg_wmean(seg, seg->flux_sum), 3);
    if (seg->cent_n) {
        double m = (double)seg->cent_sum / seg->cent_n;
        double v = (double)seg->cent_sq / seg->cent_n - m * m;
        raw->centroid_spread_oct = vx_py_round(sqrt(v > 0.0 ? v : 0.0), 3);
    } else {
        raw->centroid_spread_oct = 0.0;
    }
    raw->syllable_peaks = n_peaks;
    raw->syllable_rate_hz = vx_py_round(rate, 2);
    raw->interval_cv = vx_py_round(interval_cv, 3);
    raw->voiced_runs = runs;
    raw->strong_voiced_frac = vx_py_round(strong_voiced_frac, 3);
    raw->voicing_breaks_hz = vx_py_round(breaks_hz, 2);
    raw->pitch_rough_st = vx_py_round(rough, 3);
    raw->pitch_resid_std_st = vx_py_round(resid_std, 3);
    raw->pitch_jumps_hz = vx_py_round(jumps_hz, 2);
    if (has_shape) {
        raw->has_shape = true;
        raw->excursion_st = vx_py_round(shape.excursion, 2);
        raw->net_st = vx_py_round(shape.net, 2);
        raw->hump_st = vx_py_round(shape.hump, 2);
        raw->valley_st = vx_py_round(shape.valley, 2);
        raw->max_st = vx_py_round(shape.hi, 2);
        raw->min_st = vx_py_round(shape.lo, 2);
        resample_contour(s_sm, ns, VX_CONTOUR64, raw->contour64);
        resample_contour(s_sm, ns, VX_PITCH16, raw->pitch16);
        raw->n_pitch16 = VX_PITCH16;
    }

    const int loud = loudness_of(level, floor, cfg);
    const double dur_edges[3] = {(double)cfg->dur_short_ms, (double)cfg->dur_medium_ms, (double)cfg->dur_long_ms};
    const int dur_b = bucket(dur, dur_edges, 3);
    const double centroid = vx_seg_wmean(seg, seg->centroid_sum);
    const double zcr = vx_seg_wmean(seg, seg->zcr_sum);
    const double lf = vx_seg_wmean(seg, seg->lf_sum);

    ev->t_start_ms = t0;
    ev->t_end_ms = t1;
    ev->truncated = seg->truncated;
    ev->emit = true;
    ev->text[0] = 0;

    // 1. short -> pop / click
    const bool impulsive = onset_flux >= cfg->pop_onset_flux_db || peak_i <= cfg->pop_attack_frames;
    int core_n = 0;
    for (int i = 0; i < n; i++) core_n += e[i] >= e[peak_i] - cfg->discrete_core_db;
    const double core_ms = core_n * fm;
    const bool tonal = voiced_frac > cfg->discrete_tonal_voiced_frac && clar_med > cfg->discrete_tonal_clarity;
    raw->has_impulsive = true;
    raw->impulsive = impulsive;
    raw->core_ms = core_ms;
    raw->tonal = tonal;
    if (dur <= cfg->discrete_max_ms && core_ms <= cfg->discrete_core_ms) {
        if (impulsive && !tonal && (n_voiced < cfg->discrete_max_voiced || peak_pos <= cfg->discrete_peak_pos)) {
            int kind = (double)seg->peak_centroid >= cfg->click_centroid_hz ? VX_CLICK : VX_POP;
            ev->label = kind == VX_CLICK ? VX_L_CLICK : VX_L_POP;
            ev->like = VX_LIKE_MOUTH;
            vx_discrete_line(ev->text, kind, loud);
            snprintf(raw->why, sizeof(raw->why), "short+flux -> %s", VX_LABELS[ev->label]);
            return;
        }
        if (n_voiced < cfg->discrete_max_voiced) {
            ev->label = VX_L_UNKNOWN;
            ev->like = VX_LIKE_NOISE;
            ev->emit = false;
            strcpy(raw->why, "short blip without onset");
            return;
        }
    }

    const bool unvoiced = voiced_frac < cfg->hiss_max_voiced_frac || !has_shape;
    const bool coughy = onset_flux >= cfg->cough_onset_flux_db && peak_pos <= cfg->cough_peak_pos &&
                        decay >= cfg->cough_decay_db && dur <= cfg->cough_max_ms && voiced_frac <= cfg->cough_max_voiced_frac;
    const bool laughy = n_peaks >= cfg->laugh_min_peaks && cfg->laugh_rate_lo_hz <= rate && rate <= cfg->laugh_rate_hi_hz &&
                        interval_cv <= cfg->laugh_max_interval_cv && clar_med <= cfg->laugh_max_clarity;

    const double exc_edges[2] = {cfg->exc_medium_st, cfg->exc_large_st};
    const int tone = tone_of(clar_med, voiced_frac, cfg);
#define HUM_FROM(like_, why_)                                                              \
    do {                                                                                   \
        int contour = has_shape ? shape.shape : VX_FLAT;                                   \
        int exc_b = has_shape ? bucket(shape.excursion, exc_edges, 2) : 0;                 \
        ev->label = contour;                                                               \
        ev->like = (like_);                                                                \
        vx_hum_line(ev->text, contour, exc_b, dur_b, tone, loud, ev->like);                \
        if ((const char *)(why_) != (const char *)raw->why) snprintf(raw->why, sizeof(raw->why), "%s", (const char *)(why_)); \
        return;                                                                            \
    } while (0)

    // 2. mostly unvoiced
    if (unvoiced) {
        if (centroid >= cfg->hiss_centroid_hz && zcr >= cfg->hiss_zcr && dur >= cfg->hiss_min_ms && !laughy) {
            bool steady = dur >= cfg->hiss_bg_steady_ms && iqr < cfg->hiss_steady_db;
            bool lfy = lf > cfg->hiss_bg_lf_ratio;
            ev->label = VX_L_HISS;
            ev->like = (lfy || steady) ? VX_LIKE_NOISE : VX_LIKE_MOUTH;
            vx_hiss_line(ev->text, dur_b, loud, ev->like);
            snprintf(raw->why, sizeof(raw->why), "hiss (%s)", lfy ? "lf" : steady ? "steady" : "mouth");
            return;
        }
        if (coughy) HUM_FROM(VX_LIKE_COUGHING, "unvoiced cough shape");
        if (laughy) HUM_FROM(VX_LIKE_LAUGHING, "unvoiced regular bursts");
        ev->label = VX_L_HISS;
        ev->like = VX_LIKE_NOISE;
        vx_hiss_line(ev->text, dur_b, loud, VX_LIKE_NOISE);
        strcpy(raw->why, "unvoiced noise");
        return;
    }

    // 3. voiced
    raw->has_ctx = true;
    raw->has_gap = ctx && ctx->has_prev;
    raw->gap_ms = raw->has_gap ? ctx->gap_ms : 0.0;
    raw->prev_talky = ctx && ctx->has_prev && ctx->prev_talky;
    int like = sounds_like_voiced(raw, coughy, laughy, dur, cfg, raw->why);
    HUM_FROM(like, raw->why);
#undef HUM_FROM
}

// ---------------------------------------------------------------- shared with vx_hold.cpp

double vx_np_median(const double *x, int n, double *work) { return median_of(x, n, work); }
double vx_np_std(const double *x, int n) { return std_of(x, n); }
