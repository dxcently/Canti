#include "vx_impl.h"
#include "vx_decim.h"
#include <string.h>

static float s_taps[VX_DECIM_TAPS];
static bool s_taps_ok = false;

static double bessel_i0(double x) {   // power series; converges fast for x <= 8
    double sum = 1.0, term = 1.0, q = x * x / 4.0;
    for (int k = 1; k < 60; k++) {
        term *= q / ((double)k * k);
        sum += term;
        if (term < 1e-17 * sum) break;
    }
    return sum;
}

// scipy.signal.firwin(63, 7200, window=("kaiser", 8.0), fs=48000): windowed sinc, scaled to unit DC gain.
const float *vx_decim_taps() {
    if (s_taps_ok) return s_taps;
    const double pi = 3.14159265358979323846;
    const int N = VX_DECIM_TAPS;
    const double cutoff = 7200.0 / 24000.0, beta = 8.0, alpha = 0.5 * (N - 1);
    double h[VX_DECIM_TAPS], s = 0.0;
    for (int n = 0; n < N; n++) {
        double m = n - alpha;
        double x = cutoff * m;
        double sinc = x == 0.0 ? 1.0 : sin(pi * x) / (pi * x);
        double r = 2.0 * n / (N - 1) - 1.0;
        double w = bessel_i0(beta * sqrt(1.0 - r * r)) / bessel_i0(beta);
        h[n] = cutoff * sinc * w;
        s += h[n];
    }
    for (int n = 0; n < N; n++) s_taps[n] = (float)(h[n] / s);
    s_taps_ok = true;
    return s_taps;
}

void vx_decim_reset(VxDecim3 *d) {
    vx_decim_taps();
    memset(d->hist, 0, sizeof(d->hist));
    d->phase = 0;
}

int vx_decim_push(VxDecim3 *d, const vx_real *x, int n, vx_real *out) {
    const float *h = s_taps;
    const int H = VX_DECIM_TAPS - 1;
    int nout = 0;
    for (int i = d->phase; i < n; i += 3) {
        // buf = hist ++ x; output at x index i uses buf[i .. i + 62], i.e. x[i - 62 .. i]; h reversed
        vx_real acc = 0;
        for (int k = 0; k < VX_DECIM_TAPS; k++) {
            int j = i - k;                        // x index of tap k
            vx_real v = j >= 0 ? x[j] : d->hist[H + j];
            acc += (vx_real)h[k] * v;
        }
        out[nout++] = (vx_real)(float)acc;        // the reference returns float32
    }
    // new history: the last 62 samples of hist ++ x
    if (n >= H) {
        memcpy(d->hist, x + n - H, sizeof(vx_real) * H);
    } else {
        memmove(d->hist, d->hist + n, sizeof(vx_real) * (H - n));
        memcpy(d->hist + H - n, x, sizeof(vx_real) * n);
    }
    d->phase = ((d->phase - n) % 3 + 3) % 3;
    return nout;
}
