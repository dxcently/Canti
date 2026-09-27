#include "vx_impl.h"
#include "vx_fingerprint.h"

static double log2_(double x) { return log2(x); }

void vx_fingerprint(const VxSegStats *seg, VxRaw *raw) {
    double f0 = raw->f0_med_hz;
    bool pitched = f0 > 0 && raw->has_shape;
    double cent = raw->centroid_hz;
    double pb = (double)seg->p_band_sum, pv = (double)seg->p_voiced_sum;
    double e1k = pb > 0 ? (double)seg->p_1k6_sum / pb : 0.0;
    double e35 = pv > 0 ? (double)seg->p_hi35_sum / pv : 0.0;
    double v[VX_FP_LEN];
    v[0] = f0 > 0 ? log2_(f0 / 100.0) : -3.0;
    v[1] = pitched ? raw->max_st - raw->min_st : 0.0;
    v[2] = raw->pitch_resid_std_st;
    v[3] = raw->pitch_rough_st;
    v[4] = raw->voiced_frac;
    v[5] = raw->strong_voiced_frac;
    v[6] = raw->clarity_med;
    v[7] = log2_((cent > 50.0 ? cent : 50.0) / 1000.0);
    v[8] = raw->centroid_spread_oct;
    v[9] = raw->flatness;
    v[10] = raw->zcr;
    v[11] = raw->lf_ratio;
    v[12] = raw->hf_ratio;
    v[13] = e1k;
    v[14] = e35;
    v[15] = log2_((raw->dur_ms > 10 ? raw->dur_ms : 10) / 100.0);
    v[16] = raw->energy_iqr_db;
    v[17] = raw->flux_mean_db;
    v[18] = raw->onset_flux_db;
    v[19] = raw->decay_db;
    // cep1..cep4: orthonormal DCT-II coefficients 1-4 of the 8 log mel-band powers
    double L[VX_N_MEL];
    for (int i = 0; i < VX_N_MEL; i++) L[i] = 10.0 * log10((double)seg->mel8_sum[i] + 1e-12);
    const double pi = 3.14159265358979323846;
    for (int k = 1; k <= 4; k++) {
        double s = 0;
        for (int i = 0; i < VX_N_MEL; i++) s += L[i] * cos(pi * k * (i + 0.5) / VX_N_MEL);
        v[19 + k] = sqrt(2.0 / VX_N_MEL) * s;
    }
    for (int i = 0; i < VX_FP_LEN; i++) raw->fp[i] = (float)vx_py_round(v[i], 4);
}
