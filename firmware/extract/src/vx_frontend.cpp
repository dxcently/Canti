#include "vx_impl.h"
#include "vx_frontend.h"
#include <string.h>
#include "vx_fft.h"

static double hz_to_mel(double f) { return 2595.0 * log10(1.0 + f / 700.0); }
static double mel_to_hz(double m) { return 700.0 * (pow(10.0, m / 2595.0) - 1.0); }

// A product of positive normal numbers kept as m * 2^e with m in [0.5, 1): no underflow or overflow however many
// factors, and each factor adds one rounding (~6e-8 relative in float32), so ln of a 241-bin product is as exact
// as summing 241 separate logs, for one log call instead of 241.
struct VxProd {
    vx_real m;
    int e;
};

static inline vx_real prod_frexp(vx_real x, int *e) {
#ifdef VX_REAL_DOUBLE
    return frexp(x, e);
#else
    uint32_t b;   // x is a positive normal float here: exponent field 1..254
    memcpy(&b, &x, 4);
    *e = (int)((b >> 23) & 0xff) - 126;
    b = (b & 0x807fffffu) | (126u << 23);
    memcpy(&x, &b, 4);
    return x;
#endif
}

static inline void prod_mul(VxProd *a, vx_real v) {
    int e;
    a->m = prod_frexp(a->m * v, &e);
    a->e += e;
}

static inline double prod_ln(const VxProd *a) { return log((double)a->m) + a->e * 0.6931471805599453; }

void vx_frontend_init(VxFrontend *fe, const VxConfig *cfg) {
    vx_fft_init();
    const double pi = 3.14159265358979323846;
    int n = cfg->win;
    fe->n = n;
    fe->hop = cfg->hop;
    fe->nfft_acf = cfg->acf_fft;
    fe->sr = cfg->sample_rate;
    // scipy butter(2, hpf_hz / (sr / 2), "high"): bilinear transform with pre-warping
    double K = tan(pi * cfg->hpf_hz / cfg->sample_rate);
    double norm = 1.0 / (1.0 + sqrt(2.0) * K + K * K);
    fe->b0 = (vx_real)norm;
    fe->b1 = (vx_real)(-2.0 * norm);
    fe->b2 = (vx_real)norm;
    fe->a1 = (vx_real)(2.0 * (K * K - 1.0) * norm);
    fe->a2 = (vx_real)((1.0 - sqrt(2.0) * K + K * K) * norm);
    double wp = 0.0;
    for (int i = 0; i < n; i++) {
        double w = 0.5 - 0.5 * cos(2.0 * pi * i / n);   // periodic Hann
        fe->window[i] = (vx_real)w;
        wp += w * w;
    }
    fe->win_pow = (vx_real)wp;
    double df = (double)cfg->sample_rate / n;
    fe->df = (vx_real)df;
    fe->k_lo = (int)ceil(cfg->spec_lo_hz / df);
    fe->k_hi = (int)floor(cfg->spec_hi_hz / df);
    fe->k_lf = (int)floor(cfg->lf_split_hz / df);
    fe->k_hf = (int)ceil(cfg->hf_split_hz / df);
    fe->k_1k = (int)ceil(1000.0 / df);
    fe->k_6k = (int)floor(6000.0 / df);
    for (int k = 0; k <= n / 2; k++) fe->freqs[k] = (vx_real)(k * df);
    fe->tau_min = (int)floor(cfg->sample_rate / cfg->f0_max_hz);
    if (fe->tau_min < 2) fe->tau_min = 2;
    fe->tau_max = (int)ceil(cfg->sample_rate / cfg->f0_min_hz);
    if (fe->tau_max > n - 2) fe->tau_max = n - 2;
    fe->mpm_k = (vx_real)cfg->mpm_k;
    fe->voiced_clarity = (vx_real)cfg->voiced_clarity;
    fe->flux_floor_db = (vx_real)cfg->flux_floor_db;
    // mel filterbank (frontend.mel_filterbank(8, n, sr, 60, 7600)), stored sparsely
    double pts[VX_N_MEL + 2];
    double m0 = hz_to_mel(60.0), m1 = hz_to_mel(7600.0);
    for (int i = 0; i < VX_N_MEL + 2; i++) {
        // np.linspace: start + i * step, the last point exactly the stop
        double mv = i == VX_N_MEL + 1 ? m1 : m0 + i * ((m1 - m0) / (VX_N_MEL + 1));
        pts[i] = mel_to_hz(mv);
    }
    int off = 0;
    for (int i = 0; i < VX_N_MEL; i++) {
        double a = pts[i], c = pts[i + 1], b = pts[i + 2];
        int k0 = -1, k1 = -1;
        for (int k = 0; k <= n / 2; k++) {
            double f = k * df;
            double w = fmin((f - a) / (c - a), (b - f) / (b - c));
            if (w > 0.0) {
                if (k0 < 0) k0 = k;
                k1 = k;
            }
        }
        fe->mel_k0[i] = k0 < 0 ? 0 : k0;
        fe->mel_len[i] = k0 < 0 ? 0 : k1 - k0 + 1;
        fe->mel_off[i] = off;
        for (int k = fe->mel_k0[i]; k < fe->mel_k0[i] + fe->mel_len[i]; k++) {
            double f = k * df;
            double w = fmin((f - a) / (c - a), (b - f) / (b - c));
            fe->mel_w[off++] = (vx_real)(w > 0.0 ? w : 0.0);
        }
    }
    fe->pitch_enabled = true;
    fe->floor_init = (vx_real)cfg->floor_min_db;
    vx_frontend_reset(fe);
}

void vx_frontend_reset(VxFrontend *fe) {
    fe->z1 = fe->z2 = 0;
    memset(fe->buf, 0, sizeof(fe->buf));
    fe->fill = 0;
    fe->index = 0;
    fe->floor_db = fe->floor_init;
    fe->have_prev = false;
}

VX_HOT bool vx_frontend_push(VxFrontend *fe, vx_real x) {
    // scipy lfilter, transposed direct form II: y = z1 + b0 x; z1 = z2 + b1 x - a1 y; z2 = b2 x - a2 y
    vx_real y = fe->z1 + fe->b0 * x;
    fe->z1 = fe->z2 + x * fe->b1 - y * fe->a1;
    fe->z2 = x * fe->b2 - y * fe->a2;
    // the window holds n samples: the hop being filled goes into the tail (shifted once per hop)
    fe->buf[fe->n - fe->hop + fe->fill] = y;
    if (++fe->fill < fe->hop) return false;
    fe->fill = 0;
    return true;
}

VX_HOT vx_real vx_mpm_pitch(VxFrontend *fe, const vx_real *x, vx_real *clarity) {
    const int n = fe->n, tau_max = fe->tau_max, tau_min = fe->tau_min;
    *clarity = 0;
    vx_rfft_power(x, n, fe->nfft_acf, fe->acf_p);
    VX_PROF(5);
    vx_irfft_real(fe->acf_p, fe->nfft_acf, fe->r, tau_max + 2);
    VX_PROF(6);
    // m'(tau) = sum_{j=0}^{n-1-tau} (x_j^2 + x_{j+tau}^2), from the cumulative sum of x^2 (as the reference)
    vx_real *c = fe->m;   // reuse: c[j] = cumsum(x^2)[j] for j < n
    vx_real acc = 0;
    for (int j = 0; j < n; j++) {
        acc += x[j] * x[j];
        c[j] = acc;
    }
    vx_real *nsdf = fe->r;   // in place: nsdf[tau] = 2 r / max(m, 1e-20)
    vx_real m0 = c[n - 1] + c[n - 1];
    if (m0 <= VXF(1e-20)) return 0;
    for (int t = 0; t <= tau_max + 1; t++) {
        vx_real head = c[n - 1 - t];
        vx_real tail = c[n - 1] - (t > 0 ? c[t - 1] : 0);
        vx_real m = head + tail;
        if (m < VXF(1e-20)) m = VXF(1e-20);
        nsdf[t] = VXF(2.0) * nsdf[t] / m;
    }
    // key maxima: the highest point of each positive lobe after the first negative-going zero crossing
    int t = 1;
    while (t <= tau_max && nsdf[t] > 0) t++;
    int best = -1;
    // first pass: the highest key maximum (within tau_min..tau_max)
    vx_real top = 0;
    bool any = false;
    int t0 = t;
    for (; t <= tau_max; t++) {
        if (nsdf[t] > 0) {
            if (best < 0 || nsdf[t] > nsdf[best]) best = t;
        } else if (best >= 0) {
            if (best >= tau_min && (!any || nsdf[best] > top)) top = nsdf[best], any = true;
            best = -1;
        }
    }
    if (best >= 0 && best < tau_max && best >= tau_min && (!any || nsdf[best] > top)) top = nsdf[best], any = true;
    if (!any) return 0;
    vx_real thr = fe->mpm_k * top;
    // second pass: the first key maximum >= thr
    int p = -1;
    best = -1;
    for (t = t0; t <= tau_max && p < 0; t++) {
        if (nsdf[t] > 0) {
            if (best < 0 || nsdf[t] > nsdf[best]) best = t;
        } else if (best >= 0) {
            if (best >= tau_min && nsdf[best] >= thr) p = best;
            best = -1;
        }
    }
    if (p < 0 && best >= 0 && best < tau_max && best >= tau_min && nsdf[best] >= thr) p = best;
    if (p < 0) return 0;   // cannot happen (top itself qualifies)
    vx_real a = nsdf[p - 1], b = nsdf[p], cc = nsdf[p + 1];
    vx_real den = a - VXF(2.0) * b + cc;
    vx_real delta = (den > VXF(1e-12) || den < VXF(-1e-12)) ? VXF(0.5) * (a - cc) / den : 0;
    if (delta < VXF(-0.5)) delta = VXF(-0.5);
    if (delta > VXF(0.5)) delta = VXF(0.5);
    vx_real tau = (vx_real)p + delta;
    vx_real cl = b - VXF(0.25) * (a - cc) * delta;
    *clarity = cl < VXF(1.0) ? cl : VXF(1.0);
    return (vx_real)fe->sr / tau;
}

VX_HOT void vx_frontend_frame(VxFrontend *fe, VxFrame *f) {
    const int n = fe->n, hop = fe->hop;
    const vx_real *x = fe->buf;
    const int c = n / 2;
    VX_PROF(0);
    // energy: mean square of the central hop
    vx_real e = 0;
    for (int i = c - hop / 2; i < c + hop / 2; i++) e += x[i] * x[i];
    e /= (vx_real)(2 * (hop / 2));
    f->e_db = VXF(10.0) * VX_LOG10(e + VXF(1e-12));
    // zero crossings (sign bit changes) over the central 2 hops
    int zc = 0;
    for (int i = c - hop + 1; i < c + hop; i++) zc += signbit(x[i]) != signbit(x[i - 1]);
    f->zcr = (vx_real)zc / (vx_real)(2 * hop - 1);

    // windowed power spectrum
    vx_real *tmp = fe->wx;
    for (int i = 0; i < n; i++) tmp[i] = x[i] * fe->window[i];
    vx_real *p = fe->p;
    VX_PROF(1);
    vx_rfft_power(tmp, n, n, p);
    VX_PROF(2);
    const int k_lo = fe->k_lo, k_hi = fe->k_hi;
    vx_real total = 0, fsum = 0, lsum = 0, lf = 0, hf = 0;
    for (int k = k_lo; k <= k_hi; k++) total += p[k];
    if (total > VXF(1e-20)) {
        // sum of ln(p + 1e-30) as ln of the product (one log per frame instead of one per bin; see VxProd)
        VxProd pr = {VXF(1.0), 0};
        for (int k = k_lo; k <= k_hi; k++) {
            fsum += fe->freqs[k] * p[k];
            prod_mul(&pr, p[k] + VXF(1e-30));
        }
        lsum = (vx_real)prod_ln(&pr);
        int nb = k_hi - k_lo + 1;
        for (int k = k_lo; k < fe->k_lf; k++) lf += p[k];
        for (int k = fe->k_hf; k <= k_hi; k++) hf += p[k];
        f->centroid = fsum / total;
        f->flatness = VX_EXP(lsum / (vx_real)nb) / (total / (vx_real)nb);
        f->lf_ratio = lf / total;
        f->hf_ratio = hf / total;
    } else {
        f->centroid = f->flatness = f->lf_ratio = f->hf_ratio = 0;
    }
    VX_PROF(3);
    // flux: positive log-spectral change, each bin floored at the expected power of white noise at the floor + 3 dB
    vx_real fl = fe->floor_db > fe->flux_floor_db ? fe->floor_db : fe->flux_floor_db;
    vx_real floor_p = VXF(2.0) * VX_POW(VXF(10.0), fl / VXF(10.0)) * fe->win_pow;
    // sum over bins of max(0, 10 log10(cur / prev)) = 10 log10(prod cur / prod prev) over the bins where cur > prev,
    // with cur = p + floor_p (the reference's per-bin 10 log10 difference, one log pair per frame instead of 482)
    VxProd up = {VXF(1.0), 0}, dn = {VXF(1.0), 0};
    for (int k = k_lo; k <= k_hi; k++) {
        vx_real cur = p[k] + floor_p;
        if (fe->have_prev && cur > fe->prev_lin[k]) {
            prod_mul(&up, cur);
            prod_mul(&dn, fe->prev_lin[k]);
        }
        fe->prev_lin[k] = cur;
    }
    f->flux = fe->have_prev ? (vx_real)((prod_ln(&up) - prod_ln(&dn)) * 4.342944819032518 / (k_hi - k_lo + 1)) : 0;
    fe->have_prev = true;

    VX_PROF(4);
    // pitch
    if (fe->pitch_enabled) f->f0 = vx_mpm_pitch(fe, x, &f->clarity);
    else f->f0 = f->clarity = 0;

    VX_PROF(7);
    // fp1 sums
    for (int i = 0; i < VX_N_MEL; i++) {
        vx_real s = 0;
        const vx_real *wt = fe->mel_w + fe->mel_off[i];
        const vx_real *pp = p + fe->mel_k0[i];
        for (int k = 0; k < fe->mel_len[i]; k++) s += wt[k] * pp[k];
        f->mel8[i] = s;
    }
    vx_real s16 = 0;
    for (int k = fe->k_1k; k <= fe->k_6k; k++) s16 += p[k];
    f->p_band = total;
    f->p_1k6 = s16;
    f->p_voiced = f->p_hi35 = 0;
    if (f->f0 > 0 && f->clarity >= fe->voiced_clarity) {
        f->p_voiced = total;
        int k35 = (int)VX_FLOOR(VXF(3.5) * f->f0 / fe->df) + 1;
        if (k35 < k_lo) k35 = k_lo;
        vx_real s = 0;
        for (int k = k35; k <= k_hi; k++) s += p[k];
        f->p_hi35 = s;
    }
    f->index = fe->index;
    // 64-bit: in 32 bits, sample count x 1000 overflows at 2^31 / 1000 samples = 134 s of stream at 16 kHz, and every
    // later sound got t = 0 and dur = 0 ("very short"). int32 t_ms itself lasts 24.8 days.
    f->t_ms = (int32_t)(((int64_t)(fe->index + 1) * hop - n / 2 - hop / 2) * 1000 / fe->sr);
    fe->index++;
    // slide the window by one hop for the next frame
    memmove(fe->buf, fe->buf + hop, sizeof(vx_real) * (n - hop));
    VX_PROF(8);
}
