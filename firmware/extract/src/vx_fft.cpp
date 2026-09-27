#include "vx_impl.h"
#include "vx_fft.h"
#include <stdint.h>

static vx_real s_tw[VX_MAX_ACF];        // interleaved cos, -sin of 2 pi k / VX_MAX_ACF, k < VX_MAX_ACF / 2
static vx_real s_z[VX_MAX_ACF];         // work: VX_MAX_ACF / 2 complex values, interleaved
static bool s_init = false;

void vx_fft_init() {
    if (s_init) return;
    const double pi = 3.14159265358979323846;
    for (int k = 0; k < VX_MAX_ACF / 2; k++) {
        double a = 2.0 * pi * k / VX_MAX_ACF;
        s_tw[2 * k] = (vx_real)cos(a);
        s_tw[2 * k + 1] = (vx_real)-sin(a);
    }
    s_init = true;
}

// Bit-reversal permutation as a list of swaps, cached for the two sizes the front end uses per hop
struct RevTable {
    int m, n;
    uint16_t ij[2 * 256];                // up to 256 swaps (m <= 512)
};
static RevTable s_rev[2];

VX_HOT static const RevTable *rev_table(int m) {
    for (auto &t : s_rev)
        if (t.m == m) return &t;
    RevTable *t = s_rev[0].m == 0 ? &s_rev[0] : &s_rev[1];   // (a third size would recompute: not used)
    t->m = m;
    t->n = 0;
    for (int i = 1, j = 0; i < m; i++) {
        int bit = m >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j && t->n < 256) {
            t->ij[2 * t->n] = (uint16_t)i;
            t->ij[2 * t->n + 1] = (uint16_t)j;
            t->n++;
        }
    }
    return t;
}

// In-place forward complex FFT of m points (m power of two, m <= VX_MAX_ACF / 2), interleaved re/im.
// Radix-2 decimation in time, with pairs of stages merged into one pass over the data (radix-2^2): the same
// complex products, sums and twiddle table entries as the plain radix-2 loop, in the same order, so the results
// are bit-identical to it; only the loads, stores and loop overhead are halved.
// upper_zero: the input's upper half is zero (zero padding): the first stage is then a copy.
VX_HOT static void cfft(vx_real *a, int m, bool upper_zero) {
    if (m <= 512) {
        const RevTable *t = rev_table(m);
        for (int s = 0; s < t->n; s++) {
            int i = t->ij[2 * s], j = t->ij[2 * s + 1];
            vx_real tr = a[2 * i], ti = a[2 * i + 1];
            a[2 * i] = a[2 * j];
            a[2 * i + 1] = a[2 * j + 1];
            a[2 * j] = tr;
            a[2 * j + 1] = ti;
        }
    } else {
        for (int i = 1, j = 0; i < m; i++) {
            int bit = m >> 1;
            for (; j & bit; bit >>= 1) j ^= bit;
            j ^= bit;
            if (i < j) {
                vx_real tr = a[2 * i], ti = a[2 * i + 1];
                a[2 * i] = a[2 * j];
                a[2 * i + 1] = a[2 * j + 1];
                a[2 * j] = tr;
                a[2 * j + 1] = ti;
            }
        }
    }
    int log2m = 0;
    while ((1 << log2m) < m) log2m++;
    int h = 1;   // spans of h points are done
    if (log2m & 1) {
        // the len-2 stage alone (twiddle 1: v = q exactly)
        for (int i = 0; i < m; i += 2) {
            vx_real *p = a + 2 * i;
            if (upper_zero) {   // bit reversal put the zero half at the odd positions: p + 0
                p[2] = p[0];
                p[3] = p[1];
            } else {
                vx_real ur = p[0], ui = p[1], vr = p[2], vi = p[3];
                p[0] = ur + vr;
                p[1] = ui + vi;
                p[2] = ur - vr;
                p[3] = ui - vi;
            }
        }
        h = 2;
    }
    for (; 4 * h <= m; h *= 4) {
        const int sa = VX_MAX_ACF / (2 * h);   // stage A (len 2h): W_2h^k
        const int sb = VX_MAX_ACF / (4 * h);   // stage B (len 4h): W_4h^k and W_4h^(k+h)
        for (int i = 0; i < m; i += 4 * h) {
            vx_real *x0 = a + 2 * i, *x1 = x0 + 2 * h, *x2 = x1 + 2 * h, *x3 = x2 + 2 * h;
            for (int k = 0; k < h; k++) {
                const vx_real *w1 = s_tw + 2 * k * sa, *w2 = s_tw + 2 * k * sb, *w3 = s_tw + 2 * (k + h) * sb;
                vx_real vr, vi;
                // stage A: (x0, x1) and (x2, x3) with W_2h^k
                vr = x1[2 * k] * w1[0] - x1[2 * k + 1] * w1[1];
                vi = x1[2 * k] * w1[1] + x1[2 * k + 1] * w1[0];
                vx_real a0r = x0[2 * k] + vr, a0i = x0[2 * k + 1] + vi;
                vx_real a1r = x0[2 * k] - vr, a1i = x0[2 * k + 1] - vi;
                vr = x3[2 * k] * w1[0] - x3[2 * k + 1] * w1[1];
                vi = x3[2 * k] * w1[1] + x3[2 * k + 1] * w1[0];
                vx_real a2r = x2[2 * k] + vr, a2i = x2[2 * k + 1] + vi;
                vx_real a3r = x2[2 * k] - vr, a3i = x2[2 * k + 1] - vi;
                // stage B: (a0, a2) with W_4h^k, (a1, a3) with W_4h^(k+h)
                vr = a2r * w2[0] - a2i * w2[1];
                vi = a2r * w2[1] + a2i * w2[0];
                x0[2 * k] = a0r + vr;
                x0[2 * k + 1] = a0i + vi;
                x2[2 * k] = a0r - vr;
                x2[2 * k + 1] = a0i - vi;
                vr = a3r * w3[0] - a3i * w3[1];
                vi = a3r * w3[1] + a3i * w3[0];
                x1[2 * k] = a1r + vr;
                x1[2 * k + 1] = a1i + vi;
                x3[2 * k] = a1r - vr;
                x3[2 * k + 1] = a1i - vi;
            }
        }
    }
}

VX_HOT void vx_rfft_power(const vx_real *x, int n, int nfft, vx_real *p) {
    int m = nfft / 2;
    vx_real *z = s_z;
    for (int i = 0; i < m; i++) {
        int a = 2 * i, b = 2 * i + 1;
        z[2 * i] = a < n ? x[a] : 0;
        z[2 * i + 1] = b < n ? x[b] : 0;
    }
    cfft(z, m, 2 * n <= nfft);
    int stride = VX_MAX_ACF / nfft;         // W_nfft^k = W_MAX^(k * stride)
    vx_real r0 = z[0], i0 = z[1];
    p[0] = (r0 + i0) * (r0 + i0);
    p[m] = (r0 - i0) * (r0 - i0);
    for (int k = 1; k < m; k++) {
        vx_real ar = z[2 * k], ai = z[2 * k + 1];
        vx_real br = z[2 * (m - k)], bi = -z[2 * (m - k) + 1];     // conj(Z[m-k])
        vx_real er = VXF(0.5) * (ar + br), ei = VXF(0.5) * (ai + bi);
        // O = (A - B) / (2i) = (dI - i dR) / 2 with d = A - B
        vx_real dr = ar - br, di = ai - bi;
        vx_real orr = VXF(0.5) * di, oi = VXF(-0.5) * dr;
        vx_real wr = s_tw[2 * k * stride], wi = s_tw[2 * k * stride + 1];
        vx_real xr = er + (orr * wr - oi * wi);
        vx_real xi = ei + (orr * wi + oi * wr);
        p[k] = xr * xr + xi * xi;
    }
}

VX_HOT void vx_irfft_real(const vx_real *P, int nfft, vx_real *r, int nout) {
    int m = nfft / 2;
    int stride = VX_MAX_ACF / nfft;
    vx_real *z = s_z;
    // Z[k] = E[k] + i O[k], E = (X[k] + conj X[m-k]) / 2, O = (X[k] - conj X[m-k]) / 2 * W^-k; X real here.
    // The inverse FFT is done as conj(FFT(conj(Z))) / m, so store conj(Z) directly.
    for (int k = 0; k < m; k++) {
        vx_real a = P[k], b = P[m - k];
        vx_real e = VXF(0.5) * (a + b);
        vx_real d = VXF(0.5) * (a - b);
        vx_real wr = s_tw[2 * k * stride], wi = -s_tw[2 * k * stride + 1];   // W^-k = cos + i sin
        vx_real or_ = d * wr, oi = d * wi;
        // Z = e + i (or_ + i oi) = (e - oi) + i or_
        z[2 * k] = e - oi;
        z[2 * k + 1] = -or_;                 // conj
    }
    cfft(z, m, false);
    vx_real s = VXF(1.0) / (vx_real)m;
    for (int t = 0; t < nout; t++) {
        int n = t >> 1;
        r[t] = (t & 1) ? -z[2 * n + 1] * s : z[2 * n] * s;   // conj, then even = Re, odd = Im
    }
}
