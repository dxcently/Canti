#include "vx_impl.h"
#include "vx_tick.h"
#include <string.h>
#include "vx_fft.h"

static const double PI = 3.14159265358979323846;

void vx_tick_config_default(VxTickConfig *c) {
    c->fs = 16000;
    c->win = 512;
    c->hop = 320;
    c->hpf_hz = 70.0;
    c->f0_min_hz = 60.0;
    c->f0_max_hz = 1100.0;
    c->mpm_k = 0.88;
    c->clarity_on = 0.8;
    c->level_over_floor_db = 6.0;
    c->floor_ticks = 250;
    c->floor_pct = 10.0;
    c->lpc_order = 18;
    c->preemph = 0.97;
    c->f1_lo = 200.0;
    c->f1_hi = 1100.0;
    c->f2_lo = 600.0;
    c->f2_hi = 3600.0;
    c->f2_min_gap_hz = 150.0;
    c->max_bw_hz = 500.0;
    c->f2_max_bw_hz = 1000.0;
    c->f2_jump_hz = 500.0;
    c->f2_jump_frames = 5;
}

const char *vx_tick_init(VxTick *t, const VxTickConfig *c) {
    if (c) t->cfg = *c;
    else vx_tick_config_default(&t->cfg);
    const VxTickConfig *k = &t->cfg;
    if (k->win != VX_TICK_WIN) return "tick win must be 512";
    if (k->hop < 1 || k->hop > k->win) return "tick hop must be 1..win";
    if (k->floor_ticks < 1 || k->floor_ticks > VX_TICK_MAX_LEVELS) return "tick floor_ticks must be 1..256";
    if (k->lpc_order < 2 || k->lpc_order > VX_TICK_MAX_ORDER) return "tick lpc_order must be 2..24";
    if (k->f2_jump_frames < 1 || k->f2_jump_frames > VX_TICK_MAX_RUN) return "tick f2_jump_frames must be 1..16";
    vx_fft_init();
    // scipy butter(2, hpf_hz / (fs / 2), "high")
    double K = tan(PI * k->hpf_hz / k->fs);
    double norm = 1.0 / (1.0 + sqrt(2.0) * K + K * K);
    t->b0 = norm;
    t->b1 = -2.0 * norm;
    t->b2 = norm;
    t->a1 = 2.0 * (K * K - 1.0) * norm;
    t->a2 = (1.0 - sqrt(2.0) * K + K * K) * norm;
    for (int i = 0; i < k->win; i++) t->hamming[i] = 0.54 - 0.46 * cos(2.0 * PI * i / (k->win - 1));   // np.hamming
    vx_tick_reset(t);
    return NULL;
}

void vx_tick_reset(VxTick *t) {
    t->z1 = t->z2 = 0.0;
    memset(t->buf, 0, sizeof(t->buf));
    t->fill = 0;
    t->n = 0;
    t->lv_n = t->lv_head = 0;
    t->f2_last = NAN;
    t->f2_since = 0;
    t->run_n = 0;
}

const char *vx_tick_why_name(int why) {
    switch (why) {
    case VX_TICK_WHY_QUIET: return "quiet";
    case VX_TICK_WHY_UNCLEAR: return "unclear";
    case VX_TICK_WHY_NO_PITCH: return "no pitch";
    default: return "";
    }
}

// ------------------------------------------------------------------------------------------------ the floor

static void levels_add(VxTick *t, double v) {
    int cap = t->cfg.floor_ticks;
    if (t->lv_n == cap) {   // drop the oldest from the sorted copy
        double old = t->lv_ring[t->lv_head];
        int i = 0;
        while (i < t->lv_n - 1 && t->lv_sorted[i] != old) i++;
        memmove(&t->lv_sorted[i], &t->lv_sorted[i + 1], (size_t)(t->lv_n - 1 - i) * sizeof(double));
        t->lv_n--;
    }
    t->lv_ring[t->lv_head] = v;
    t->lv_head = (t->lv_head + 1) % cap;
    int j = t->lv_n;
    while (j > 0 && t->lv_sorted[j - 1] > v) {
        t->lv_sorted[j] = t->lv_sorted[j - 1];
        j--;
    }
    t->lv_sorted[j] = v;
    t->lv_n++;
}

static double floor_db(const VxTick *t) {
    if (t->lv_n == 0) return -90.0;
    double pos = (t->lv_n - 1) * t->cfg.floor_pct / 100.0;   // numpy percentile, linear
    int lo = (int)floor(pos);
    int hi = lo + 1 < t->lv_n ? lo + 1 : lo;
    double f = pos - lo;
    return t->lv_sorted[lo] + (t->lv_sorted[hi] - t->lv_sorted[lo]) * f;
}

// ------------------------------------------------------------------------------------------------ MPM pitch

double vx_tick_nsdf_f0(VxTick *t, const double *x, int n, double *clarity) {
    const VxTickConfig *k = &t->cfg;
    *clarity = 0.0;
    for (int i = 0; i < n; i++) t->x[i] = (vx_real)x[i];
    int lo = (int)(k->fs / k->f0_max_hz);
    if (lo < 2) lo = 2;
    int hi = (int)(k->fs / k->f0_min_hz);
    if (hi > n - 2) hi = n - 2;
    // r = irfft(|rfft(x, 2n)|^2)[:n]; only lags up to hi + 1 are read
    vx_rfft_power(t->x, n, 2 * n, t->acf_p);
    vx_irfft_real(t->acf_p, 2 * n, t->r, hi + 2);
    // m[tau] = sum x[0..n-1-tau]^2 + sum x[tau..n-1]^2 (cumulative sums in double)
    double *c = t->s_b;
    double s = 0.0;
    for (int i = 0; i < n; i++) {
        s += x[i] * x[i];
        c[i] = s;
    }
    int len = hi - lo + 3;   // seg = nsdf[lo - 1 .. hi + 1]
    double *seg = t->s_c;
    for (int j = 0; j < len; j++) {
        int tau = lo - 1 + j;
        double m = c[n - 1 - tau] + (c[n - 1] - (tau > 0 ? c[tau - 1] : 0.0));
        seg[j] = 2.0 * (double)t->r[tau] / (m + 1e-12);
    }
    double top = -1.0;
    bool any = false;
    for (int j = 1; j < len - 1; j++)
        if (seg[j] > seg[j - 1] && seg[j] >= seg[j + 1] && seg[j] > 0) {
            if (!any || seg[j] > top) top = seg[j];
            any = true;
        }
    if (!any) return 0.0;
    for (int j = 1; j < len - 1; j++)
        if (seg[j] > seg[j - 1] && seg[j] >= seg[j + 1] && seg[j] > 0 && seg[j] >= k->mpm_k * top) {
            double a = seg[j - 1], b = seg[j], cc = seg[j + 1];
            double den = a - 2 * b + cc;
            double d = den != 0 ? 0.5 * (a - cc) / den : 0.0;
            *clarity = b;
            return k->fs / (lo - 1 + j + d);
        }
    return 0.0;   // not reached: the top peak itself qualifies
}

// ------------------------------------------------------------------------------------------------ LPC formants

#define NM (VX_TICK_MAX_ORDER + 1)

// Roots of the monic polynomial z^n + a[1] z^(n-1) + ... + a[n] (as numpy.roots of [1, a]) by the Aberth-Ehrlich
// iteration in double: all roots at once, cubic convergence, no matrix. Results in wr/wi[1..n]. false if it does
// not converge (a caller then has no formants for this tick, as when numpy's LPC fails).
static bool poly_roots(const double *a, int n, double wr[NM], double wi[NM]) {
    // start on a circle inside the Cauchy bound, off the axes so conjugate pairs separate
    double bound = 0.0;
    for (int i = 1; i <= n; i++) bound = fmax(bound, fabs(a[i]));
    double rad = fmin(1.0 + bound, 1.2);
    for (int i = 1; i <= n; i++) {
        double th = 2 * PI * (i - 1) / n + 0.4;
        wr[i] = rad * cos(th);
        wi[i] = rad * sin(th);
    }
    for (int it = 0; it < 200; it++) {
        double worst = 0.0;
        for (int i = 1; i <= n; i++) {
            // p(z) and p'(z) by Horner
            double zr = wr[i], zi = wi[i];
            double pr = 1.0, pi = 0.0, dr = 0.0, di = 0.0;
            for (int k = 1; k <= n; k++) {
                double ndr = dr * zr - di * zi + pr, ndi = dr * zi + di * zr + pi;
                dr = ndr;
                di = ndi;
                double npr = pr * zr - pi * zi + a[k], npi = pr * zi + pi * zr;
                pr = npr;
                pi = npi;
            }
            double dd = dr * dr + di * di;
            if (dd == 0.0 && pr == 0.0 && pi == 0.0) continue;   // exactly on a root
            double wre, wim;                                      // w = p / p'
            if (dd == 0.0) {
                wre = 1e-8;
                wim = 0.0;
            } else {
                wre = (pr * dr + pi * di) / dd;
                wim = (pi * dr - pr * di) / dd;
            }
            double sr = 0.0, si = 0.0;                            // sum 1 / (z_i - z_j)
            for (int j = 1; j <= n; j++) {
                if (j == i) continue;
                double er = zr - wr[j], ei = zi - wi[j];
                double ee = er * er + ei * ei;
                if (ee == 0.0) continue;
                sr += er / ee;
                si -= ei / ee;
            }
            // step = w / (1 - w * s)
            double br = 1.0 - (wre * sr - wim * si), bi = -(wre * si + wim * sr);
            double bb = br * br + bi * bi;
            double str, sti;
            if (bb == 0.0) {
                str = wre;
                sti = wim;
            } else {
                str = (wre * br + wim * bi) / bb;
                sti = (wim * br - wre * bi) / bb;
            }
            wr[i] = zr - str;
            wi[i] = zi - sti;
            double mag = fabs(str) + fabs(sti);
            if (mag > worst) worst = mag;
        }
        if (worst < 1e-14) return true;
    }
    // not converged to 1e-14 in 200 sweeps (clustered roots converge linearly): keep the estimates if finite
    for (int i = 1; i <= n; i++)
        if (!isfinite(wr[i]) || !isfinite(wi[i])) return false;
    return true;
}

struct Cand {
    double f, bw, lv;
};

bool vx_tick_formants(VxTick *t, const double *x, int n, double *f1, double *f2) {
    const VxTickConfig *k = &t->cfg;
    const int order = k->lpc_order;
    double *y = t->s_a;
    y[0] = x[0] * t->hamming[0];
    for (int i = 1; i < n; i++) y[i] = (x[i] - k->preemph * x[i - 1]) * t->hamming[i];
    double r[VX_TICK_MAX_ORDER + 1] = {0};
    for (int lag = 0; lag <= order; lag++) {
        double s = 0.0;
        for (int i = 0; i + lag < n; i++) s += y[i] * y[i + lag];
        r[lag] = s;
    }
    if (r[0] <= 0) return false;
    // Levinson-Durbin: a[1..order] with poly = [1, a]
    double a[VX_TICK_MAX_ORDER + 1], tmp[VX_TICK_MAX_ORDER + 1];
    a[0] = 1.0;
    double err = r[0];
    for (int i = 1; i <= order; i++) {
        double acc = r[i];
        for (int j = 1; j < i; j++) acc += a[j] * r[i - j];
        if (!(err > 0) || !isfinite(err)) return false;
        double kk = -acc / err;
        for (int j = 1; j < i; j++) tmp[j] = a[j] + kk * a[i - j];
        for (int j = 1; j < i; j++) a[j] = tmp[j];
        a[i] = kk;
        err *= 1.0 - kk * kk;
    }
    for (int i = 1; i <= order; i++)
        if (!isfinite(a[i])) return false;
    // roots of poly = [1, a] (numpy.roots)
    double wr[NM], wi[NM];
    if (!poly_roots(a, order, wr, wi)) return false;
    Cand c[VX_TICK_MAX_ORDER];
    int nc = 0;
    for (int i = 1; i <= order; i++) {
        if (!(wi[i] > 0)) continue;
        double f = atan2(wi[i], wr[i]) * k->fs / (2 * PI);
        double bw = -k->fs / PI * log(hypot(wr[i], wi[i]) + 1e-12);
        if (!(f > 150 && f < k->f2_hi + 500)) continue;
        double re = 0.0, im = 0.0;   // A(e^{-jw}) = sum a[m] e^{-j w m}
        for (int m = 0; m <= order; m++) {
            double ph = -2 * PI * f * m / k->fs;
            re += a[m] * cos(ph);
            im += a[m] * sin(ph);
        }
        double lv = -20 * log10(hypot(re, im) + 1e-12);
        int j = nc++;
        while (j > 0 && c[j - 1].f > f) {
            c[j] = c[j - 1];
            j--;
        }
        c[j] = {f, bw, lv};
    }
    // _pick_formants (voice_cursor_v2: broad F2 accepted when at least as loud as the next narrow candidate)
    double nb = k->max_bw_hz;
    int i1 = -1;
    for (int i = 0; i < nc; i++)
        if (c[i].f >= k->f1_lo && c[i].f <= k->f1_hi && c[i].bw < nb) {
            i1 = i;
            break;
        }
    if (i1 < 0) return false;
    double F1 = c[i1].f;
    int idx[VX_TICK_MAX_ORDER], m2 = 0;
    for (int i = 0; i < nc; i++)
        if (c[i].f > F1 + k->f2_min_gap_hz && c[i].f >= k->f2_lo && c[i].f <= k->f2_hi && c[i].bw < k->f2_max_bw_hz)
            idx[m2++] = i;
    for (int j = 0; j < m2; j++) {
        const Cand &e = c[idx[j]];
        bool pick = e.bw < nb;
        if (!pick) {
            int nx = -1;
            for (int q = j + 1; q < m2; q++)
                if (c[idx[q]].bw < nb) {
                    nx = idx[q];
                    break;
                }
            pick = nx < 0 || e.lv >= c[nx].lv;
        }
        if (pick) {
            *f1 = F1;
            *f2 = e.f;
            return true;
        }
    }
    return false;
}

// ------------------------------------------------------------------------------------------------ F2 continuity

static double f2_push(VxTick *t, double v) {
    const VxTickConfig *k = &t->cfg;
    if (!(k->f2_jump_hz > 0)) return v;
    int need = k->f2_jump_frames;
    if (isnan(v)) {
        t->f2_since++;
        if (t->f2_since > need) {
            t->f2_last = NAN;
            t->run_n = 0;
        }
        return NAN;
    }
    t->f2_since = 0;
    if (isnan(t->f2_last) || fabs(v - t->f2_last) <= k->f2_jump_hz) {
        t->f2_last = v;
        t->run_n = 0;
        return v;
    }
    int w = 0;
    for (int i = 0; i < t->run_n; i++)
        if (fabs(t->run[i] - v) <= k->f2_jump_hz) t->run[w++] = t->run[i];
    if (w >= VX_TICK_MAX_RUN) {   // cannot happen (a run of need is accepted), kept in bounds anyway
        memmove(t->run, t->run + 1, (size_t)(w - 1) * sizeof(double));
        w--;
    }
    t->run[w++] = v;
    t->run_n = w;
    if (w >= need) {
        t->f2_last = v;
        t->run_n = 0;
        return v;
    }
    return NAN;
}

// ------------------------------------------------------------------------------------------------ the tick

static void tick(VxTick *t, VxTickOut *o) {
    const VxTickConfig *k = &t->cfg;
    const int n = k->win;
    const double *fr = t->buf;
    double ss = 0.0, sum = 0.0;
    for (int i = 0; i < n; i++) {
        ss += fr[i] * fr[i];
        sum += fr[i];
    }
    double db = 20 * log10(sqrt(ss / n) + 1e-9);
    double fl = floor_db(t);
    double mean = sum / n;
    double *xm = t->s_a;
    for (int i = 0; i < n; i++) xm[i] = fr[i] - mean;
    double cl;
    double f0 = vx_tick_nsdf_f0(t, xm, n, &cl);
    double f1 = NAN, f2 = NAN;
    bool loud = db >= fl + k->level_over_floor_db;
    if (cl < k->clarity_on) {
        levels_add(t, db);
    } else if (loud) {
        double a, b;
        if (vx_tick_formants(t, fr, n, &a, &b)) {
            f1 = a;
            f2 = b;
        }
    }
    bool voiced = f0 > 0 && cl >= k->clarity_on && loud;
    f2 = f2_push(t, voiced ? f2 : NAN);
    if (isnan(f2)) f1 = NAN;
    o->t_ms = (double)t->n * 1000.0 / k->fs;
    o->f0 = voiced ? f0 : 0.0;
    o->f0_raw = f0;
    o->clarity = cl;
    o->db = db;
    o->floor_db = fl;
    o->f1 = f1;
    o->f2 = f2;
    o->voiced = voiced;
    o->why = voiced ? VX_TICK_WHY_NONE : !loud ? VX_TICK_WHY_QUIET : cl < k->clarity_on ? VX_TICK_WHY_UNCLEAR : VX_TICK_WHY_NO_PITCH;
}

bool vx_tick_push(VxTick *t, vx_real xin, VxTickOut *out) {
    double x = (double)xin;
    double yv = t->b0 * x + t->z1;
    t->z1 = t->b1 * x - t->a1 * yv + t->z2;
    t->z2 = t->b2 * x - t->a2 * yv;
    t->hopbuf[t->fill++] = yv;
    t->n++;
    if (t->fill < t->cfg.hop) return false;
    const int n = t->cfg.win, hop = t->cfg.hop;
    memmove(t->buf, t->buf + hop, (size_t)(n - hop) * sizeof(double));
    memcpy(t->buf + n - hop, t->hopbuf, (size_t)hop * sizeof(double));
    t->fill = 0;
    tick(t, out);
    return true;
}
